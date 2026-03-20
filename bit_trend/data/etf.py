"""
ETF потоки Bitcoin: Coinglass API или парсинг Farside Investors (plan 8.4).
Источник: https://farside.co.uk/btc/
Парсинг: soup.find("table") — только таблица, проверка структуры.
"""

import logging
import os
import re
import time
from typing import Optional, Dict, Any, List, Tuple

from .http_client import http_get

logger = logging.getLogger(__name__)

COINGLASS_BASE = "https://open-api-v4.coinglass.com"
# Plan 8.4: лучший источник
FARSIDE_URL = "https://farside.co.uk/btc/"

# Feature flag — отключить Selenium для тестов
USE_FARSIDE_SELENIUM = os.environ.get("USE_FARSIDE_SELENIUM", "true").lower() in ("true", "1", "yes")

# Значения в таблице Farside — US$m (миллионы)
FARSIDE_MULTIPLIER = 1_000_000


def _get_etf_coinglass() -> Optional[Dict]:
    """ETF данные через Coinglass. Требует COINGLASS_API_KEY."""
    api_key = os.environ.get("COINGLASS_API_KEY")
    if not api_key:
        return None
    try:
        r_list = http_get(
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

        r_flow = http_get(
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
            "source": "coinglass",
        }
    except Exception as e:
        logger.warning(f"Ошибка Coinglass ETF: {e}")
        return None


def _parse_farside_value(cell_text: str) -> Optional[float]:
    """
    Парсить значение из ячейки Farside.
    (89.3) = -89.3, 63,340 = 63340, значения в млн USD.
    """
    text = cell_text.strip().replace(",", "").replace(" ", "")
    if not text or text in ("-", "–", "—"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        val = float(text)
        return -val if negative else val
    except ValueError:
        return None


def _is_date_row(label: str) -> bool:
    """Проверка: строка с датой (02 Mar 2026, 16 Mar 2026 и т.д.)."""
    if not label or len(label) < 8:
        return False
    # Формат: DD Mon YYYY
    date_pattern = re.compile(r"^\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}$", re.I)
    return bool(date_pattern.match(label.strip()))


def _parse_farside_table(html: str) -> Optional[Tuple[float, float]]:
    """
    Парсинг таблицы Farside (plan 8.4: soup.find("table")).
    Returns (flow_1d_usd, flow_7d_usd) или None.
    Структура: колонка Total = последняя колонка (агрегат по дням), строки с датами.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("BeautifulSoup не установлен: pip install beautifulsoup4")
        return None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="etf") or soup.find("table")
    if not table:
        logger.warning("Farside: таблица не найдена")
        return None

    rows = table.find_all("tr")
    if not rows:
        return None

    total_col_idx = None
    for row in rows[:3]:
        cells = row.find_all(["th", "td"])
        for i, c in enumerate(cells):
            if "total" in (c.get_text(strip=True) or "").lower():
                total_col_idx = i
                break
        if total_col_idx is not None:
            break
    if total_col_idx is None:
        total_col_idx = -1

    daily_flows: List[float] = []
    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True) if cells else ""
        if not _is_date_row(label):
            continue
        idx = total_col_idx if total_col_idx >= 0 else len(cells) + total_col_idx
        if idx >= len(cells):
            continue
        val = _parse_farside_value(cells[idx].get_text(strip=True))
        if val is not None:
            daily_flows.append(val * FARSIDE_MULTIPLIER)

    if not daily_flows:
        logger.warning("Farside: не найдены строки с датами и потоками")
        return None

    flow_1d = daily_flows[-1]
    flow_7d = sum(daily_flows[-7:])
    return (flow_1d, flow_7d)


def _fetch_farside_selenium() -> Optional[str]:
    """Загрузка страницы Farside через Selenium (Cloudflare bypass)."""
    if not USE_FARSIDE_SELENIUM:
        return None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
    except ImportError:
        logger.debug("Selenium не установлен для Farside")
        return None

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(60)
        driver.get(FARSIDE_URL)
        time.sleep(8)
        wait = WebDriverWait(driver, 25)
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.etf")))
        except Exception:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(2)
        return driver.page_source
    except Exception as e:
        logger.warning(f"Farside Selenium: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _parse_farside_flows() -> Optional[Dict]:
    """
    Парсинг Farside Investors (plan 8.4).
    Selenium + soup.find("table") — Cloudflare блокирует requests.
    """
    html = _fetch_farside_selenium()
    if not html:
        return None

    parsed = _parse_farside_table(html)
    if not parsed:
        return None

    flow_1d, flow_7d = parsed
    return {
        "flow_1d_usd": flow_1d,
        "flow_7d_usd": flow_7d,
        "total_aum_usd": 0,
        "etf_count": 0,
        "interpretation": _interpret_etf_flows(flow_1d, flow_7d),
        "source": "farside_table",
    }


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
    Получить данные по ETF потокам Bitcoin (plan 8.4).
    Цепочка: Coinglass (если ключ) → Farside Selenium+table → fallback.

    Returns:
        {
            "flow_1d_usd": float,
            "flow_7d_usd": float,
            "total_aum_usd": float,
            "etf_count": int,
            "interpretation": str,
            "source": str
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
        "source": "none",
    }
