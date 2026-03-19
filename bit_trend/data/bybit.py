"""
Интеграция с Bybit API — Funding Rate, Open Interest (plan 8.3).
Используется вместе с Binance для агрегации (среднее по двум биржам).
"""

import logging
import requests
import time
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

BYBIT_API = "https://api.bybit.com/v5/market"


def _get_bybit_funding_rate() -> Optional[Tuple[float, float]]:
    """
    Получить Funding Rate с Bybit.
    Returns (funding_rate, funding_rate_8h_avg) или None.
    """
    try:
        r = requests.get(
            f"{BYBIT_API}/funding/history",
            params={"category": "linear", "symbol": "BTCUSDT", "limit": 3},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") != 0:
            logger.warning(f"Bybit funding: retCode={data.get('retCode')}")
            return None
        lst = data.get("result", {}).get("list", [])
        if not lst:
            return None
        rates = [float(item["fundingRate"]) for item in lst]
        funding_rate = rates[0] if rates else 0.0
        funding_rate_8h_avg = sum(rates) / len(rates) if rates else 0.0
        return (funding_rate, funding_rate_8h_avg)
    except Exception as e:
        logger.warning(f"Ошибка Bybit Funding Rate: {e}")
        return None


def _get_bybit_open_interest(btc_price: float) -> Optional[Tuple[float, float]]:
    """
    Получить Open Interest с Bybit (текущий и 7 дней назад).
    Bybit linear: openInterest в BTC.
    Returns (oi_now_usd, oi_7d_ago_usd) или None.
    """
    try:
        now_ms = int(time.time() * 1000)
        week_ms = 7 * 24 * 60 * 60 * 1000

        r = requests.get(
            f"{BYBIT_API}/open-interest",
            params={
                "category": "linear",
                "symbol": "BTCUSDT",
                "intervalTime": "1h",
                "startTime": now_ms - week_ms - 3600_000,
                "endTime": now_ms,
                "limit": 200,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("retCode") != 0:
            logger.warning(f"Bybit OI: retCode={data.get('retCode')}")
            return None
        lst = data.get("result", {}).get("list", [])
        if not lst:
            return None
        lst_sorted = sorted(lst, key=lambda x: int(x["timestamp"]))
        oi_first_btc = float(lst_sorted[0]["openInterest"])
        oi_last_btc = float(lst_sorted[-1]["openInterest"])
        oi_7d_ago_usd = oi_first_btc * btc_price
        oi_now_usd = oi_last_btc * btc_price
        return (oi_now_usd, oi_7d_ago_usd)
    except Exception as e:
        logger.warning(f"Ошибка Bybit Open Interest: {e}")
        return None


def get_bybit_derivatives(btc_price: float) -> Optional[Dict]:
    """
    Получить данные по деривативам BTC с Bybit.

    Returns:
        {
            "funding_rate": float,
            "funding_rate_8h_avg": float,
            "open_interest_usd": float,
            "open_interest_7d_ago_usd": float,
            "open_interest_7d_change_pct": float,
        } или None при ошибке
    """
    funding = _get_bybit_funding_rate()
    oi = _get_bybit_open_interest(btc_price)
    if funding is None and oi is None:
        return None
    funding_rate = funding[0] if funding else 0.0
    funding_rate_8h_avg = funding[1] if funding else 0.0
    if oi:
        oi_now_usd, oi_7d_ago_usd = oi
        oi_change = (
            (oi_now_usd - oi_7d_ago_usd) / oi_7d_ago_usd * 100
            if oi_7d_ago_usd else 0
        )
    else:
        oi_now_usd = 0.0
        oi_7d_ago_usd = 0.0
        oi_change = 0.0
    return {
        "funding_rate": funding_rate,
        "funding_rate_8h_avg": funding_rate_8h_avg,
        "open_interest_usd": oi_now_usd,
        "open_interest_7d_ago_usd": oi_7d_ago_usd,
        "open_interest_7d_change_pct": oi_change,
    }
