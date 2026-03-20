"""
Импорт дневного OHLCV CoinMarketCap в SQLite market_data (plan_change §5 вариант A).

Тонкая обёртка над cmc_market_import — имя модуля как в plan_change.md (пример:
``from bit_trend.data.coinmarketcap_history import sync_btc_from_cmc``).
"""

from __future__ import annotations

from .cmc_market_import import cmc_history_df_to_rows, sync_btc_from_cmc

__all__ = ["cmc_history_df_to_rows", "sync_btc_from_cmc"]
