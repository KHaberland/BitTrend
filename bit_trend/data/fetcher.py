"""
DataFetcher — единая точка входа для сбора всех рыночных данных.
Кэширование с TTL 5–15 минут, fallback при недоступности API.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from .binance import get_btc_price, get_btc_derivatives, get_ma200
from .fear_greed import get_fear_greed_index
from .macro import get_macro_data
from .onchain import get_btc_onchain
from .etf import get_etf_flows

logger = logging.getLogger(__name__)


class DataFetcher:
    """Сбор и кэширование всех данных для BitTrend."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: Optional[datetime] = None

    def _is_cache_valid(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return False
        return datetime.now() - self._cache_time < self.ttl

    def fetch_all(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Собрать все данные из всех источников.
        При use_cache=True возвращает кэш, если TTL не истёк.

        Returns:
            Словарь с полным набором данных для Score Calculator.
        """
        if use_cache and self._is_cache_valid():
            return self._cache

        btc_price = get_btc_price()
        ma200 = get_ma200()

        derivatives = get_btc_derivatives() or {}
        fear_greed = get_fear_greed_index() or {}
        macro = get_macro_data() or {}
        onchain = get_btc_onchain() or {}
        etf = get_etf_flows() or {}

        result: Dict[str, Any] = {
            "btc_price": btc_price,
            "ma200": ma200,
            "funding_rate": derivatives.get("funding_rate"),
            "funding_rate_8h_avg": derivatives.get("funding_rate_8h_avg"),
            "open_interest_usd": derivatives.get("open_interest_usd"),
            "open_interest_7d_change_pct": derivatives.get("open_interest_7d_change_pct"),
            "fear_greed_value": fear_greed.get("value"),
            "fear_greed_classification": fear_greed.get("classification"),
            "macro_signal": macro.get("macro_signal", 0),
            "fed_funds_rate": macro.get("fed_funds_rate"),
            "dxy": macro.get("dxy"),
            "dxy_30d_change_pct": macro.get("dxy_30d_change_pct"),
            "treasury_10y": macro.get("treasury_10y"),
            "mvrv_z_score": onchain.get("mvrv_z_score"),
            "nupl": onchain.get("nupl"),
            "sopr": onchain.get("sopr"),
            "sopr_signal": onchain.get("sopr_signal", 0),
            "exchange_flow_signal": onchain.get("exchange_flow_signal", 0),
            "etf_flow_7d_usd": etf.get("flow_7d_usd"),
            "etf_flow_1d_usd": etf.get("flow_1d_usd"),
            "etf_interpretation": etf.get("interpretation"),
        }

        self._cache = result
        self._cache_time = datetime.now()
        return result

    def clear_cache(self) -> None:
        """Очистить кэш."""
        self._cache = None
        self._cache_time = None