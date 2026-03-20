"""
Proxy MVRV / NUPL / SOPR по plan.md §8.10 — ряды price / market_cap / volume.

Источник рядов для proxy §8.10 — только plan01: :func:`build_market_history` (FreeCryptoAPI + SQLite).
Запрос CoinGecko ``market_chart`` здесь не используется; ``_fetch_market_chart_payload`` остаётся
для :class:`CoinGeckoMarketDataSource.get_history` в цепочке рынка.

Glassnode / LookIntoBitcoin в `onchain.py` подключаются опционально и дозаполняют пропуски.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from bit_trend.config.loader import get_scoring_config

from .http_client import http_get
from .market_source import build_market_history

logger = logging.getLogger(__name__)

COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
REQUEST_TIMEOUT = 25

USE_COINGECKO_ONCHAIN = os.environ.get("USE_COINGECKO_ONCHAIN", "true").lower() in ("true", "1", "yes")

# Минимум строк (дней при дневных снимках) для rolling-окон §8.10; совпадает с прежним порогом CoinGecko.
_MIN_PROXY_ROWS_DEFAULT = 400

# Прокси-модель — ниже, чем у LTB/Glassnode; conservative meta для UI
PROXY_CONFIDENCE = float(os.environ.get("COINGECKO_ONCHAIN_CONFIDENCE", "0.55"))
PROXY_SOURCE_SCORE = float(os.environ.get("COINGECKO_ONCHAIN_SOURCE_SCORE", "0.52"))

_bundle_time: Optional[datetime] = None
_bundle_payload: Optional[Dict[str, Any]] = None
_bundle_df: Optional[pd.DataFrame] = None
_BUNDLE_TTL = timedelta(seconds=int(os.environ.get("COINGECKO_BUNDLE_CACHE_SEC", "120")))


def _env_onchain_proxy_history_days() -> int:
    """Глубина окна для build_market_history (по умолчанию макс. как у FreeCrypto getHistory)."""
    raw = os.environ.get("ONCHAIN_PROXY_HISTORY_DAYS", "3650").strip() or "3650"
    try:
        d = int(raw)
    except ValueError:
        d = 3650
    return max(_MIN_PROXY_ROWS_DEFAULT, min(3650, d))


def _env_onchain_proxy_min_rows() -> int:
    raw = os.environ.get("ONCHAIN_PROXY_MIN_ROWS", str(_MIN_PROXY_ROWS_DEFAULT)).strip() or str(
        _MIN_PROXY_ROWS_DEFAULT
    )
    try:
        n = int(raw)
    except ValueError:
        n = _MIN_PROXY_ROWS_DEFAULT
    return max(200, min(2000, n))


def _btc_supply_estimate_for_proxy() -> float:
    """Если у ряда нет market_cap (Binance и т.п.), кап ≈ price × оценка circulating supply BTC."""
    raw = os.environ.get("ONCHAIN_PROXY_BTC_SUPPLY_EST", "19500000").strip() or "19500000"
    try:
        s = float(raw)
    except ValueError:
        s = 19_500_000.0
    return max(1.0, s)


def _impute_market_cap_from_price(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    supply = _btc_supply_estimate_for_proxy()
    need = out["market_cap"].isna()
    if need.any():
        prices = pd.to_numeric(out.loc[need, "price"], errors="coerce")
        out.loc[need, "market_cap"] = prices * supply
        n = int(need.sum())
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "proxy §8.10: market_cap = price×%.0f для %d строк (источник без капа; см. ONCHAIN_PROXY_BTC_SUPPLY_EST)",
                supply,
                n,
            )
    return out


def _dataframe_from_market_history(hist: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Нормализованный ряд market_source → индекс UTC-время, колонки для :func:`_enrich_810`.
    """
    if hist is None or hist.empty:
        return None
    min_rows = _env_onchain_proxy_min_rows()
    df = hist.copy()
    df = df.dropna(subset=["timestamp", "price"])
    df = _impute_market_cap_from_price(df)
    df = df.dropna(subset=["market_cap"])
    df = df[df["market_cap"] > 0]
    if len(df) < min_rows:
        logger.warning(
            "История для proxy §8.10: мало строк (%d < %d). Только plan01: "
            "FREECRYPTO_API_TOKEN + getHistory и/или снимки в SQLite market_data (collect_daily_snapshot).",
            len(df),
            min_rows,
        )
        return None
    df = df.sort_values("timestamp")
    if "volume" not in df.columns:
        df["volume"] = np.nan
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").ffill().fillna(0.0)
    df = df.set_index("timestamp")
    return df[["price", "market_cap", "volume"]]


