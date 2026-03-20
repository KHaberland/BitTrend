"""
CoinGecko — legacy: полный market_chart для истории; simple/price для текущего снимка (plan01 §8).
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

import pandas as pd

from .coingecko_onchain import _dataframe_from_payload, _fetch_market_chart_payload
from .http_client import http_get
from .market_source import MarketDataSource, normalize_history_df

SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"


def _coingecko_coin_id(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in ("BTC", "XBT"):
        return "bitcoin"
    return symbol.strip().lower()


class CoinGeckoMarketDataSource(MarketDataSource):
    def get_current(self, symbol: str) -> Dict[str, Any]:
        cid = _coingecko_coin_id(symbol)
        headers = {"User-Agent": "BitTrend/1.0 (market)"}
        demo = os.environ.get("COINGECKO_DEMO_API_KEY", "").strip()
        pro = os.environ.get("COINGECKO_PRO_API_KEY", "").strip()
        if pro:
            headers["x-cg-pro-api-key"] = pro
        elif demo:
            headers["x-cg-demo-api-key"] = demo
        r = http_get(
            SIMPLE_PRICE_URL,
            params={
                "ids": cid,
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        block = body.get(cid) if isinstance(body, dict) else None
        if not isinstance(block, dict):
            raise ValueError("CoinGecko: нет блока по id")
        price = float(block.get("usd", 0) or 0)
        cap = block.get("usd_market_cap")
        vol = block.get("usd_24h_vol")
        return {
            "symbol": symbol.strip().upper(),
            "price": price,
            "market_cap": float(cap) if cap is not None else None,
            "volume": float(vol) if vol is not None else None,
            "timestamp": int(time.time()),
            "source": "coingecko",
        }

    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        if _coingecko_coin_id(symbol) != "bitcoin":
            return normalize_history_df(pd.DataFrame())
        payload = _fetch_market_chart_payload()
        if not payload:
            return normalize_history_df(pd.DataFrame())
        df = _dataframe_from_payload(payload)
        if df is None or df.empty:
            return normalize_history_df(pd.DataFrame())
        out = df.reset_index().rename(columns={"ts": "timestamp"})
        out = out[["timestamp", "price", "market_cap", "volume"]]
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(max(1, days)))
        out = out[out["timestamp"] >= cutoff]
        return normalize_history_df(out)


# Имя из plan01 §8 (таблица реализаций); основной класс — CoinGeckoMarketDataSource.
CoinGeckoDataSource = CoinGeckoMarketDataSource
