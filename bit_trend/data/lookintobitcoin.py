"""
Парсинг LookIntoBitcoin для MVRV Z-Score, NUPL, SOPR.
Idempotency, freshness, source_score, merge для quant-уровня.
"""

import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from .http_client import http_get

logger = logging.getLogger(__name__)

PARSER_VERSION = "v2_pattern_extraction"

# Feature flags — быстро отключать источники, тестировать
USE_LOOKINTOBITCOIN = os.environ.get("USE_LOOKINTOBITCOIN", "true").lower() in ("true", "1", "yes")
USE_SELENIUM = os.environ.get("USE_SELENIUM", "true").lower() in ("true", "1", "yes")

# Кэш
CACHE_TTL_BASE = int(os.environ.get("LOOKINTOBITCOIN_CACHE_TTL", 86400))
CACHE_TTL_WEEKEND = 2 * 86400

# Circuit breaker
FAIL_LIMIT = int(os.environ.get("LOOKINTOBITCOIN_FAIL_LIMIT", 5))
DISABLE_HOURS = int(os.environ.get("LOOKINTOBITCOIN_DISABLE_HOURS", 6))

# Стабильность: max_delta для защиты от скачков (MVRV 2.1 → 9.8 → 2.2)
MAX_DELTA = {
    "mvrv_z_score": float(os.environ.get("LOOKINTOBITCOIN_MAX_DELTA_MVRV", "0.5")),
    "nupl": float(os.environ.get("LOOKINTOBITCOIN_MAX_DELTA_NUPL", "0.1")),
    "sopr": float(os.environ.get("LOOKINTOBITCOIN_MAX_DELTA_SOPR", "0.1")),
}

# Freshness
MAX_AGE_HOURS = int(os.environ.get("LOOKINTOBITCOIN_MAX_AGE_HOURS", 24))
SOURCE_SCORE_THRESHOLD = float(os.environ.get("LOOKINTOBITCOIN_SOURCE_SCORE_THRESHOLD", "0.4"))

