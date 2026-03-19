"""Модули сбора рыночных данных."""

from .fetcher import DataFetcher
from .fear_greed import get_fear_greed_index
from .binance import get_btc_price, get_btc_derivatives
from .macro import get_macro_data
from .onchain import get_btc_onchain
from .etf import get_etf_flows
from .types import OnchainMetrics
from .lookintobitcoin import merge_sources, merge_weighted, stabilize, is_fresh, is_same, detect_drift, get_last_known_good
from .storage import save_history, get_last_history, get_history
from .normalize import normalize_mvrv, normalize_nupl, normalize_sopr, normalize_all

__all__ = [
    "DataFetcher",
    "get_fear_greed_index",
    "get_btc_price",
    "get_btc_derivatives",
    "get_macro_data",
    "get_btc_onchain",
    "get_etf_flows",
    "OnchainMetrics",
    "merge_sources",
    "merge_weighted",
    "stabilize",
    "is_fresh",
    "is_same",
    "detect_drift",
    "get_last_known_good",
    "save_history",
    "get_last_history",
    "get_history",
    "normalize_mvrv",
    "normalize_nupl",
    "normalize_sopr",
    "normalize_all",
]
