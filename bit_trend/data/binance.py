"""
Интеграция с Binance API — цена BTC, MA200, Funding Rate, Open Interest.
"""

import logging
import requests
import pandas as pd
from typing import Optional, Dict, Tuple, List

logger = logging.getLogger(__name__)

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
BINANCE_DATA = "https://fapi.binance.com/futures/data"
# Spot API для klines (plan 8.2) — надёжный источник дневных цен
BINANCE_SPOT = "https://api.binance.com/api/v3"


def get_btc_price() -> float:
    """Получить текущую цену BTC с Binance."""
    try:
        r = requests.get(
            f"{BINANCE_FAPI}/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=5
        )
        if r.ok:
            return float(r.json().get("price", 97000.0))
    except Exception:
        pass
    return 97000.0


def _get_open_interest_history() -> Optional[Tuple[float, float]]:
    """
    Open Interest: текущий и 7 дней назад (для тренда).
    Returns (oi_now_usd, oi_7d_ago_usd) или None.
    """
    try:
        btc_price = get_btc_price()
        r = requests.get(
            f"{BINANCE_FAPI}/openInterest",
            params={"symbol": "BTCUSDT"},
            timeout=10
        )
        r.raise_for_status()
        oi_now_contracts = float(r.json().get("openInterest", 0))
        oi_now_usd = oi_now_contracts * 0.1 * btc_price

        r_hist = requests.get(
            f"{BINANCE_DATA}/openInterestHist",
            params={"symbol": "BTCUSDT", "period": "1h", "limit": 168},
            timeout=10
        )
        r_hist.raise_for_status()
        hist = r_hist.json()
        if hist:
            last = hist[-1]
            if "sumOpenInterestValue" in last:
                oi_7d_ago_usd = float(last["sumOpenInterestValue"])
            else:
                oi_7d_ago_usd = float(last.get("sumOpenInterest", 0)) * 0.1 * btc_price
        else:
            oi_7d_ago_usd = oi_now_usd
        return (oi_now_usd, oi_7d_ago_usd)
    except Exception as e:
        logger.warning(f"Ошибка Open Interest history: {e}")
        return None


def get_btc_derivatives() -> Optional[Dict]:
    """
    Получить данные по деривативам BTC: Funding Rate, Open Interest.

    Returns:
        {
            "funding_rate": float,
            "funding_rate_8h_avg": float,
            "open_interest_usd": float,
            "open_interest_7d_ago_usd": float,
            "open_interest_7d_change_pct": float,
            ...
        } или None при ошибке
    """
    try:
        fr_resp = requests.get(
            f"{BINANCE_FAPI}/fundingRate",
            params={"symbol": "BTCUSDT", "limit": 3},
            timeout=10
        )
        fr_resp.raise_for_status()
        funding_data = fr_resp.json()
        rates = [float(r["fundingRate"]) for r in funding_data] if funding_data else []
        funding_rate = rates[0] if rates else 0.0
        funding_rate_8h_avg = sum(rates) / len(rates) if rates else 0.0

        btc_price = get_btc_price()
        oi_hist = _get_open_interest_history()
        if oi_hist:
            oi_now_usd, oi_7d_ago_usd = oi_hist
            oi_change = (
                (oi_now_usd - oi_7d_ago_usd) / oi_7d_ago_usd * 100
                if oi_7d_ago_usd else 0
            )
        else:
            oi_resp = requests.get(
                f"{BINANCE_FAPI}/openInterest",
                params={"symbol": "BTCUSDT"},
                timeout=10
            )
            oi_resp.raise_for_status()
            oi = float(oi_resp.json().get("openInterest", 0))
            oi_now_usd = oi * 0.1 * btc_price
            oi_7d_ago_usd = oi_now_usd
            oi_change = 0.0

        return {
            "funding_rate": funding_rate,
            "funding_rate_8h_avg": funding_rate_8h_avg,
            "open_interest_usd": oi_now_usd,
            "open_interest_7d_ago_usd": oi_7d_ago_usd,
            "open_interest_7d_change_pct": oi_change,
        }
    except Exception as e:
        logger.warning(f"Ошибка получения деривативов BTC: {e}")
        return None


def get_btc_klines(limit: int = 200) -> Optional[List[float]]:
    """
    Получить историю цен BTC для расчёта MA200.
    Источник: Binance Spot API (plan 8.2).
    Returns: список цен закрытия (от старых к новым) или None.
    """
    try:
        r = requests.get(
            f"{BINANCE_SPOT}/klines",
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": limit},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return [float(candle[4]) for candle in data]
    except Exception as e:
        logger.warning(f"Ошибка получения klines BTC: {e}")
        return None


def get_ma200() -> Optional[float]:
    """
    Вычислить MA200 по данным Binance (plan 8.2).
    df['ma200'] = df['close'].rolling(200).mean()
    """
    prices = get_btc_klines(200)
    if not prices or len(prices) < 200:
        return None
    df = pd.DataFrame({"close": prices})
    df["ma200"] = df["close"].rolling(200).mean()
    return float(df["ma200"].iloc[-1])