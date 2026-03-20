"""
Proxy MVRV / NUPL / SOPR по plan.md §8.10 — CoinGecko (price, market_cap, volume).
Третий fallback после Glassnode и LookIntoBitcoin; volatility, drawdown, rolling z, composite_onchain (S1).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
REQUEST_TIMEOUT = 25

USE_COINGECKO_ONCHAIN = os.environ.get("USE_COINGECKO_ONCHAIN", "true").lower() in ("true", "1", "yes")

# Прокси-модель — ниже, чем у LTB/Glassnode; conservative meta для UI
PROXY_CONFIDENCE = float(os.environ.get("COINGECKO_ONCHAIN_CONFIDENCE", "0.55"))
PROXY_SOURCE_SCORE = float(os.environ.get("COINGECKO_ONCHAIN_SOURCE_SCORE", "0.52"))

# §8.10 composite: веса z-метрик (сумма w_mvrv..w_dd ≈ 1; w_vol обычно отрицательный)
W_COMP_MVRV = float(os.environ.get("COMPOSITE_810_W_MVRV", "0.30"))
W_COMP_NUPL = float(os.environ.get("COMPOSITE_810_W_NUPL", "0.25"))
W_COMP_SOPR = float(os.environ.get("COMPOSITE_810_W_SOPR", "0.20"))
W_COMP_DD = float(os.environ.get("COMPOSITE_810_W_DRAWDOWN", "0.25"))
W_COMP_VOL = float(os.environ.get("COMPOSITE_810_W_VOLATILITY", "-0.10"))

_Z_WINDOW = int(os.environ.get("COMPOSITE_810_Z_WINDOW", "365"))
_Z_MIN_PERIODS = int(os.environ.get("COMPOSITE_810_Z_MIN_PERIODS", "30"))

_bundle_time: Optional[datetime] = None
_bundle_payload: Optional[Dict[str, Any]] = None
_BUNDLE_TTL = timedelta(seconds=int(os.environ.get("COINGECKO_BUNDLE_CACHE_SEC", "120")))


def clear_coingecko_bundle_cache() -> None:
    """Сброс кэша бандла (например при clear_cache у DataFetcher)."""
    global _bundle_time, _bundle_payload
    _bundle_time = None
    _bundle_payload = None


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
    try:
        r = requests.get(
            COINGECKO_CHART_URL,
            params={"vs_currency": "usd", "days": "max"},
            headers={"User-Agent": "BitTrend/1.0 (onchain proxy)"},
            timeout=REQUEST_TIMEOUT,
        )
        if not r.ok:
            logger.warning("CoinGecko market_chart: HTTP %s", r.status_code)
            return None
        return r.json()
    except Exception as e:
        logger.warning("CoinGecko onchain proxy: ошибка запроса: %s", e)
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


def _enrich_810(df: pd.DataFrame) -> pd.DataFrame:
    """Все прокси и z-ряды по §8.10 (один проход по df)."""
    zw, zmin = _Z_WINDOW, _Z_MIN_PERIODS

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
        W_COMP_MVRV * df["mvrv_z"]
        + W_COMP_NUPL * df["nupl_z"]
        + W_COMP_SOPR * df["sopr_z"]
        + W_COMP_DD * (-df["drawdown_z"])
        + W_COMP_VOL * df["volatility_z"]
    )
    return df


def _row_to_public_dict(df: pd.DataFrame) -> Dict[str, Any]:
    """Последняя строка → поля для API/UI."""
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
        "source": "coingecko",
        "method": "market_chart_proxy",
        "confidence": round(PROXY_CONFIDENCE, 2),
        "parser_version": "coingecko_v2",
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


def get_coingecko_810_bundle(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Полный бандл §8.10 за один HTTP-запрос (с кэшем).
    Ключи cg_* — по рядам CoinGecko; mvrv_z_score/nupl/sopr — для fallback как раньше.
    """
    global _bundle_time, _bundle_payload

    if not USE_COINGECKO_ONCHAIN:
        logger.debug("CoinGecko onchain proxy выключен (USE_COINGECKO_ONCHAIN=false)")
        return None

    now = datetime.now(timezone.utc)
    if (
        not force_refresh
        and _bundle_payload is not None
        and _bundle_time is not None
        and now - _bundle_time < _BUNDLE_TTL
    ):
        return dict(_bundle_payload)

    payload = _fetch_market_chart_payload()
    if not payload:
        return None

    df = _dataframe_from_payload(payload)
    if df is None or df.empty:
        return None

    df = _enrich_810(df)
    public = _row_to_public_dict(df)

    if (
        public.get("mvrv_z_score") is None
        and public.get("nupl") is None
        and public.get("sopr") is None
    ):
        return None

    _bundle_time = now
    _bundle_payload = dict(public)
    return dict(public)


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
