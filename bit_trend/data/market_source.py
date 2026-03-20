"""
Абстракция источников price / market_cap / volume (plan01 §8).
Потребители ожидают единый контракт; провайдеры — cmc (CoinMarketCap), freecrypto, coingecko, binance.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

import pandas as pd

logger = logging.getLogger(__name__)

# plan01 §10: in-memory TTL-кэш для get_market_current_with_fallback (символ, гранулярность, вид эндпоинта)
_market_current_cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# plan01 §9: circuit breaker по имени провайдера (monotonic секунды — open_until, счётчик подряд)
_cb_lock = threading.Lock()
_cb_fail_streak: Dict[str, int] = {}
_cb_open_until: Dict[str, float] = {}


class MarketDataSource(ABC):
    """Источник рыночных полей для символа (по умолчанию BTC)."""

    @abstractmethod
    def get_current(self, symbol: str) -> Dict[str, Any]:
        """
        Текущий снимок. Рекомендуемые ключи:
        symbol, price, market_cap, volume, timestamp (unix int или ISO UTC str), source (имя провайдера).
        """

    @abstractmethod
    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        """
        История за до `days` дней (по возможности провайдера).
        Колонки: timestamp (datetime64 UTC), price, market_cap, volume.
        Пустой DataFrame, если данных нет.
        """


def sanity_check_market_row(row: Dict[str, Any], *, require_market_cap: bool = True) -> bool:
    """plan01 §7.2: цена и кап > 0, объём ≥ 0. Без валидного капа при require_market_cap — False."""
    try:
        price = float(row.get("price", 0) or 0)
        if price <= 0:
            return False
        cap = row.get("market_cap")
        if require_market_cap:
            if cap is None or float(cap) <= 0:
                return False
        vol = row.get("volume")
        if vol is None:
            return True
        return float(vol) >= 0
    except (TypeError, ValueError):
        return False


def normalize_history_df(df: pd.DataFrame) -> pd.DataFrame:
    """Единый вид для потребителей: колонки timestamp, price, market_cap, volume."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["timestamp", "price", "market_cap", "volume"])
    out = df.copy()
    if "timestamp" not in out.columns:
        if isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index()
            if out.columns[0] != "timestamp":
                out = out.rename(columns={out.columns[0]: "timestamp"})
        else:
            return pd.DataFrame(columns=["timestamp", "price", "market_cap", "volume"])
    for col in ("price", "market_cap", "volume"):
        if col not in out.columns:
            out[col] = None
    ts = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out["timestamp"] = ts
    out = out.dropna(subset=["timestamp", "price"])
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out["market_cap"] = pd.to_numeric(out["market_cap"], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    return out[["timestamp", "price", "market_cap", "volume"]].sort_values("timestamp").reset_index(drop=True)


def _env_market_current_cache_ttl_sec() -> float:
    """plan01 §10: 5–15 мин (по умолчанию 600 с)."""
    raw = os.environ.get("MARKET_CURRENT_CACHE_TTL_SEC", "600").strip() or "600"
    try:
        v = float(raw)
    except ValueError:
        v = 600.0
    return max(300.0, min(900.0, v))


def _env_market_max_attempts() -> int:
    """Число попыток на один источник при транзиентных сбоях (plan01 §9)."""
    raw = os.environ.get("MARKET_SOURCE_MAX_ATTEMPTS", "3").strip() or "3"
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(8, n))


def _env_market_retry_base_sec() -> float:
    raw = os.environ.get("MARKET_SOURCE_RETRY_BASE_SEC", "0.35").strip() or "0.35"
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.35


def _env_market_cb_enabled() -> bool:
    return os.environ.get("MARKET_CIRCUIT_BREAKER", "").strip().lower() in ("1", "true", "yes", "on")


def _env_market_cb_failures() -> int:
    raw = os.environ.get("MARKET_CB_FAILURE_THRESHOLD", "5").strip() or "5"
    try:
        return max(2, int(raw))
    except ValueError:
        return 5


def _env_market_cb_open_sec() -> float:
    raw = os.environ.get("MARKET_CB_OPEN_SEC", "60").strip() or "60"
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 60.0


def _is_transient_market_error(exc: BaseException) -> bool:
    """Ретраим сетевые/5xx-сценарии; без токена и явный мусор — сразу к следующему источнику."""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    try:
        import requests

        if isinstance(exc, requests.RequestException):
            return True
    except ImportError:
        pass
    if isinstance(exc, ValueError):
        s = str(exc)
        if "FREECRYPTO_API_TOKEN" in s or "CMC_API_KEY" in s:
            return False
        if "не задан" in s:
            return False
        if any(x in s for x in ("HTTP 5", "HTTP 502", "HTTP 503", "HTTP 504")):
            return True
        if "timeout" in s.lower() or "timed out" in s.lower():
            return True
    return False


