"""
Интеграция с Alternative.me API — Fear & Greed Index.
"""

import logging
from typing import Optional, Dict

from .http_client import http_get

logger = logging.getLogger(__name__)

FNG_URL = "https://api.alternative.me/fng/"


def get_fear_greed_index() -> Optional[Dict]:
    """
    Получить индекс страха и жадности (0–100).

    Returns:
        {"value": int, "classification": str, "timestamp": int} или None при ошибке
    """
    try:
        response = http_get(FNG_URL, params={"limit": 1}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("metadata", {}).get("error"):
            return None
        items = data.get("data", [])
        if not items:
            return None
        item = items[0]
        return {
            "value": int(item.get("value", 50)),
            "classification": item.get("value_classification", "Neutral"),
            "timestamp": int(item.get("timestamp", 0)),
        }
    except Exception as e:
        logger.warning(f"Ошибка получения Fear & Greed Index: {e}")
        return None
