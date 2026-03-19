"""
DataFetcher — единая точка входа для сбора всех рыночных данных.
Кэширование с TTL 5–15 минут, fallback при недоступности API.
Параллельная загрузка источников для ускорения.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from .binance import get_btc_price, get_btc_derivatives, get_ma200
from .fear_greed import get_fear_greed_index
from .macro import get_macro_data
from .onchain import get_btc_onchain
from .etf import get_etf_flows

logger = logging.getLogger(__name__)

# Общий кэш на уровне модуля — сохраняется между rerun Streamlit
_shared_cache: Optional[Dict[str, Any]] = None
_shared_cache_time: Optional[datetime] = None


class DataFetcher:
    """Сбор и кэширование всех данных для BitTrend."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = timedelta(seconds=ttl_seconds)

    def _is_cache_valid(self) -> bool:
        global _shared_cache, _shared_cache_time
        if _shared_cache is None or _shared_cache_time is None:
            return False
        return datetime.now() - _shared_cache_time < self.ttl

    def fetch_all(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Собрать все данные из всех источников (параллельно).
        При use_cache=True возвращает кэш, если TTL не истёк.

        Returns:
            Словарь с полным набором данных для Score Calculator.
        """
        global _shared_cache, _shared_cache_time
        if use_cache and self._is_cache_valid():
            return _shared_cache

        # Параллельная загрузка — ускорение в 3–5 раз
        btc_price = 0.0
        ma200 = None
        derivatives: Dict = {}
        fear_greed: Dict = {}
        macro: Dict = {}
        onchain: Dict = {}
        etf: Dict = {}

        def _fetch_price():
            return get_btc_price()

        def _fetch_ma200():
            return get_ma200()

        def _fetch_derivatives():
            return get_btc_derivatives() or {}

        def _fetch_fear_greed():
            return get_fear_greed_index() or {}

        def _fetch_macro():
            return get_macro_data() or {}

        def _fetch_onchain():
            return get_btc_onchain() or {}

        def _fetch_etf():
            return get_etf_flows() or {}

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(_fetch_price): "price",
                executor.submit(_fetch_ma200): "ma200",
                executor.submit(_fetch_derivatives): "derivatives",
                executor.submit(_fetch_fear_greed): "fear_greed",
                executor.submit(_fetch_macro): "macro",
                executor.submit(_fetch_onchain): "onchain",
                executor.submit(_fetch_etf): "etf",
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    val = future.result()
                    if key == "price":
                        btc_price = val or 0.0
                    elif key == "ma200":
                        ma200 = val
                    elif key == "derivatives":
                        derivatives = val
                    elif key == "fear_greed":
                        fear_greed = val
                    elif key == "macro":
                        macro = val
                    elif key == "onchain":
                        onchain = val
                    elif key == "etf":
                        etf = val
                except Exception as e:
                    logger.warning(f"Ошибка загрузки {key}: {e}")

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

        _shared_cache = result
        _shared_cache_time = datetime.now()
        return result

    def clear_cache(self) -> None:
        """Очистить кэш."""
        global _shared_cache, _shared_cache_time
        _shared_cache = None
        _shared_cache_time = None