BASE_URL = "https://www.lookintobitcoin.com"
CHARTS = {
    "mvrv_z_score": "/charts/mvrv-zscore/",
    "nupl": "/charts/nupl/",
    "sopr": "/charts/sopr/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT = 10
SELENIUM_WAIT_SEC = 10

# Модульное состояние
_cache: Optional[Dict[str, Any]] = None
_cache_time: float = 0
_fail_count: int = 0
_circuit_open_until: float = 0
_success_history: deque = deque(maxlen=20)


# --- Deduplication ---
def is_same(prev: Optional[float], current: Optional[float], eps: float = 1e-6) -> bool:
    """Не писать в БД одно и то же."""
    if prev is None and current is None:
        return True
    if prev is None or current is None:
        return False
    return abs(prev - current) < eps


# --- Drift detection: медленное сползание данных (возможно баг парсинга) ---
def detect_drift(values: List[float], window: int = 10, threshold: float = 0.5) -> bool:
    """Если max - min в окне > threshold → данные ползут."""
    if len(values) < window:
        return False
    window_vals = values[-window:]
    return max(window_vals) - min(window_vals) > threshold


# --- Idempotency: защита от скачков ---
def stabilize(prev: Optional[float], current: Optional[float], key: str) -> Optional[float]:
    """Парсинг 2.1 → 9.8 → 2.2 убивает стратегию. Возвращаем prev при скачке."""
    if current is None:
        return prev
    if prev is None:
        return current
    max_delta = MAX_DELTA.get(key, 0.5)
    if abs(current - prev) > max_delta:
        logger.warning(f"LookIntoBitcoin stabilize: {key} jump {prev:.3f}→{current:.3f} rejected (max_delta={max_delta})")
        return prev
    return current


# --- Freshness ---
def is_fresh(ts_str: str, max_age_hours: int = MAX_AGE_HOURS) -> bool:
    """Старые данные ≠ плохие, но менее надёжные."""
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_sec = (now - ts).total_seconds()
        return age_sec < max_age_hours * 3600
    except Exception:
        return False


def _get_freshness_factor(ts_str: str) -> float:
    """1.0 = свежие, 0.5 = старые (снижаем confidence)."""
    return 1.0 if is_fresh(ts_str) else 0.5


# --- Quality score источника ---
def compute_source_score(
    success_rate: float,
    confidence: float,
    freshness: float,
) -> float:
    """source_score = success_rate*0.5 + confidence*0.3 + freshness*0.2"""
    return success_rate * 0.5 + confidence * 0.3 + freshness * 0.2


# --- Multi-source merge (для quant-систем) ---
def merge_sources(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Выбор по confidence или weighted average."""
    conf_a = a.get("confidence", 0) or 0
    conf_b = b.get("confidence", 0) or 0
    if conf_a >= conf_b and any(a.get(k) for k in ("mvrv_z_score", "nupl", "sopr")):
        return a
    if any(b.get(k) for k in ("mvrv_z_score", "nupl", "sopr")):
        return b
    return a


def merge_weighted(a: Dict[str, Any], b: Dict[str, Any], key: str) -> Optional[float]:
    """weighted = (a*conf_a + b*conf_b) / (conf_a + conf_b)"""
    va, vb = a.get(key), b.get(key)
    conf_a = a.get("confidence", 0) or 0
    conf_b = b.get("confidence", 0) or 0
    if va is None and vb is None:
        return None
    if va is None:
        return vb
    if vb is None:
        return va
    total = conf_a + conf_b
    if total <= 0:
        return va
    return (va * conf_a + vb * conf_b) / total


# --- Data validation ---
def _validate_mvrv(value: float) -> bool:
    return -5 < value < 20


def _validate_nupl(value: float) -> bool:
    return -0.5 <= value <= 1.5


def _validate_sopr(value: float) -> bool:
    return 0.5 <= value <= 2.0


def _validate_value(key: str, value: float) -> bool:
    if value is None or (isinstance(value, float) and (value != value or abs(value) > 1e10)):
        return False
    validators = {"mvrv_z_score": _validate_mvrv, "nupl": _validate_nupl, "sopr": _validate_sopr}
    fn = validators.get(key)
    if fn and not fn(value):
        logger.warning(f"LookIntoBitcoin invalid {key}={value} (sanity check failed)")
        return False
    return True


def _get_cache_ttl() -> int:
    now = datetime.now()
    return CACHE_TTL_WEEKEND if now.weekday() >= 5 else CACHE_TTL_BASE


def _get_success_rate() -> float:
    if not _success_history:
        return 1.0
    return sum(_success_history) / len(_success_history)


def _is_circuit_open() -> bool:
    global _circuit_open_until
    now = time.time()
    if now < _circuit_open_until:
        return True
    if _circuit_open_until > 0:
        logger.info("LookIntoBitcoin circuit breaker: attempting recovery")
        _circuit_open_until = 0
    return False


def _record_failure() -> None:
    global _fail_count, _circuit_open_until
    _fail_count += 1
    _success_history.append(0)
    if _fail_count >= FAIL_LIMIT:
        _circuit_open_until = time.time() + DISABLE_HOURS * 3600
        logger.warning(f"LookIntoBitcoin circuit breaker: отключено на {DISABLE_HOURS} ч после {_fail_count} неудач")


def _record_success() -> None:
    global _fail_count
    _fail_count = 0
    _success_history.append(1)


def _fetch_page(path: str) -> Optional[str]:
    try:
        r = http_get(f"{BASE_URL}{path}", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if not r.ok:
            logger.debug(f"LookIntoBitcoin {path}: HTTP {r.status_code}")
            return None
        return r.text
    except Exception as e:
        logger.debug(f"LookIntoBitcoin {path}: {e}")
        return None


DATA_PATTERNS = [
    re.compile(r'"datasets":\s*(\[[\s\S]*?\])', re.IGNORECASE),
    re.compile(r'datasets:\s*(\[[\s\S]*?\])\s*[,}\]]', re.IGNORECASE),
    re.compile(r'"data":\s*(\[[\s\S]*?\])', re.IGNORECASE),
    re.compile(r'data:\s*(\[[\s\S]*?\])\s*[,}\]]', re.IGNORECASE),
    re.compile(r'"values":\s*(\[[\s\S]*?\])', re.IGNORECASE),
    re.compile(r'values:\s*(\[[\s\S]*?\])\s*[,}\]]', re.IGNORECASE),
    re.compile(r'(\[[\s]*\[[\d.e+-]+,\s*[\d.e+-]+\][\s\S]*?\])\s*[,}\]]'),
]


def _extract_json_array(text: str) -> Optional[List]:
    for pattern in DATA_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            try:
                data = json.loads(raw)
                if isinstance(data, list) and len(data) > 0:
                    return data
            except json.JSONDecodeError:
                pairs = re.findall(r"\[([\d.e+-]+)\s*,\s*([\d.e+-]+)\]", raw)
                if pairs:
                    return [[float(x), float(y)] for x, y in pairs]
    return None


def _parse_chart_value(data: List) -> Optional[float]:
    if not data:
        return None
    last = data[-1]
    try:
        if isinstance(last, (list, tuple)) and len(last) >= 2:
            return float(last[1])
        if isinstance(last, dict):
            return float(last.get("y", last.get("v", last.get("value", 0))))
    except (TypeError, ValueError):
        return None
    return None


def _parse_from_text(text: str) -> Optional[float]:
    arr = _extract_json_array(text)
    return _parse_chart_value(arr) if arr else None


def _parse_chart_fast(metric_key: str) -> Optional[float]:
    path = CHARTS.get(metric_key)
    if not path:
        return None
    html = _fetch_page(path)
    if not html:
        return None
    return _parse_from_text(html)


# --- Selenium pool: kill при idle > max_idle (утечки, зависшие процессы) ---
class SeleniumPool:
    _driver = None
    _last_used: float = 0
    _max_idle_sec = 300

    @classmethod
    def get_driver(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        now = time.time()
        if cls._driver is not None:
            idle = now - cls._last_used
            if idle < cls._max_idle_sec:
                cls._last_used = now
                return cls._driver
            cls.kill_idle()

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        cls._driver = webdriver.Chrome(options=opts)
        cls._driver.set_page_load_timeout(REQUEST_TIMEOUT + 10)
        cls._last_used = now
        return cls._driver

    @classmethod
    def kill_idle(cls) -> None:
        """Явный kill при idle > max_idle — утечки памяти, зависшие процессы."""
        if cls._driver:
            try:
                cls._driver.quit()
            except Exception:
                pass
            cls._driver = None

    @classmethod
    def quit(cls) -> None:
        cls.kill_idle()


def _parse_chart_selenium(metric_key: str) -> Optional[float]:
    if not USE_SELENIUM:
        return None
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        logger.debug("Selenium не установлен: pip install selenium")
        return None

    path = CHARTS.get(metric_key)
    if not path:
        return None

    try:
        driver = SeleniumPool.get_driver()
        driver.get(f"{BASE_URL}{path}")

        wait = WebDriverWait(driver, SELENIUM_WAIT_SEC)
        scripts = wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "script")))

        for el in scripts:
            try:
                inner = el.get_attribute("innerHTML") or ""
                val = _parse_from_text(inner)
                if val is not None and _validate_value(metric_key, val):
                    return val
            except Exception:
                continue

        val = _parse_from_text(driver.page_source)
        return val if (val is not None and _validate_value(metric_key, val)) else None
    except Exception as e:
        logger.debug(f"LookIntoBitcoin Selenium {metric_key}: {e}")
        return None


def _build_result(
    mvrv: Optional[float],
    nupl: Optional[float],
    sopr: Optional[float],
    source: str,
    method: str,
    base_confidence: float,
    prev: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Data provenance + stabilize + freshness + source_score."""
    # Stabilize против предыдущего кэша
    if prev:
        mvrv = stabilize(prev.get("mvrv_z_score"), mvrv, "mvrv_z_score")
        nupl = stabilize(prev.get("nupl"), nupl, "nupl")
        sopr = stabilize(prev.get("sopr"), sopr, "sopr")

    ts = datetime.now(timezone.utc).isoformat()
    success_rate = _get_success_rate()
    confidence = round(base_confidence * success_rate, 2)
    freshness = _get_freshness_factor(ts)
    if not is_fresh(ts):
        confidence = round(confidence * 0.5, 2)
    source_score = round(compute_source_score(success_rate, confidence, freshness), 2)

    return {
        "mvrv_z_score": mvrv,
        "nupl": nupl,
        "sopr": sopr,
        "source": source,
        "method": method,
        "confidence": confidence,
        "parser_version": PARSER_VERSION,
        "timestamp": ts,
        "source_score": source_score,
    }


def parse_fast() -> Tuple[Dict[str, Any], float]:
    if not USE_LOOKINTOBITCOIN:
        return {"mvrv_z_score": None, "nupl": None, "sopr": None}, 0.0
    result: Dict[str, Any] = {"mvrv_z_score": None, "nupl": None, "sopr": None}
    for key in ("mvrv_z_score", "nupl", "sopr"):
        val = _parse_chart_fast(key)
        if val is not None and _validate_value(key, val):
            result[key] = val
            logger.debug(f"LookIntoBitcoin fast {key}: {val}")
    has_data = any(result.get(k) for k in ("mvrv_z_score", "nupl", "sopr"))
    return result, 0.9 if has_data else 0.0


def parse_selenium() -> Tuple[Dict[str, Any], float]:
    result: Dict[str, Any] = {"mvrv_z_score": None, "nupl": None, "sopr": None}
    for key in ("mvrv_z_score", "nupl", "sopr"):
        val = _parse_chart_selenium(key)
        if val is not None and _validate_value(key, val):
            result[key] = val
            logger.debug(f"LookIntoBitcoin selenium {key}: {val}")
    has_data = any(result.get(k) for k in ("mvrv_z_score", "nupl", "sopr"))
    return result, 0.6 if has_data else 0.0


def _failed_result() -> Dict[str, Any]:
    return _build_result(
        mvrv=None, nupl=None, sopr=None,
        source="failed", method="none", base_confidence=0.0,
    )


def _merge_last_known_good(out: Dict[str, Any], last: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Graceful degradation: подставить last_known_good при failed."""
    if not last or out.get("source") != "failed":
        return out
    for key in ("mvrv_z_score", "nupl", "sopr"):
        if out.get(key) is None and last.get(key) is not None:
            out[key] = last[key]
            out["source"] = "last_known_good"
    return out


def _save_history_if_changed(data: Dict[str, Any]) -> None:
    """Записать в time-series storage при изменении."""
    try:
        from .storage import save_history
        save_history(data)
    except Exception as e:
        logger.debug(f"save_history: {e}")


def get_last_known_good() -> Optional[Dict[str, Any]]:
    """Graceful degradation: последние известные хорошие значения."""
    if _cache and _cache.get("source") not in ("failed", "none"):
        return _cache
    try:
        from .storage import get_last_history
        return get_last_history()
    except Exception:
        return None


def get_lookintobitcoin_metrics() -> Dict[str, Any]:
    """
    MVRV Z-Score, NUPL, SOPR.
    Idempotency (stabilize), freshness, source_score, last_known_good.
    """
    global _cache, _cache_time

    if not USE_LOOKINTOBITCOIN:
        logger.debug("LookIntoBitcoin disabled (USE_LOOKINTOBITCOIN=false)")
        out = _failed_result()
        last = get_last_known_good()
        return _merge_last_known_good(out, last)

    if _is_circuit_open():
        logger.info("LookIntoBitcoin circuit breaker: источник отключён")
        out = _failed_result()
        last = get_last_known_good()
        return _merge_last_known_good(out, last)

    now = time.time()
    ttl = _get_cache_ttl()
    if _cache is not None and (now - _cache_time) < ttl:
        return _cache

    # parse_fast
    try:
        result, base_conf = parse_fast()
        if any(result.get(k) for k in ("mvrv_z_score", "nupl", "sopr")):
            out = _build_result(
                mvrv=result.get("mvrv_z_score"),
                nupl=result.get("nupl"),
                sopr=result.get("sopr"),
                source="lookintobitcoin",
                method="fast",
                base_confidence=base_conf,
                prev=_cache,
            )
            if out.get("source_score", 0) >= SOURCE_SCORE_THRESHOLD:
                _record_success()
                _cache = out
                _cache_time = now
                _save_history_if_changed(out)
                return out
            logger.warning(f"LookIntoBitcoin source_score {out.get('source_score')} < {SOURCE_SCORE_THRESHOLD}, ignore_source")
            last = get_last_known_good()
            return _merge_last_known_good(out, last)
    except Exception as e:
        logger.warning(f"LookIntoBitcoin fast parsing failed: {e}")

    # parse_selenium (если USE_SELENIUM)
    if not USE_SELENIUM:
        logger.debug("Selenium disabled (USE_SELENIUM=false)")
        out = _failed_result()
        return _merge_last_known_good(out, get_last_known_good())

    logger.info("LookIntoBitcoin: fallback to Selenium")
    try:
        result, base_conf = parse_selenium()
        if any(result.get(k) for k in ("mvrv_z_score", "nupl", "sopr")):
            out = _build_result(
                mvrv=result.get("mvrv_z_score"),
                nupl=result.get("nupl"),
                sopr=result.get("sopr"),
                source="lookintobitcoin",
                method="selenium",
                base_confidence=base_conf,
                prev=_cache,
            )
            if out.get("source_score", 0) >= SOURCE_SCORE_THRESHOLD:
                _record_success()
                _cache = out
                _cache_time = now
                _save_history_if_changed(out)
                return out
    except Exception as e:
        logger.warning(f"LookIntoBitcoin Selenium failed: {e}")

    _record_failure()
    out = _failed_result()
    return _merge_last_known_good(out, get_last_known_good())