def clear_market_current_cache() -> None:
    """Сброс кэша §10 (тесты, принудительное обновление)."""
    with _cache_lock:
        _market_current_cache.clear()


def clear_market_circuit_breaker_state() -> None:
    """Сброс circuit breaker (тесты)."""
    with _cb_lock:
        _cb_fail_streak.clear()
        _cb_open_until.clear()


def _circuit_is_open(name: str) -> bool:
    if not _env_market_cb_enabled():
        return False
    with _cb_lock:
        until = _cb_open_until.get(name, 0.0)
    return time.monotonic() < until


def _circuit_record_success(name: str) -> None:
    if not _env_market_cb_enabled():
        return
    with _cb_lock:
        _cb_fail_streak[name] = 0
        _cb_open_until.pop(name, None)


def _circuit_record_failure(name: str) -> None:
    if not _env_market_cb_enabled():
        return
    thr = _env_market_cb_failures()
    open_sec = _env_market_cb_open_sec()
    with _cb_lock:
        n = _cb_fail_streak.get(name, 0) + 1
        _cb_fail_streak[name] = n
        if n >= thr:
            _cb_open_until[name] = time.monotonic() + open_sec
            logger.warning(
                "Market circuit breaker: «%s» отключён на %.0f с после %s ошибок (plan01 §9)",
                name,
                open_sec,
                n,
            )


def _try_source_current(name: str, src: MarketDataSource, symbol: str) -> Optional[Dict[str, Any]]:
    """Несколько попыток на источник при транзиентных ошибках; битые по sanity — без ретраев."""
    max_attempts = _env_market_max_attempts()
    base = _env_market_retry_base_sec()
    last_err: Optional[BaseException] = None
    attempt = 0
    while attempt < max_attempts:
        try:
            row = dict(src.get_current(symbol))
            row.setdefault("source", name)
            strict = name != "binance"
            if sanity_check_market_row(row, require_market_cap=strict):
                _circuit_record_success(name)
                return row
            if name == "binance" and sanity_check_market_row(row, require_market_cap=False):
                _circuit_record_success(name)
                return row
            return None
        except Exception as e:
            last_err = e
            logger.debug("market current %s попытка %s/%s: %s", name, attempt + 1, max_attempts, e)
            attempt += 1
            if attempt >= max_attempts or not _is_transient_market_error(e):
                break
            delay = min(8.0, base * (2 ** (attempt - 1)) + random.uniform(0, 0.12))
            if delay > 0:
                time.sleep(delay)
    if last_err is not None and _is_transient_market_error(last_err):
        _circuit_record_failure(name)
    return None


def _env_market_chain() -> List[str]:
    raw = os.environ.get("MARKET_DATA_PRIMARY", "cmc").strip() or "cmc"
    fall = os.environ.get("MARKET_DATA_FALLBACK", "binance,coingecko").strip()
    parts = [raw] + [p.strip() for p in fall.split(",") if p.strip()]
    seen: set[str] = set()
    out: List[str] = []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _source_cls_map() -> Dict[str, Type[MarketDataSource]]:
    from .freecrypto import FreeCryptoDataSource
    from .market_binance import BinanceMarketDataSource
    from .market_coingecko import CoinGeckoMarketDataSource
    from .market_coinmarketcap import CoinMarketCapDataSource

    return {
        "cmc": CoinMarketCapDataSource,
        "coinmarketcap": CoinMarketCapDataSource,
        "freecrypto": FreeCryptoDataSource,
        "binance": BinanceMarketDataSource,
        "coingecko": CoinGeckoMarketDataSource,
    }


def get_market_source_chain(
    *,
    names: Optional[Sequence[str]] = None,
) -> List[Tuple[str, MarketDataSource]]:
    """
    plan01 §8: фабрика цепочки primary + fallback для DI и тестов.

    По умолчанию порядок из MARKET_DATA_PRIMARY и MARKET_DATA_FALLBACK;
    при передаче `names` — только эти ключи (как в _source_cls_map).
    """
    chain = [n.lower() for n in names] if names is not None else _env_market_chain()
    classes = _source_cls_map()
    out: List[Tuple[str, MarketDataSource]] = []
    for name in chain:
        cls = classes.get(name)
        if cls is not None:
            out.append((name, cls()))
    return out


