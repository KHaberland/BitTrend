"""
Proxy MVRV / NUPL / SOPR по plan.md §8.10 — CoinGecko (price, market_cap, volume).
Третий fallback после Glassnode и LookIntoBitcoin; без Glassnode API.
"""

import logging
import os
from datetime import datetime, timezone
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


def _last_finite(series: pd.Series) -> Optional[float]:
    s = series.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def _rolling_z(series: pd.Series, window: int = 365, min_periods: int = 30) -> pd.Series:
    m = series.rolling(window, min_periods=min_periods).mean()
    s = series.rolling(window, min_periods=min_periods).std()
    out = (series - m) / s.replace(0, np.nan)
    return out


def get_coingecko_onchain_proxy() -> Optional[Dict[str, Any]]:
    """
    Вернуть последние proxy-метрики и provenance (§8.10).
    mvrv_z_score — rolling Z по mvrv_proxy (масштаб согласован со знаком «низко = лучше для BTC»).
    """
    if not USE_COINGECKO_ONCHAIN:
        logger.debug("CoinGecko onchain proxy выключен (USE_COINGECKO_ONCHAIN=false)")
        return None

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
        payload = r.json()
    except Exception as e:
        logger.warning("CoinGecko onchain proxy: ошибка запроса: %s", e)
        return None

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
    df = df.dropna(subset=["price", "market_cap"])

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

    df["mvrv_z"] = _rolling_z(df["mvrv_proxy"], window=365, min_periods=30)

    mvrv_z = _last_finite(df["mvrv_z"])
    nupl_raw = _last_finite(df["nupl_proxy"])
    sopr_val = _last_finite(df["sopr_simple"])
    if sopr_val is None:
        sopr_val = _last_finite(df["sopr_proxy"])

    nupl_adj = nupl_raw
    if nupl_raw is not None:
        nupl_adj = float(max(-0.5, min(1.5, nupl_raw)))

    ts = datetime.now(timezone.utc).isoformat()
    if mvrv_z is None and nupl_adj is None and sopr_val is None:
        return None

    return {
        "mvrv_z_score": mvrv_z,
        "nupl": nupl_adj,
        "sopr": sopr_val,
        "source": "coingecko",
        "method": "market_chart_proxy",
        "confidence": round(PROXY_CONFIDENCE, 2),
        "parser_version": "coingecko_v1",
        "timestamp": ts,
        "source_score": round(PROXY_SOURCE_SCORE, 2),
    }
