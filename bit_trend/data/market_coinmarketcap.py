"""
CoinMarketCap Pro API — текущие котировки (quotes/latest) и дневная история (ohlcv/historical).
См. plan_change.md; ключ: CMC_API_KEY, заголовок X-CMC_PRO_API_KEY.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from .http_client import http_get
from .market_source import MarketDataSource, normalize_history_df

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://pro-api.coinmarketcap.com/v1"


def _env_cmc_chunk_days() -> int:
    raw = os.environ.get("CMC_OHLCV_CHUNK_DAYS", "120").strip() or "120"
    try:
        n = int(raw)
    except ValueError:
        n = 120
    return max(30, min(365, n))


class CoinMarketCapDataSource(MarketDataSource):
    """Провайдер plan01: тот же контракт, что у FreeCrypto (get_current / get_history)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = (base_url or os.environ.get("CMC_API_BASE", DEFAULT_BASE)).rstrip("/")
        self.api_key = (api_key if api_key is not None else os.environ.get("CMC_API_KEY", "")).strip()
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "X-CMC_PRO_API_KEY": self.api_key,
            "Accept": "application/json",
        }

    def get_current(self, symbol: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("CMC_API_KEY не задан")
        sym = symbol.strip().upper()
        url = f"{self.base_url}/cryptocurrency/quotes/latest"
        r = http_get(
            url,
            headers=self._headers(),
            params={"symbol": sym, "convert": "USD"},
            timeout=self.timeout,
        )
        if not r.ok:
            raise ValueError(f"CoinMarketCap quotes/latest HTTP {r.status_code}")
        body = r.json()
        row = _parse_quotes_latest(body, sym)
        if row is None:
            raise ValueError(_cmc_error_message(body) or "CoinMarketCap: пустой ответ")
        row["source"] = "coinmarketcap"
        return row

    def get_history(self, symbol: str, days: int) -> pd.DataFrame:
        if not self.api_key:
            return normalize_history_df(pd.DataFrame())
        sym = symbol.strip().upper()
        d = max(1, min(int(days), 3650))
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=d)
        chunk = timedelta(days=_env_cmc_chunk_days())
        frames: List[pd.DataFrame] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + chunk, end)
            df = _fetch_ohlcv_historical(self, sym, cursor, chunk_end)
            if not df.empty:
                frames.append(df)
            cursor = chunk_end
        if not frames:
            return normalize_history_df(pd.DataFrame())
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["timestamp"], keep="last")
        return normalize_history_df(out)


def _cmc_error_message(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    st = body.get("status")
    if isinstance(st, dict):
        msg = st.get("error_message")
        if msg:
            return str(msg)
    return None


def _parse_quotes_latest(body: Any, symbol: str) -> Optional[Dict[str, Any]]:
    if not isinstance(body, dict):
        return None
    st = body.get("status")
    if isinstance(st, dict):
        code = st.get("error_code")
        if code not in (None, 0):
            return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    u = symbol.upper()
    coin = data.get(u)
    if coin is None:
        for k, v in data.items():
            if str(k).upper() == u and isinstance(v, dict):
                coin = v
                break
    if coin is None and len(data) == 1:
        only = next(iter(data.values()))
        if isinstance(only, dict):
            coin = only
    if not isinstance(coin, dict):
        return None
    quote = coin.get("quote")
    if not isinstance(quote, dict):
        return None
    usd = quote.get("USD")
    if not isinstance(usd, dict):
        return None
    price = usd.get("price")
    cap = usd.get("market_cap")
    if cap is None:
        cap = usd.get("fully_diluted_market_cap")
    vol = usd.get("volume_24h")
    if vol is None:
        vol = usd.get("volume_24h_reported") or usd.get("volume_7d") or usd.get("volume_30d")
    ts_raw = coin.get("last_updated")
    ts_unix = int(time.time())
    if isinstance(ts_raw, str) and ts_raw.strip():
        try:
            ts_unix = int(pd.Timestamp(ts_raw, tz="UTC").timestamp())
        except (ValueError, TypeError, OSError):
            pass
    sym_out = str(coin.get("symbol", symbol)).upper()
    return {
        "symbol": sym_out,
        "price": price,
        "market_cap": cap,
        "volume": vol if vol is not None else 0.0,
        "timestamp": ts_unix,
    }


def _ohlcv_body_to_df(body: Any) -> pd.DataFrame:
    if not isinstance(body, dict):
        return pd.DataFrame()
    st = body.get("status")
    if isinstance(st, dict):
        if st.get("error_code") not in (None, 0):
            return pd.DataFrame()
    data = body.get("data")
    if not isinstance(data, dict):
        return pd.DataFrame()
    quotes = data.get("quotes")
    if not isinstance(quotes, list) or not quotes:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for q in quotes:
        if not isinstance(q, dict):
            continue
        tclose = q.get("time_close")
        quote = q.get("quote")
        if not isinstance(quote, dict):
            continue
        usd = quote.get("USD")
        if not isinstance(usd, dict):
            continue
        close = usd.get("close")
        cap = usd.get("market_cap")
        vol = usd.get("volume") or usd.get("volume_24h")
        rows.append(
            {
                "timestamp": tclose,
                "price": close,
                "market_cap": cap,
                "volume": vol,
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["market_cap"] = pd.to_numeric(df["market_cap"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["timestamp", "price"])
    return df


def _fetch_ohlcv_historical(
    src: CoinMarketCapDataSource,
    sym: str,
    t_start: datetime,
    t_end: datetime,
) -> pd.DataFrame:
    url = f"{src.base_url}/cryptocurrency/ohlcv/historical"
    params: Dict[str, Any] = {
        "symbol": sym,
        "convert": "USD",
        "time_start": t_start.date().isoformat(),
        "time_end": t_end.date().isoformat(),
        "interval": "daily",
    }
    try:
        r = http_get(url, headers=src._headers(), params=params, timeout=src.timeout)
        if not r.ok:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("CMC ohlcv/historical HTTP %s: %s", r.status_code, (r.text or "")[:500])
            else:
                logger.debug("CMC ohlcv/historical HTTP %s", r.status_code)
            return pd.DataFrame()
        body = r.json()
        return _ohlcv_body_to_df(body)
    except Exception as e:
        logger.debug("CMC ohlcv/historical: %s", e)
        return pd.DataFrame()
