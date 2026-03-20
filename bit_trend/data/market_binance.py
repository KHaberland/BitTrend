"""
Binance Spot — fallback цены и объёма (24h quote volume); market cap отсутствует (plan01 §8).
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pandas as pd

from .binance import get_btc_klines, get_btc_price
from .http_client import http_get
from .market_source import MarketDataSource, normalize_history_df

BINANCE_SPOT = "https://api.binance.com/api/v3"


class BinanceMarketDataSource(MarketDataSource):
    def get_current(self, symbol: str) -> Dict[str, Any]:
        sym_in = symbol.strip().upper()
        if sym_in.endswith("USDT"):
            pair = sym_in
            base = sym_in[:-4]
        else:
            base = sym_in
            pair = f"{base}USDT"
        r = http_get(f"{BINANCE_SPOT}/ticker/24hr", params={"symbol": pair}, timeout=10)
        r.raise_for_status()
        j = r.json()
        price = float(j.get("lastPrice", 0) or 0)
        vol = float(j.get("quoteVolume", 0) or 0)
        return {
            "symbol": base,
            "price": price,
            "market_cap": None,
            "volume": vol,
            "timestamp": int(time.time()),
            "source": "binance",
        }

    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        sym = symbol.strip().upper()
        if sym not in ("BTC", ""):
            return normalize_history_df(pd.DataFrame())
        limit = max(2, min(int(days), 1000))
        prices = get_btc_klines(limit)
        if not prices:
            p = get_btc_price()
            now = pd.Timestamp.now(tz="UTC")
            return normalize_history_df(
                pd.DataFrame([{"timestamp": now, "price": p, "market_cap": None, "volume": None}])
            )
        now = pd.Timestamp.now(tz="UTC")
        idx = pd.date_range(end=now, periods=len(prices), freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": idx,
                "price": prices,
                "market_cap": None,
                "volume": None,
            }
        )
        return normalize_history_df(df)


# Имя из plan01 §8 (таблица реализаций); основной класс — BinanceMarketDataSource.
BinanceDataSource = BinanceMarketDataSource