def get_market_current_with_fallback(
    symbol: str = "BTC",
    *,
    use_cache: bool = True,
    granularity: str = "live",
    endpoint_kind: str = "current",
) -> Optional[Dict[str, Any]]:
    """
    Цепочка primary + fallback (plan01 §9): ретраи с backoff на транзиентных сбоях, опциональный
    circuit breaker (`MARKET_CIRCUIT_BREAKER`); горячий путь — TTL-кэш (plan01 §10).

    Ключ кэша: (symbol, granularity, endpoint_kind). Для записи снимка в БД вызывайте с
    ``use_cache=False``.
    """
    sym_u = symbol.strip().upper()
    cache_key = (sym_u, granularity, endpoint_kind)
    if use_cache:
        ttl_sec = _env_market_current_cache_ttl_sec()
        with _cache_lock:
            hit = _market_current_cache.get(cache_key)
            if hit is not None:
                exp_mono, row = hit
                if time.monotonic() < exp_mono:
                    return dict(row)
                del _market_current_cache[cache_key]

    chain_pairs = get_market_source_chain()
    if not chain_pairs:
        return None
    last_problem: Optional[str] = None
    for name, src in chain_pairs:
        if _circuit_is_open(name):
            logger.debug("market current: circuit open, пропуск %s", name)
            continue
        row = _try_source_current(name, src, sym_u)
        if row:
            if use_cache:
                with _cache_lock:
                    _market_current_cache[cache_key] = (
                        time.monotonic() + _env_market_current_cache_ttl_sec(),
                        dict(row),
                    )
            return row
        last_problem = name
    logger.warning(
        "Все источники market current исчерпаны для %s (последний шаг: %s)",
        sym_u,
        last_problem,
    )
    return None


def build_market_history(
    symbol: str,
    days: int,
    *,
    primary: Optional[str] = None,
) -> pd.DataFrame:
    """
    Гибрид plan01 §4.1: (A) история с API primary, (B) досбор из SQLite market_data (снимки collect_daily_snapshot).

    Пустой/короткий ответ API не блокирует ряд — локальные снимки заполняют окно. При совпадении timestamp
    предпочтение строке API (провайдер), затем снимок.
    """
    primary = (primary or os.environ.get("MARKET_DATA_PRIMARY", "cmc") or "cmc").lower()
    classes = _source_cls_map()
    cls = classes.get(primary) or classes["cmc"]
    api_df = normalize_history_df(cls().get_history(symbol, days))
    window_end = pd.Timestamp.now(tz="UTC")
    window_start = window_end - pd.Timedelta(days=max(1, int(days)))
    try:
        from .storage import load_market_data_history

        db_df = load_market_data_history(symbol, since_iso=window_start.isoformat())
        db_df = normalize_history_df(db_df)
        if api_df.empty and db_df.empty:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("build_market_history: нет ни API, ни БД за %s дн. (%s)", days, symbol)
            merged = normalize_history_df(pd.DataFrame())
        elif api_df.empty:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("build_market_history: только снимки БД (§4.1 B) для %s", symbol)
            merged = db_df
        elif db_df.empty:
            merged = api_df
        else:
            # db первым, api вторым → keep='last' отдаёт приоритет API
            merged = pd.concat([db_df, api_df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["timestamp"], keep="last")
            merged = merged.sort_values("timestamp").reset_index(drop=True)
        merged = merged[(merged["timestamp"] >= window_start) & (merged["timestamp"] <= window_end)]
        return merged.sort_values("timestamp").reset_index(drop=True)
    except Exception as e:
        logger.debug("build_market_history DB merge: %s", e)
        out = normalize_history_df(api_df)
        out = out[(out["timestamp"] >= window_start) & (out["timestamp"] <= window_end)]
        return out.sort_values("timestamp").reset_index(drop=True)


def iter_market_sources_for_tests() -> Sequence[str]:
    """Имена провайдеров для тестов/реестра."""
    return tuple(_source_cls_map().keys())


def collect_daily_snapshot(
    symbol: str = "BTC",
    *,
    min_interval_hours: Optional[float] = None,
) -> bool:
    """
    plan01 §4.1 B: снять get_current (цепочка fallback) и записать в market_data.

    Расписание: планировщик Windows / cron — минимум 1 раз в день; при чаще задайте min_interval_hours
    (например 20), чтобы не плодить строки с разными секундами в одном дне.
    """
    from .storage import get_last_market_snapshot_time, save_market_snapshot

    if min_interval_hours is not None and float(min_interval_hours) > 0:
        last = get_last_market_snapshot_time(symbol)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            else:
                last = last.astimezone(timezone.utc)
            age = datetime.now(timezone.utc) - last
            if age.total_seconds() < float(min_interval_hours) * 3600:
                return True
    row = get_market_current_with_fallback(symbol, use_cache=False)
    if not row:
        return False
    return save_market_snapshot(row)
