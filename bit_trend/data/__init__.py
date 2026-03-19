"""Модули сбора рыночных данных."""

from .fetcher import DataFetcher
from .fear_greed import get_fear_greed_index
from .binance import get_btc_price, get_btc_derivatives
from .macro import get_macro_data
from .onchain import get_btc_onchain
from .etf import get_etf_flows

__all__ = [
    "DataFetcher",
    "get_fear_greed_index",
    "get_btc_price",
    "get_btc_derivatives",
    "get_macro_data",
    "get_btc_onchain",
    "get_etf_flows",
]
