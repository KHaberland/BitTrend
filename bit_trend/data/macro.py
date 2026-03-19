"""
Макроэкономика: ФРС, DXY, доходности 10Y.
Опционально: FRED API (при наличии FRED_API_KEY).
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

import requests

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
SERIES_FEDFUNDS = "FEDFUNDS"
SERIES_DGS10 = "DGS10"
SERIES_DTWEXBGS = "DTWEXBGS"


def _get_fred_observations(
    series_id: str,
    limit: int = 10,
    sort_order: str = "desc"
) -> Optional[List[Dict]]:
    """Получить последние наблюдения из FRED."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        r = requests.get(
            f"{FRED_BASE}/series/observations",
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": start,
                "observation_end": end,
                "sort_order": sort_order,
                "limit": limit,
            },
            timeout=15
        )
        if not r.ok:
            return None
        data = r.json()
        return data.get("observations", [])
    except Exception as e:
        logger.warning(f"Ошибка FRED {series_id}: {e}")
        return None


def _parse_fred_value(obs: Dict) -> Optional[float]:
    """Извлечь числовое значение из наблюдения FRED."""
    val = obs.get("value")
    if val is None or val == ".":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _get_latest_fred(series_id: str) -> Optional[float]:
    """Получить последнее значение серии FRED."""
    obs = _get_fred_observations(series_id, limit=1)
    if not obs:
        return None
    return _parse_fred_value(obs[0])


def _interpret_macro(data: Dict) -> Tuple[int, str]:
    """
    macro_signal: -1 = сжатие, 0 = нейтрально, +1 = расширение
    """
    fed = data.get("fed_funds_rate")
    dxy_change = data.get("dxy_30d_change_pct")
    treasury_10y = data.get("treasury_10y")

    score = 0
    parts = []

    if fed is not None:
        if fed < 4.0:
            score += 1
            parts.append("ФРС смягчает")
        elif fed > 5.0:
            score -= 1
            parts.append("ФРС ужесточает")

    if dxy_change is not None:
        if dxy_change > 3:
            score -= 1
            parts.append("рост DXY")
        elif dxy_change < -3:
            score += 1
            parts.append("падение DXY")

    if treasury_10y is not None:
        if treasury_10y > 4.5:
            score -= 1
            parts.append("высокие доходности 10Y")
        elif treasury_10y < 3.0:
            score += 1
            parts.append("низкие доходности 10Y")

    signal = max(-1, min(1, score))
    if signal > 0:
        interp = "ликвидность расширяется"
    elif signal < 0:
        interp = "ликвидность сжимается"
    else:
        interp = "нейтральная среда"

    if parts:
        interp += f" ({'; '.join(parts)})"

    return signal, interp


def get_macro_data() -> Optional[Dict]:
    """
    Получить макроэкономические данные (ставки, DXY, 10Y).

    Returns:
        {
            "fed_funds_rate": float | None,
            "treasury_10y": float | None,
            "dxy": float | None,
            "dxy_30d_change_pct": float | None,
            "macro_signal": int,
            "interpretation": str
        }
    """
    result: Dict[str, Any] = {
        "fed_funds_rate": None,
        "treasury_10y": None,
        "dxy": None,
        "dxy_30d_change_pct": None,
        "macro_signal": 0,
        "interpretation": "нет данных (нужен FRED_API_KEY)",
    }

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return result

    result["fed_funds_rate"] = _get_latest_fred(SERIES_FEDFUNDS)
    result["treasury_10y"] = _get_latest_fred(SERIES_DGS10)

    dxy_obs = _get_fred_observations(SERIES_DTWEXBGS, limit=35)
    if dxy_obs:
        latest = _parse_fred_value(dxy_obs[0])
        oldest = _parse_fred_value(dxy_obs[-1]) if len(dxy_obs) > 1 else latest
        result["dxy"] = latest
        if latest and oldest and oldest > 0:
            result["dxy_30d_change_pct"] = (latest - oldest) / oldest * 100

    result["macro_signal"], result["interpretation"] = _interpret_macro(result)
    return result