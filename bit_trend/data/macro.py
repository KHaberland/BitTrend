"""
Макроэкономика: ФРС, DXY, доходности 10Y.
Опционально: FRED API (при наличии FRED_API_KEY).
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

from .http_client import http_get

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
SERIES_FEDFUNDS = "FEDFUNDS"
SERIES_DGS10 = "DGS10"
SERIES_DTWEXBGS = "DTWEXBGS"
SERIES_CPI = "CPIAUCSL"


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
        r = http_get(
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


def _get_cpi_level_and_yoy() -> Tuple[Optional[float], Optional[float]]:
    """Индекс CPI (уровень) и изменение г/г, %. FRED CPIAUCSL (§8.5)."""
    obs = _get_fred_observations(SERIES_CPI, limit=14)
    if not obs or len(obs) < 13:
        return None, None
    latest = _parse_fred_value(obs[0])
    yago = _parse_fred_value(obs[12])
    if latest is None:
        return None, None
    if yago is None or yago == 0:
        return latest, None
    yoy = (latest / yago - 1.0) * 100.0
    return latest, yoy


def _get_sp500_level_and_30d_change() -> Tuple[Optional[float], Optional[float]]:
    """S&P 500: уровень и изменение ~30 торговых дней (yfinance ^GSPC), plan §8.5."""
    try:
        import yfinance as yf
        t = yf.Ticker("^GSPC")
        hist = t.history(period="3mo")
        if hist is None or hist.empty or len(hist) < 22:
            return None, None
        close = hist["Close"].astype(float)
        latest = float(close.iloc[-1])
        ref = float(close.iloc[-22])
        if ref == 0:
            return latest, None
        pct = (latest / ref - 1.0) * 100.0
        return latest, pct
    except Exception as e:
        logger.warning("S&P 500 (yfinance): %s", e)
        return None, None


def _interpret_macro(data: Dict) -> Tuple[int, str]:
    """
    macro_signal: -1 = сжатие, 0 = нейтрально, +1 = расширение
    """
    fed = data.get("fed_funds_rate")
    dxy_change = data.get("dxy_30d_change_pct")
    treasury_10y = data.get("treasury_10y")
    cpi_yoy = data.get("cpi_yoy_pct")
    sp_chg = data.get("sp500_30d_change_pct")

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

    if cpi_yoy is not None:
        if cpi_yoy > 5.0:
            score -= 1
            parts.append("высокий CPI г/г")
        elif cpi_yoy < 2.5:
            score += 1
            parts.append("умеренный CPI г/г")

    if sp_chg is not None:
        if sp_chg >= 4.0:
            score += 1
            parts.append("S&P ~30д в плюсе")
        elif sp_chg <= -7.0:
            score -= 1
            parts.append("S&P ~30д под давлением")

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
    Получить макроэкономические данные (ставки, DXY, 10Y, CPI по FRED; S&P 500 — yfinance).

    DXY в коде — FRED DTWEXBGS (как upgrade_plan); в plan.md также упоминается Yahoo — формулировки см. README.

    Returns:
        Словарь с полями FRED, cpi_*, sp500_*, macro_signal, interpretation.
    """
    result: Dict[str, Any] = {
        "fed_funds_rate": None,
        "treasury_10y": None,
        "dxy": None,
        "dxy_30d_change_pct": None,
        "cpi_index": None,
        "cpi_yoy_pct": None,
        "sp500": None,
        "sp500_30d_change_pct": None,
        "macro_signal": 0,
        "interpretation": "",
    }

    api_key = os.environ.get("FRED_API_KEY")
    if api_key:
        result["fed_funds_rate"] = _get_latest_fred(SERIES_FEDFUNDS)
        result["treasury_10y"] = _get_latest_fred(SERIES_DGS10)

        dxy_obs = _get_fred_observations(SERIES_DTWEXBGS, limit=35)
        if dxy_obs:
            latest = _parse_fred_value(dxy_obs[0])
            oldest = _parse_fred_value(dxy_obs[-1]) if len(dxy_obs) > 1 else latest
            result["dxy"] = latest
            if latest and oldest and oldest > 0:
                result["dxy_30d_change_pct"] = (latest - oldest) / oldest * 100

        cpi_lvl, cpi_yoy = _get_cpi_level_and_yoy()
        result["cpi_index"] = cpi_lvl
        result["cpi_yoy_pct"] = cpi_yoy

    sp_lvl, sp_chg = _get_sp500_level_and_30d_change()
    result["sp500"] = sp_lvl
    result["sp500_30d_change_pct"] = sp_chg

    if not api_key:
        result["interpretation"] = "нет FRED (ставки/DXY/10Y/CPI); S&P доступен без ключа"

    result["macro_signal"], result["interpretation"] = _interpret_macro(result)
    return result