def clear_coingecko_bundle_cache() -> None:
    """Сброс кэша бандла (например при clear_cache у DataFetcher)."""
    global _bundle_time, _bundle_payload, _bundle_df
    _bundle_time = None
    _bundle_payload = None
    _bundle_df = None


def _last_finite(series: pd.Series) -> Optional[float]:
    s = series.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def rolling_z(series: pd.Series, window: int = 365, min_periods: int = 30) -> pd.Series:
    """(x − rolling_mean) / rolling_std — plan.md §8.10."""
    m = series.rolling(window, min_periods=min_periods).mean()
    s = series.rolling(window, min_periods=min_periods).std()
    return (series - m) / s.replace(0, np.nan)


def _fetch_market_chart_payload() -> Optional[dict]:
    headers = {"User-Agent": "BitTrend/1.0 (onchain proxy)"}
    # Без ключа часть окружений получает 401; demo/pro — см. документацию CoinGecko
    demo = os.environ.get("COINGECKO_DEMO_API_KEY", "").strip()
    pro = os.environ.get("COINGECKO_PRO_API_KEY", "").strip()
    if pro:
        headers["x-cg-pro-api-key"] = pro
    elif demo:
        headers["x-cg-demo-api-key"] = demo

    try:
        r = http_get(
            COINGECKO_CHART_URL,
            params={"vs_currency": "usd", "days": "max"},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if not r.ok:
            if r.status_code == 401:
                logger.warning(
                    "CoinGecko market_chart: HTTP 401 — для CoinGeckoMarketDataSource.get_history "
                    "нужен COINGECKO_DEMO_API_KEY или COINGECKO_PRO_API_KEY. "
                    "Прокси §8.10 в приложении строится из build_market_history (FreeCrypto+БД), не из этого запроса."
                )
            else:
                logger.warning("CoinGecko market_chart: HTTP %s", r.status_code)
            return None
        return r.json()
    except Exception as e:
        logger.warning("CoinGecko market_chart: ошибка запроса: %s", e)
        return None


def _dataframe_from_payload(payload: dict) -> Optional[pd.DataFrame]:
    prices = payload.get("prices") or []
    caps = payload.get("market_caps") or []
    vols = payload.get("total_volumes") or []
    if len(prices) < 400:
        logger.warning("CoinGecko: недостаточно точек для rolling окон (%d)", len(prices))
        return None

    n = min(len(prices), len(caps), len(vols))
    if n < 400:
        logger.warning("CoinGecko: после выравнивания рядов слишком мало точек (%d)", n)
        return None

    df = pd.DataFrame(
        {
            "ts": pd.to_datetime([prices[i][0] for i in range(n)], unit="ms", utc=True),
            "price": [float(prices[i][1]) for i in range(n)],
            "market_cap": [float(caps[i][1]) for i in range(n)],
            "volume": [float(vols[i][1]) for i in range(n)],
        }
    )
    df = df.set_index("ts")
    return df.dropna(subset=["price", "market_cap"])


def _load_proxy_input_dataframe_with_meta() -> tuple[Optional[pd.DataFrame], Dict[str, str]]:
    """
    Только plan01: :func:`build_market_history` (FreeCryptoAPI + SQLite), без CoinGecko для proxy.

    Второй элемент — provenance для :func:`_row_to_public_dict` (пустой dict при отказе).
    """
    days = _env_onchain_proxy_history_days()
    hist = build_market_history("BTC", days)
    df = _dataframe_from_market_history(hist)
    if df is None:
        return None, {}
    return df, {
        "source": "market_history",
        "method": "build_market_history_proxy",
        "parser_version": "market_history_v1",
    }


def _load_proxy_input_dataframe() -> Optional[pd.DataFrame]:
    """Обратная совместимость тестов: только кадр без meta."""
    df, _ = _load_proxy_input_dataframe_with_meta()
    return df


def _enrich_810(df: pd.DataFrame) -> pd.DataFrame:
    """Все прокси и z-ряды по §8.10 (один проход по df)."""
    cg = get_scoring_config().coingecko_composite
    zw, zmin = cg.z_window, cg.z_min_periods

    df = df.copy()
    df["supply"] = df["market_cap"] / df["price"].replace(0, np.nan)
    df["rv_180"] = df["price"].rolling(180, min_periods=60).mean() * df["supply"]
    df["rv_365"] = df["price"].rolling(365, min_periods=90).mean() * df["supply"]
    df["rv_730"] = df["price"].rolling(730, min_periods=180).mean() * df["supply"]

    rv_mix = 0.5 * df["rv_730"] + 0.3 * df["rv_365"] + 0.2 * df["rv_180"]
    df["mvrv_proxy"] = df["market_cap"] / rv_mix.replace(0, np.nan)

    df["nupl_proxy"] = (df["market_cap"] - df["rv_730"]) / df["market_cap"].replace(0, np.nan)

    ma30 = df["price"].rolling(30, min_periods=14).mean()
    df["price_vs_ma"] = df["price"] / ma30.replace(0, np.nan)
    vol_ma = df["volume"].rolling(14, min_periods=7).mean()
    df["volume_change"] = df["volume"] / vol_ma.replace(0, np.nan)
    ma365 = df["price"].rolling(365, min_periods=90).mean()
    df["sopr_simple"] = df["price"] / ma365.replace(0, np.nan)
    df["sopr_proxy"] = df["price_vs_ma"] * df["volume_change"]

    df["returns"] = df["price"].pct_change()
    df["volatility_30d"] = df["returns"].rolling(30, min_periods=14).std()
    df["rolling_max"] = df["price"].rolling(730, min_periods=180).max()
    df["drawdown"] = (df["price"] - df["rolling_max"]) / df["rolling_max"].replace(0, np.nan)

    df["mvrv_z"] = rolling_z(df["mvrv_proxy"], window=zw, min_periods=zmin)
    df["nupl_z"] = rolling_z(df["nupl_proxy"], window=zw, min_periods=zmin)
    df["sopr_z"] = rolling_z(df["sopr_proxy"], window=zw, min_periods=zmin)
    df["volatility_z"] = rolling_z(df["volatility_30d"], window=zw, min_periods=zmin)
    df["drawdown_z"] = rolling_z(df["drawdown"], window=zw, min_periods=zmin)

    # Глубокая просадка → вклад в сторону накопления (см. −drawdown_z в плане)
    df["composite_onchain"] = (
        cg.w_mvrv * df["mvrv_z"]
        + cg.w_nupl * df["nupl_z"]
        + cg.w_sopr * df["sopr_z"]
        + cg.w_drawdown * (-df["drawdown_z"])
        + cg.w_volatility * df["volatility_z"]
    )
    return df


def _row_to_public_dict(df: pd.DataFrame, *, provenance: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Последняя строка → поля для API/UI."""
    prov = provenance or {}
    mvrv_z = _last_finite(df["mvrv_z"])
    nupl_raw = _last_finite(df["nupl_proxy"])
    sopr_val = _last_finite(df["sopr_simple"])
    if sopr_val is None:
        sopr_val = _last_finite(df["sopr_proxy"])

    nupl_adj: Optional[float] = nupl_raw
    if nupl_raw is not None:
        nupl_adj = float(max(-0.5, min(1.5, nupl_raw)))

    ts = datetime.now(timezone.utc).isoformat()
    composite = _last_finite(df["composite_onchain"])

    base: Dict[str, Any] = {
        "mvrv_z_score": mvrv_z,
        "nupl": nupl_adj,
        "sopr": sopr_val,
        "source": prov.get("source") or "market_history",
        "method": prov.get("method") or "build_market_history_proxy",
        "confidence": round(PROXY_CONFIDENCE, 2),
        "parser_version": prov.get("parser_version") or "market_history_v1",
        "timestamp": ts,
        "source_score": round(PROXY_SOURCE_SCORE, 2),
        "cg_nupl_z": _last_finite(df["nupl_z"]),
        "cg_sopr_z": _last_finite(df["sopr_z"]),
        "cg_mvrv_z": mvrv_z,
        "cg_volatility_30d": _last_finite(df["volatility_30d"]),
        "cg_drawdown": _last_finite(df["drawdown"]),
        "cg_volatility_z": _last_finite(df["volatility_z"]),
        "cg_drawdown_z": _last_finite(df["drawdown_z"]),
        "cg_composite_onchain": composite,
    }
    return base


def get_coingecko_810_dataframe() -> Optional[pd.DataFrame]:
    """
    Полный ряд §8.10 (все прокси и z-колонки) для бэктеста и калибровки — upgrade_plan S2 / plan.md §8.10.

    Данные: :func:`build_market_history` (plan01); кэш бандла (:func:`get_coingecko_810_bundle`) не заполняется.
    """
    if not USE_COINGECKO_ONCHAIN:
        logger.warning("Onchain proxy §8.10 выключен (USE_COINGECKO_ONCHAIN=false)")
        return None
    df, _ = _load_proxy_input_dataframe_with_meta()
    if df is None or df.empty:
        return None
    return _enrich_810(df)


def get_coingecko_810_bundle(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Полный бандл §8.10 (с кэшем): ряд из build_market_history → те же формулы, ключи cg_* без изменений.
    """
    global _bundle_time, _bundle_payload, _bundle_df

    if not USE_COINGECKO_ONCHAIN:
        logger.debug("Onchain proxy §8.10 выключен (USE_COINGECKO_ONCHAIN=false)")
        return None

    now = datetime.now(timezone.utc)
    if (
        not force_refresh
        and _bundle_payload is not None
        and _bundle_time is not None
        and now - _bundle_time < _BUNDLE_TTL
    ):
        return dict(_bundle_payload)

    df, prov = _load_proxy_input_dataframe_with_meta()
    if df is None or df.empty:
        return None

    df = _enrich_810(df)
    public = _row_to_public_dict(df, provenance=prov)

    if (
        public.get("mvrv_z_score") is None
        and public.get("nupl") is None
        and public.get("sopr") is None
    ):
        return None

    _bundle_time = now
    _bundle_payload = dict(public)
    _bundle_df = df
    return dict(public)


def get_coingecko_810_chart_frame(
    max_points: int = 2500,
    smooth_window: int = 7,
) -> Optional[pd.DataFrame]:
    """
    Цена и proxy composite §8.10 для UI (upgrade_plan P2 / plan.md §8.10).
    Использует тот же кэш, что :func:`get_coingecko_810_bundle` — без повторного build_market_history до истечения TTL.
    """
    get_coingecko_810_bundle()
    if _bundle_df is None or _bundle_df.empty:
        return None
    sub = _bundle_df.tail(int(max(50, max_points))).copy()
    sub = sub.dropna(subset=["composite_onchain"])
    if sub.empty:
        return None
    w = max(1, int(smooth_window))
    sub["composite_smooth"] = sub["composite_onchain"].rolling(w, min_periods=1).mean()
    return sub[["price", "composite_onchain", "composite_smooth"]]


def get_coingecko_onchain_proxy() -> Optional[Dict[str, Any]]:
    """Только поля для get_btc_onchain() fallback (обратная совместимость)."""
    bundle = get_coingecko_810_bundle()
    if not bundle:
        return None
    keys = (
        "mvrv_z_score",
        "nupl",
        "sopr",
        "source",
        "method",
        "confidence",
        "parser_version",
        "timestamp",
        "source_score",
    )
    return {k: bundle[k] for k in keys if k in bundle}


_CG_LEGACY_ALIASES = {
    "W_COMP_MVRV": "w_mvrv",
    "W_COMP_NUPL": "w_nupl",
    "W_COMP_SOPR": "w_sopr",
    "W_COMP_DD": "w_drawdown",
    "W_COMP_VOL": "w_volatility",
}


def __getattr__(name: str):
    """Совместимость: веса и окна из scoring.yaml (переопределение через .env см. loader)."""
    cg_attr = _CG_LEGACY_ALIASES.get(name)
    if cg_attr is not None:
        return getattr(get_scoring_config().coingecko_composite, cg_attr)
    if name == "_Z_WINDOW":
        return get_scoring_config().coingecko_composite.z_window
    if name == "_Z_MIN_PERIODS":
        return get_scoring_config().coingecko_composite.z_min_periods
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
