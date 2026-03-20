"""
Он-чейн аналитика Bitcoin: MVRV Z-Score, NUPL, SOPR, Exchange flow.

Источники (по приоритету):
1. Glassnode API — при наличии GLASSNODE_API_KEY
2. LookIntoBitcoin — парсинг (бесплатно, план 8.1)
3. Blockchain.com — stats, active addresses
"""

import logging
import os
import time
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

BLOCKCHAIN_STATS = "https://api.blockchain.info/stats"
BLOCKCHAIN_CHARTS = "https://api.blockchain.info/charts"
GLASSNODE_URL = "https://api.glassnode.com/v1/metrics"


def _get_blockchain_stats() -> Optional[Dict]:
    """Blockchain.com stats — бесплатно, без ключа."""
    try:
        r = requests.get(BLOCKCHAIN_STATS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"Ошибка Blockchain.com stats: {e}")
        return None


def _get_blockchain_chart(chart_name: str, days: int = 30) -> Optional[list]:
    """Blockchain.com charts."""
    try:
        r = requests.get(
            f"{BLOCKCHAIN_CHARTS}/{chart_name}",
            params={"timespan": f"{days}days", "format": "json"},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        return data.get("values", [])
    except Exception as e:
        logger.warning(f"Ошибка Blockchain.com chart {chart_name}: {e}")
        return None


def _get_glassnode_metric(
    endpoint: str,
    asset: str = "BTC",
    interval: str = "24h",
    days: int = 30
) -> Optional[Any]:
    """Запрос метрики Glassnode. Требует GLASSNODE_API_KEY."""
    api_key = os.environ.get("GLASSNODE_API_KEY")
    if not api_key:
        return None
    try:
        until = int(time.time())
        since = until - days * 24 * 3600
        r = requests.get(
            f"{GLASSNODE_URL}/{endpoint}",
            params={
                "a": asset,
                "s": since,
                "u": until,
                "i": interval,
                "api_key": api_key,
            },
            timeout=15
        )
        if not r.ok:
            return None
        data = r.json()
        if isinstance(data, list) and data:
            return data[-1].get("v", data[-1])
        return data
    except Exception as e:
        logger.warning(f"Ошибка Glassnode {endpoint}: {e}")
        return None


def _interpret_onchain(data: Dict) -> str:
    """Вывод: накопление / распределение / фаза капитуляции."""
    sopr = data.get("sopr")
    mvrv_z = data.get("mvrv_z_score")
    nupl = data.get("nupl")
    exchange_flow_signal = data.get("exchange_flow_signal", 0)

    if mvrv_z is not None:
        if mvrv_z > 3.5:
            return "распределение (MVRV Z-Score высокий, переоценка)"
        if mvrv_z < 0:
            return "накопление (MVRV Z-Score < 0, недооценка)"

    if nupl is not None:
        if nupl > 0.75:
            return "распределение (NUPL эйфория)"
        if nupl < 0:
            return "фаза капитуляции (NUPL < 0, убытки)"

    if sopr is not None and sopr < 0.95:
        return "фаза капитуляции (SOPR < 1)"
    if sopr is not None and sopr > 1.05:
        return "распределение (прибыльные продажи)"

    if exchange_flow_signal > 0:
        return "накопление (отток с бирж)"
    if exchange_flow_signal < 0:
        return "распределение (приток на биржи)"

    return "нейтральная фаза"


def _apply_onchain_quality(
    result: Dict[str, Any],
    source: str,
    confidence: float,
    source_score: float,
    method: str = "",
) -> None:
    """Provenance для UI: при смешанных источниках — минимум confidence/source_score."""
    if result.get("onchain_source") in (None, "", "none"):
        result["onchain_source"] = source
        result["onchain_confidence"] = float(confidence)
        result["onchain_source_score"] = float(source_score)
        result["onchain_method"] = method
        return
    if result["onchain_source"] == source:
        return
    result["onchain_source"] = f"{result['onchain_source']}+{source}"
    result["onchain_confidence"] = min(float(result["onchain_confidence"]), float(confidence))
    result["onchain_source_score"] = min(float(result["onchain_source_score"]), float(source_score))
    prev_m = result.get("onchain_method") or ""
    result["onchain_method"] = f"{prev_m}+{method}" if prev_m else method


def get_btc_onchain() -> Optional[Dict]:
    """
    Получить он-чейн метрики Bitcoin: MVRV Z-Score, NUPL, SOPR.

    Returns:
        {
            "mvrv_z_score": float | None,
            "nupl": float | None,
            "sopr": float | None,
            "mvrv": float | None,
            "exchange_flow_signal": int,
            "sopr_signal": int,
            "interpretation": str,
            ...
        }
    """
    result: Dict[str, Any] = {
        "mvrv_z_score": None,
        "nupl": None,
        "sopr": None,
        "mvrv": None,
        "exchange_inflow_btc": None,
        "exchange_outflow_btc": None,
        "exchange_flow_signal": 0,
        "sopr_signal": 0,
        "active_addresses": 0,
        "transactions_24h": 0,
        "interpretation": "нет данных",
        "onchain_source": "none",
        "onchain_confidence": 0.0,
        "onchain_source_score": 0.0,
        "onchain_method": "",
    }

    stats = _get_blockchain_stats()
    if stats:
        result["transactions_24h"] = int(stats.get("n_tx", 0))

    addr_data = _get_blockchain_chart("n-unique-addresses", 30)
    if addr_data:
        result["active_addresses"] = int(addr_data[-1]["y"]) if addr_data else 0

    api_key = os.environ.get("GLASSNODE_API_KEY")
    if api_key:
        mvrv_z = _get_glassnode_metric("market/mvrv_z_score", days=7)
        if mvrv_z is not None:
            result["mvrv_z_score"] = float(mvrv_z) if not isinstance(mvrv_z, dict) else float(mvrv_z.get("v", 0))

        nupl = _get_glassnode_metric("indicators/nupl", days=7)
        if nupl is not None:
            result["nupl"] = float(nupl) if not isinstance(nupl, dict) else float(nupl.get("v", 0))

        mvrv = _get_glassnode_metric("market/mvrv", days=7)
        if mvrv is not None:
            result["mvrv"] = float(mvrv) if not isinstance(mvrv, dict) else float(mvrv.get("v", 0))

        sopr = _get_glassnode_metric("indicators/sopr", days=7)
        if sopr is not None:
            val = float(sopr) if not isinstance(sopr, dict) else float(sopr.get("v", 1.0))
            result["sopr"] = val
            result["sopr_signal"] = 1 if val < 1.0 else (-1 if val > 1.05 else 0)

        inflow = _get_glassnode_metric("transactions/transfers_volume_to_exchanges_sum", days=7)
        outflow = _get_glassnode_metric("transactions/transfers_volume_from_exchanges_sum", days=7)
        if inflow is not None and outflow is not None:
            in_val = float(inflow) if not isinstance(inflow, dict) else 0
            out_val = float(outflow) if not isinstance(outflow, dict) else 0
            result["exchange_inflow_btc"] = in_val
            result["exchange_outflow_btc"] = out_val
            if out_val > in_val * 1.1:
                result["exchange_flow_signal"] = 1
            elif in_val > out_val * 1.1:
                result["exchange_flow_signal"] = -1

        if (
            result["mvrv_z_score"] is not None
            or result["nupl"] is not None
            or result["sopr"] is not None
        ):
            _apply_onchain_quality(result, "glassnode", 0.95, 0.9, "api")

    # Fallback: LookIntoBitcoin — parse_fast → parse_selenium
    if result["mvrv_z_score"] is None or result["nupl"] is None or result["sopr"] is None:
        try:
            from .lookintobitcoin import get_lookintobitcoin_metrics
            lib_data = get_lookintobitcoin_metrics()
            if lib_data.get("source") == "failed":
                logger.error("CRITICAL: Onchain data unavailable — система работает вслепую")
            elif lib_data.get("source_score", 0) >= 0.4:
                confidence = lib_data.get("confidence", 0)
                if confidence >= 0.5:
                    filled_ltb = False
                    if result["mvrv_z_score"] is None and lib_data.get("mvrv_z_score") is not None:
                        result["mvrv_z_score"] = lib_data["mvrv_z_score"]
                        filled_ltb = True
                    if result["nupl"] is None and lib_data.get("nupl") is not None:
                        result["nupl"] = lib_data["nupl"]
                        filled_ltb = True
                    if result["sopr"] is None and lib_data.get("sopr") is not None:
                        val = lib_data["sopr"]
                        result["sopr"] = val
                        result["sopr_signal"] = 1 if val < 1.0 else (-1 if val > 1.05 else 0)
                        filled_ltb = True
                    if filled_ltb:
                        _apply_onchain_quality(
                            result,
                            str(lib_data.get("source", "lookintobitcoin")),
                            float(lib_data.get("confidence", 0)),
                            float(lib_data.get("source_score", 0)),
                            str(lib_data.get("method", "")),
                        )
        except Exception as e:
            logger.debug(f"LookIntoBitcoin fallback: {e}")

    # Третий fallback: CoinGecko proxy (plan §8.10)
    if result["mvrv_z_score"] is None or result["nupl"] is None or result["sopr"] is None:
        try:
            from .coingecko_onchain import get_coingecko_onchain_proxy
            cg = get_coingecko_onchain_proxy()
            if cg:
                filled = False
                if result["mvrv_z_score"] is None and cg.get("mvrv_z_score") is not None:
                    result["mvrv_z_score"] = cg["mvrv_z_score"]
                    filled = True
                if result["nupl"] is None and cg.get("nupl") is not None:
                    result["nupl"] = cg["nupl"]
                    filled = True
                if result["sopr"] is None and cg.get("sopr") is not None:
                    val = cg["sopr"]
                    result["sopr"] = val
                    result["sopr_signal"] = 1 if val < 1.0 else (-1 if val > 1.05 else 0)
                    filled = True
                if filled:
                    _apply_onchain_quality(
                        result,
                        str(cg.get("source", "coingecko")),
                        float(cg.get("confidence", 0)),
                        float(cg.get("source_score", 0)),
                        str(cg.get("method", "")),
                    )
        except Exception as e:
            logger.debug(f"CoinGecko onchain fallback: {e}")

    result["interpretation"] = _interpret_onchain(result)
    return result