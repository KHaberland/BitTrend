"""
ETF потоки Bitcoin: Coinglass API или парсинг Farside Investors.
"""

import logging
import os
import re
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

COINGLASS_BASE = "https://open-api-v4.coinglass.com"
FARSIDE_URL = "https://farside.co.uk/?p=997"


def _get_etf_coinglass() -> Optional[Dict]:
    """ETF данные через Coinglass. Требует COINGLASS_API_KEY."""
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        return None
    try:
        r_list = requests.get(
            f"{COINGLASS_BASE}/api/etf/bitcoin/list",
            headers={"CG-API-KEY": api_key},
            timeout=15
        )
        if not r_list.ok:
            return None
        data_list = r_list.json()
        if data_list.get("code") != "0":
            return None
        etfs = data_list.get("data", [])

        r_flow = requests.get(
            f"{COINGLASS_BASE}/api/etf/bitcoin/flow-history",
            headers={"CG-API-KEY": api_key},
            timeout=15
        )
        flow_data = []
        if r_flow.ok:
            data_flow = r_flow.json()
            if data_flow.get("code") == "0":
                flow_data = data_flow.get("data", [])[:7]

        total_aum = sum(float(e.get("aum_usd", 0) or 0) for e in etfs)
        flow_7d = sum(float(f.get("flow_usd", 0) or 0) for f in flow_data)
        flow_1d = float(flow_data[0].get("flow_usd", 0)) if flow_data else 0

        return {
            "flow_1d_usd": flow_1d,
            "flow_7d_usd": flow_7d,
            "total_aum_usd": total_aum,
            "etf_count": len(etfs),
            "interpretation": _interpret_etf_flows(flow_1d, flow_7d),
        }
    except Exception as e:
        logger.warning(f"Ошибка Coinglass ETF: {e}")
        return None


def _parse_farside_flows() -> Optional[Dict]:
    """
    Парсинг страницы Farside Investors для ETF flows.
    Fallback при отсутствии Coinglass API.
    """
    try:
        r = requests.get(FARSIDE_URL, timeout=15)
        if not r.ok:
            return None
        html = r.text

        flow_7d = 0.0
        flow_1d = 0.0

        numbers = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", html)
        for i, num in enumerate(numbers):
            try:
                val = float(num)
                if abs(val) > 1_000_000 and abs(val) < 100_000_000_000:
                    if flow_7d == 0:
                        flow_7d = val
                    elif flow_1d == 0:
                        flow_1d = val
                        break
            except ValueError:
                continue

        return {
            "flow_1d_usd": flow_1d,
            "flow_7d_usd": flow_7d,
            "total_aum_usd": 0,
            "etf_count": 0,
            "interpretation": _interpret_etf_flows(flow_1d, flow_7d),
            "source": "farside_parsed",
        }
    except Exception as e:
        logger.warning(f"Ошибка парсинга Farside: {e}")
        return None


def _interpret_etf_flows(flow_1d: float, flow_7d: float) -> str:
    """Интерпретация ETF потоков."""
    if flow_7d > 500_000_000:
        return "сильный приток в ETF (институциональный спрос)"
    if flow_7d < -500_000_000:
        return "отток из ETF (институциональная осторожность)"
    if flow_1d > 100_000_000:
        return "приток в ETF за день"
    if flow_1d < -100_000_000:
        return "отток из ETF за день"
    return "нейтральные потоки ETF"


def get_etf_flows() -> Optional[Dict]:
    """
    Получить данные по ETF потокам Bitcoin.
    Coinglass (если есть ключ) или парсинг Farside.

    Returns:
        {
            "flow_1d_usd": float,
            "flow_7d_usd": float,
            "total_aum_usd": float,
            "etf_count": int,
            "interpretation": str
        }
    """
    result = _get_etf_coinglass()
    if result:
        return result

    result = _parse_farside_flows()
    if result:
        return result

    return {
        "flow_1d_usd": 0,
        "flow_7d_usd": 0,
        "total_aum_usd": 0,
        "etf_count": 0,
        "interpretation": "нет данных ETF",
    }