"""
FreeCryptoAPI — текущие котировки и история (plan01 §3).
Требуется FREECRYPTO_API_TOKEN (query `token`); см. https://freecryptoapi.com/documentation
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .http_client import http_get
from .market_source import MarketDataSource, normalize_history_df

# plan01 §6: маппинг полей ответа API → ключи в системе и колонки market_data
FREECRYPTO_FIELD_MAP: Tuple[Tuple[str, str], ...] = (
    ("price", "price"),
    ("market_cap", "market_cap"),
    ("volume_24h", "volume"),
)

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.freecryptoapi.com/v1"


class FreeCryptoDataSource(MarketDataSource):
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: int = 20,
    ) -> None:
        self.base_url = (base_url or os.environ.get("FREECRYPTO_API_BASE", DEFAULT_BASE)).rstrip("/")
        self.api_token = (api_token if api_token is not None else os.environ.get("FREECRYPTO_API_TOKEN", "")).strip()
        self.timeout = timeout

    def get_current(self, symbol: str) -> Dict[str, Any]:
        if not self.api_token:
            raise ValueError("FREECRYPTO_API_TOKEN не задан")
        sym = symbol.strip().upper()
        url = f"{self.base_url}/getData"
        r = http_get(url, params={"token": self.api_token, "symbol": sym}, timeout=self.timeout)
        if not r.ok:
            raise ValueError(f"FreeCryptoAPI getData HTTP {r.status_code}")
        body = r.json()
        row = _unwrap_payload(body)
        if row is None:
            err = body.get("error") if isinstance(body, dict) else None
            raise ValueError(err or "FreeCryptoAPI: пустой ответ")
        out = _normalize_current_row(row, sym)
        out["source"] = "freecrypto"
        return out

    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        """
        Вариант A plan01 §4.1: история с API (`/getHistory`), если провайдер отдаёт ряд.

        Неполный ряд или пустой ответ — норма; полный гибрид с локальными снимками — `build_market_history`.
        """
        if not self.api_token:
            return normalize_history_df(pd.DataFrame())
        sym = symbol.strip().upper()
        d = max(1, min(int(days), 3650))
        url = f"{self.base_url}/getHistory"
        try:
            r = http_get(
                url,
                params={"token": self.api_token, "symbol": sym, "days": d},
                timeout=self.timeout,
            )
            if not r.ok:
                logger.debug("FreeCrypto getHistory HTTP %s", r.status_code)
                return normalize_history_df(pd.DataFrame())
            body = r.json()
            df = _history_json_to_df(body, sym)
            return normalize_history_df(df)
        except Exception as e:
            logger.debug("FreeCrypto getHistory: %s", e)
            return normalize_history_df(pd.DataFrame())


def _unwrap_payload(body: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(body, dict):
        return None
    if body.get("status") is False:
        return None
    for key in ("data", "result", "payload"):
        inner = body.get(key)
        if isinstance(inner, dict):
            return inner
    if "price" in body or "symbol" in body:
        return body
    return None


def _normalize_current_row(raw: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    price: Optional[float] = None
    cap: Optional[float] = None
    vol: Optional[float] = None
    for api_key, internal in FREECRYPTO_FIELD_MAP:
        val = _to_float(raw.get(api_key))
        if val is not None:
            if internal == "price":
                price = val
            elif internal == "market_cap":
                cap = val
            elif internal == "volume":
                vol = val
    if vol is None:
        vol = _to_float(raw.get("volume"))
    ts = raw.get("timestamp")
    if ts is None:
        ts = int(time.time())
    elif isinstance(ts, float):
        ts = int(ts)
    sym = str(raw.get("symbol", symbol)).upper()
    out: Dict[str, Any] = {
        "symbol": sym,
        "price": price,
        "market_cap": cap,
        "volume": vol if vol is not None else 0.0,
        "timestamp": ts,
    }
    return out


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _history_json_to_df(body: Any, symbol: str) -> pd.DataFrame:
    """Разбор ответа getHistory (допускаем несколько распространённых схем)."""
    if not isinstance(body, dict) or body.get("status") is False:
        return pd.DataFrame()
    series: Any = None
    for key in ("data", "result", "history", "items"):
        if isinstance(body.get(key), list):
            series = body[key]
            break
    if series is None and isinstance(body.get("data"), dict):
        inner = body["data"]
        for key in ("history", "candles", "points"):
            if isinstance(inner.get(key), list):
                series = inner[key]
                break
    if not isinstance(series, list) or not series:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for item in series:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            ts_raw, price = item[0], item[1]
            cap = item[2] if len(item) > 2 else None
            vol = item[3] if len(item) > 3 else None
            rows.append({"timestamp": ts_raw, "price": price, "market_cap": cap, "volume": vol})
        elif isinstance(item, dict):
            ts_raw = item.get("timestamp") or item.get("time") or item.get("date") or item.get("t")
            price = item.get("price") or item.get("close") or item.get("c")
            rows.append(
                {
                    "timestamp": ts_raw,
                    "price": price,
                    "market_cap": item.get("market_cap"),
                    "volume": item.get("volume") or item.get("volume_24h"),
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce").fillna(
        pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    )
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["timestamp", "price"])
    return df


def normalize_freecrypto_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = _unwrap_payload(payload) or payload
    if not isinstance(raw, dict):
        raise ValueError("invalid payload")
    sym = str(raw.get("symbol", "BTC")).upper()
    return _normalize_current_row(raw, sym)
