"""
DataFetcher — единая точка входа для сбора всех рыночных данных.
Кэш: быстрый блок (цена/MA/деривативы/F&G) и медленный (макро/ончейн/ETF), §8.7 upgrade_plan D3.
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
from .coingecko_onchain import get_coingecko_810_bundle, clear_coingecko_bundle_cache

logger = logging.getLogger(__name__)

# Поля plan.md §8.10 (S1) — только из ряда CoinGecko, не перезаписывают MVRV/NUPL/SOPR из LTB/Glassnode
_CG810_RESULT_KEYS = (
    "cg_composite_onchain",
    "cg_mvrv_z",
    "cg_nupl_z",
    "cg_sopr_z",
    "cg_volatility_30d",
    "cg_drawdown",
    "cg_volatility_z",
    "cg_drawdown_z",
    "cg_proxy_updated_at",
)


def _cg810_slice() -> Dict[str, Any]:
    """Подмножество §8.10 для результата fetch_all (один вызов CoinGecko с кэшем)."""
    bundle = get_coingecko_810_bundle()
    if not bundle:
        return {k: None for k in _CG810_RESULT_KEYS}
    out: Dict[str, Any] = {k: bundle.get(k) for k in _CG810_RESULT_KEYS if k != "cg_proxy_updated_at"}
    out["cg_proxy_updated_at"] = bundle.get("timestamp")
    return out

_shared_fast_cache: Optional[Dict[str, Any]] = None
_shared_fast_time: Optional[datetime] = None
_shared_slow_cache: Optional[Dict[str, Any]] = None
_shared_slow_time: Optional[datetime] = None


class DataFetcher:
    """Сбор и кэширование всех данных для BitTrend."""

    def __init__(self, ttl_seconds: int = 300):
        """
        ttl_seconds — TTL быстрого блока (как раньше). Медленный — CACHE_TTL_SLOW или 3600 с.
        """
        fast = int(os.getenv("CACHE_TTL_FAST", str(ttl_seconds)))
        slow = int(os.getenv("CACHE_TTL_SLOW", "3600"))
        self.ttl_fast = timedelta(seconds=fast)
        self.ttl_slow = timedelta(seconds=slow)

    def _fast_cache_valid(self) -> bool:
        global _shared_fast_cache, _shared_fast_time
        if _shared_fast_cache is None or _shared_fast_time is None:
            return False
        return datetime.now() - _shared_fast_time < self.ttl_fast

    def _slow_cache_valid(self) -> bool:
        global _shared_slow_cache, _shared_slow_time
        if _shared_slow_cache is None or _shared_slow_time is None:
            return False
        return datetime.now() - _shared_slow_time < self.ttl_slow

    def fetch_all(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Собрать все данные из всех источников.
        Быстрые источники обновляются чаще; макро/ончейн/ETF — по отдельному TTL.
        """
        global _shared_fast_cache, _shared_fast_time, _shared_slow_cache, _shared_slow_time

        need_fast = not use_cache or not self._fast_cache_valid()
        need_slow = not use_cache or not self._slow_cache_valid()

        if use_cache and not need_fast and not need_slow:
            return {**_shared_fast_cache, **_shared_slow_cache}

        btc_price = 0.0
        ma200 = None
        derivatives: Dict = {}
        fear_greed: Dict = {}
        macro: Dict = {}
        onchain: Dict = {}
        etf: Dict = {}

        if need_fast:
            with ThreadPoolExecutor(max_workers=4) as executor:
                f_price = executor.submit(get_btc_price)
                f_ma = executor.submit(get_ma200)
                f_deriv = executor.submit(lambda: get_btc_derivatives() or {})
                f_fg = executor.submit(lambda: get_fear_greed_index() or {})
                for fut, key in [
                    (f_price, "price"),
                    (f_ma, "ma200"),
                    (f_deriv, "deriv"),
                    (f_fg, "fg"),
                ]:
                    try:
                        val = fut.result()
                        if key == "price":
                            btc_price = val or 0.0
                        elif key == "ma200":
                            ma200 = val
                        elif key == "deriv":
                            derivatives = val
                        else:
                            fear_greed = val
                    except Exception as e:
                        logger.warning("Ошибка загрузки %s: %s", key, e)
            now_f = datetime.now()
            _shared_fast_cache = {
                "btc_price": btc_price,
                "ma200": ma200,
                "funding_rate": derivatives.get("funding_rate"),
                "funding_rate_8h_avg": derivatives.get("funding_rate_8h_avg"),
                "open_interest_usd": derivatives.get("open_interest_usd"),
                "open_interest_7d_change_pct": derivatives.get("open_interest_7d_change_pct"),
                "fear_greed_value": fear_greed.get("value"),
                "fear_greed_classification": fear_greed.get("classification"),
            }
            _shared_fast_time = now_f
        else:
            btc_price = _shared_fast_cache["btc_price"]
            ma200 = _shared_fast_cache["ma200"]
            derivatives = {
                "funding_rate": _shared_fast_cache.get("funding_rate"),
                "funding_rate_8h_avg": _shared_fast_cache.get("funding_rate_8h_avg"),
                "open_interest_usd": _shared_fast_cache.get("open_interest_usd"),
                "open_interest_7d_change_pct": _shared_fast_cache.get("open_interest_7d_change_pct"),
            }
            fear_greed = {
                "value": _shared_fast_cache.get("fear_greed_value"),
                "classification": _shared_fast_cache.get("fear_greed_classification"),
            }

        if need_slow:
            with ThreadPoolExecutor(max_workers=3) as executor:
                f_macro = executor.submit(lambda: get_macro_data() or {})
                f_on = executor.submit(lambda: get_btc_onchain() or {})
                f_etf = executor.submit(lambda: get_etf_flows() or {})
                for f, name in [(f_macro, "macro"), (f_on, "onchain"), (f_etf, "etf")]:
                    try:
                        val = f.result()
                        if name == "macro":
                            macro = val
                        elif name == "onchain":
                            onchain = val
                        else:
                            etf = val
                    except Exception as e:
                        logger.warning("Ошибка загрузки %s: %s", name, e)
            now_s = datetime.now()
            _shared_slow_cache = {
                "macro_signal": macro.get("macro_signal", 0),
                "fed_funds_rate": macro.get("fed_funds_rate"),
                "dxy": macro.get("dxy"),
                "dxy_30d_change_pct": macro.get("dxy_30d_change_pct"),
                "treasury_10y": macro.get("treasury_10y"),
                "cpi_index": macro.get("cpi_index"),
                "cpi_yoy_pct": macro.get("cpi_yoy_pct"),
                "sp500": macro.get("sp500"),
                "sp500_30d_change_pct": macro.get("sp500_30d_change_pct"),
                "macro_interpretation": macro.get("interpretation"),
                "mvrv_z_score": onchain.get("mvrv_z_score"),
                "nupl": onchain.get("nupl"),
                "sopr": onchain.get("sopr"),
                "sopr_signal": onchain.get("sopr_signal", 0),
                "exchange_flow_signal": onchain.get("exchange_flow_signal", 0),
                "onchain_source": onchain.get("onchain_source"),
                "onchain_confidence": onchain.get("onchain_confidence"),
                "onchain_source_score": onchain.get("onchain_source_score"),
                "onchain_method": onchain.get("onchain_method"),
                "etf_flow_7d_usd": etf.get("flow_7d_usd"),
                "etf_flow_1d_usd": etf.get("flow_1d_usd"),
                "etf_interpretation": etf.get("interpretation"),
                **_cg810_slice(),
            }
            _shared_slow_time = now_s
        else:
            macro = {
                "macro_signal": _shared_slow_cache.get("macro_signal", 0),
                "fed_funds_rate": _shared_slow_cache.get("fed_funds_rate"),
                "dxy": _shared_slow_cache.get("dxy"),
                "dxy_30d_change_pct": _shared_slow_cache.get("dxy_30d_change_pct"),
                "treasury_10y": _shared_slow_cache.get("treasury_10y"),
                "cpi_index": _shared_slow_cache.get("cpi_index"),
                "cpi_yoy_pct": _shared_slow_cache.get("cpi_yoy_pct"),
                "sp500": _shared_slow_cache.get("sp500"),
                "sp500_30d_change_pct": _shared_slow_cache.get("sp500_30d_change_pct"),
                "interpretation": _shared_slow_cache.get("macro_interpretation"),
            }
            onchain = {
                "mvrv_z_score": _shared_slow_cache.get("mvrv_z_score"),
                "nupl": _shared_slow_cache.get("nupl"),
                "sopr": _shared_slow_cache.get("sopr"),
                "sopr_signal": _shared_slow_cache.get("sopr_signal", 0),
                "exchange_flow_signal": _shared_slow_cache.get("exchange_flow_signal", 0),
                "onchain_source": _shared_slow_cache.get("onchain_source"),
                "onchain_confidence": _shared_slow_cache.get("onchain_confidence"),
                "onchain_source_score": _shared_slow_cache.get("onchain_source_score"),
                "onchain_method": _shared_slow_cache.get("onchain_method"),
            }
            etf = {
                "flow_7d_usd": _shared_slow_cache.get("etf_flow_7d_usd"),
                "flow_1d_usd": _shared_slow_cache.get("etf_flow_1d_usd"),
                "interpretation": _shared_slow_cache.get("etf_interpretation"),
            }

        cg810 = {k: _shared_slow_cache.get(k) for k in _CG810_RESULT_KEYS} if _shared_slow_cache else {k: None for k in _CG810_RESULT_KEYS}

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
            "cpi_index": macro.get("cpi_index"),
            "cpi_yoy_pct": macro.get("cpi_yoy_pct"),
            "sp500": macro.get("sp500"),
            "sp500_30d_change_pct": macro.get("sp500_30d_change_pct"),
            "mvrv_z_score": onchain.get("mvrv_z_score"),
            "nupl": onchain.get("nupl"),
            "sopr": onchain.get("sopr"),
            "sopr_signal": onchain.get("sopr_signal", 0),
            "exchange_flow_signal": onchain.get("exchange_flow_signal", 0),
            "onchain_source": onchain.get("onchain_source"),
            "onchain_confidence": onchain.get("onchain_confidence"),
            "onchain_source_score": onchain.get("onchain_source_score"),
            "onchain_method": onchain.get("onchain_method"),
            "etf_flow_7d_usd": etf.get("flow_7d_usd"),
            "etf_flow_1d_usd": etf.get("flow_1d_usd"),
            "etf_interpretation": etf.get("interpretation"),
            **cg810,
        }

        return result

    def clear_cache(self) -> None:
        """Очистить оба кэша."""
        global _shared_fast_cache, _shared_fast_time, _shared_slow_cache, _shared_slow_time
        _shared_fast_cache = None
        _shared_fast_time = None
        _shared_slow_cache = None
        _shared_slow_time = None
        clear_coingecko_bundle_cache()
