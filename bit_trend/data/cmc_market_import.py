"""
Импорт дневного OHLCV CoinMarketCap в SQLite market_data (plan_change §3).
symbol=BTC, source=coinmarketcap; запись через storage.save_market_rows.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import pandas as pd

from .market_coinmarketcap import CoinMarketCapDataSource
from .storage import save_market_rows

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip() or str(default)
    try:
        return int(raw)
    except ValueError:
        return default


def cmc_history_df_to_rows(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        ts = r.get("timestamp")
        rows.append(
            {
                "timestamp": ts,
                "price": r.get("price"),
                "market_cap": r.get("market_cap"),
                "volume": r.get("volume"),
            }
        )
    return rows


def sync_btc_from_cmc(*, days_back: int | None = None) -> int:
    """
    Подтянуть get_history(BTC) с CMC и записать в market_data (INSERT OR REPLACE по timestamp).
    days_back: по умолчанию CMC_OHLCV_HISTORY_DAYS или ONCHAIN_PROXY_HISTORY_DAYS, иначе 730.

    Без CMC_API_KEY — ValueError (явный сигнал для сценария бэкфилла / планировщика).
    """
    d = days_back
    if d is None:
        d = _env_int("CMC_OHLCV_HISTORY_DAYS", 0)
        if d <= 0:
            d = _env_int("ONCHAIN_PROXY_HISTORY_DAYS", 730)
        if d <= 0:
            d = 730
    d = max(1, min(int(d), 3650))
    src = CoinMarketCapDataSource()
    if not src.api_key:
        raise ValueError("CMC_API_KEY не задан — укажите ключ Pro API для бэкфилла market_data")
    df = src.get_history("BTC", d)
    rows = cmc_history_df_to_rows(df)
    n = save_market_rows(rows, symbol="BTC", source="coinmarketcap")
    logger.info("sync_btc_from_cmc: записано %s строк (окно %s дн.)", n, d)
    return n
