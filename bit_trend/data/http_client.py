"""
Централизованные HTTP GET для внешних API: интервал между запросами по хосту,
ретраи при 429/5xx и сетевых сбоях, экспоненциальный backoff с джиттером.

Настройки через переменные окружения:
  HTTP_RATE_MIN_INTERVAL_SEC — минимум секунд между запросами к одному netloc (0 = выкл.)
  HTTP_MAX_RETRIES — число повторов после первой попытки (итого до 1 + HTTP_MAX_RETRIES запросов)
  HTTP_BACKOFF_BASE_SEC — база экспоненты, сек
  HTTP_BACKOFF_MAX_SEC — потолок ожидания между попытками, сек
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional, Set
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_request_monotonic: Dict[str, float] = {}

_DEFAULT_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _retry_status_codes() -> Set[int]:
    raw = os.environ.get("HTTP_RETRY_STATUS", "")
    if not raw.strip():
        return set(_DEFAULT_RETRY_STATUS)
    out: Set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out or set(_DEFAULT_RETRY_STATUS)


def _host_key(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host or "__nohost__"


def _rate_wait_seconds() -> float:
    return float(os.environ.get("HTTP_RATE_MIN_INTERVAL_SEC", "0.12"))


def _throttle(host: str) -> None:
    interval = _rate_wait_seconds()
    if interval <= 0:
        return
    with _lock:
        now = time.monotonic()
        last = _last_request_monotonic.get(host, 0.0)
        wait = last + interval - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _last_request_monotonic[host] = now


def _retry_after_seconds(response: requests.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delay = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delay)
    except (TypeError, ValueError, OverflowError):
        return None


def _backoff_sleep(attempt: int, base: float, cap: float) -> None:
    """Экспоненциальная задержка с джиттером (attempt от 0 после первой неудачи)."""
    exp = min(cap, base * (2**attempt))
    # полный джиттер в [0.5*exp, exp]
    delay = exp * (0.5 + 0.5 * random.random())
    time.sleep(delay)


def http_get(url: str, **kwargs) -> requests.Response:
    """
    GET с троттлингом по хосту и ретраями.

    Параметры как у requests.get; отдельных аргументов нет — max retries только из env.
    """
    max_retries = int(os.environ.get("HTTP_MAX_RETRIES", "3"))
    backoff_base = float(os.environ.get("HTTP_BACKOFF_BASE_SEC", "0.85"))
    backoff_max = float(os.environ.get("HTTP_BACKOFF_MAX_SEC", "32"))
    retry_codes = _retry_status_codes()
    host = _host_key(url)

    last_error: Optional[BaseException] = None
    attempt = 0

    while True:
        _throttle(host)
        try:
            response = requests.get(url, **kwargs)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt >= max_retries:
                logger.debug("http_get: исчерпаны ретраи для %s: %s", url, e)
                raise
            _backoff_sleep(attempt, backoff_base, backoff_max)
            attempt += 1
            continue

        if response.status_code in retry_codes and attempt < max_retries:
            ra = _retry_after_seconds(response)
            if ra is not None:
                time.sleep(min(backoff_max, ra))
            else:
                _backoff_sleep(attempt, backoff_base, backoff_max)
            attempt += 1
            continue

        return response
