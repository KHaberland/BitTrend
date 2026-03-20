"""plan01: MarketDataSource, FreeCrypto парсинг, цепочка fallback, market_data SQLite."""

from __future__ import annotations

import importlib
import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from bit_trend.data.freecrypto import _history_json_to_df, normalize_freecrypto_dict
from bit_trend.data.market_coingecko import CoinGeckoDataSource
from bit_trend.data.market_binance import BinanceDataSource
from bit_trend.data.coinmarketcap_history import sync_btc_from_cmc
from bit_trend.data.market_coinmarketcap import CoinMarketCapDataSource, _ohlcv_body_to_df, _parse_quotes_latest
from bit_trend.data.market_source import (
    MarketDataSource,
    build_market_history,
    clear_market_circuit_breaker_state,
    clear_market_current_cache,
    collect_daily_snapshot,
    get_market_current_with_fallback,
    get_market_source_chain,
    normalize_history_df,
    sanity_check_market_row,
)


@pytest.fixture(autouse=True)
def _reset_market_hot_path() -> None:
    clear_market_current_cache()
    clear_market_circuit_breaker_state()
    yield


def test_plan01_market_data_source_subclasses_and_factory():
    assert issubclass(CoinGeckoDataSource, MarketDataSource)
    assert issubclass(BinanceDataSource, MarketDataSource)
    assert issubclass(CoinMarketCapDataSource, MarketDataSource)
    chain = get_market_source_chain(names=("binance", "coingecko"))
    assert [n for n, _ in chain] == ["binance", "coingecko"]
    assert all(isinstance(src, MarketDataSource) for _, src in chain)


def test_cmc_registry_alias_coinmarketcap():
    c1 = get_market_source_chain(names=("cmc",))
    c2 = get_market_source_chain(names=("coinmarketcap",))
    assert [n for n, _ in c1] == ["cmc"]
    assert [n for n, _ in c2] == ["coinmarketcap"]
    assert isinstance(c1[0][1], CoinMarketCapDataSource)
    assert isinstance(c2[0][1], CoinMarketCapDataSource)


def test_cmc_parse_quotes_latest_body():
    body = {
        "status": {"error_code": 0, "error_message": None},
        "data": {
            "BTC": {
                "symbol": "BTC",
                "last_updated": "2025-01-15T12:00:00.000Z",
                "quote": {
                    "USD": {
                        "price": 99500.12,
                        "volume_24h": 2.5e10,
                        "market_cap": 1.95e12,
                    }
                },
            }
        },
    }
    row = _parse_quotes_latest(body, "BTC")
    assert row is not None
    assert row["price"] == 99500.12
    assert row["market_cap"] == 1.95e12
    assert row["volume"] == 2.5e10


def test_cmc_parse_ohlcv_historical_body():
    body = {
        "status": {"error_code": 0},
        "data": {
            "symbol": "BTC",
            "quotes": [
                {
                    "time_close": "2025-01-01T23:59:59.999Z",
                    "quote": {
                        "USD": {
                            "close": 94000.0,
                            "market_cap": 1.8e12,
                            "volume": 1.2e10,
                        }
                    },
                }
            ],
        },
    }
    df = _ohlcv_body_to_df(body)
    assert len(df) == 1
    assert df["price"].iloc[0] == 94000.0
    assert df["market_cap"].iloc[0] == 1.8e12


def test_sanity_check_plan01():
    assert sanity_check_market_row(
        {"price": 67000, "market_cap": 1.3e12, "volume": 2.5e10}, require_market_cap=True
    )
    assert not sanity_check_market_row({"price": 0, "market_cap": 1.0, "volume": 1.0})
    assert not sanity_check_market_row({"price": -100.0, "market_cap": 1.0, "volume": 1.0})
    assert not sanity_check_market_row({"price": 1.0, "market_cap": None, "volume": 1.0}, require_market_cap=True)
    assert sanity_check_market_row({"price": 1.0, "market_cap": None, "volume": 1.0}, require_market_cap=False)
    assert not sanity_check_market_row({"price": 1.0, "market_cap": 1.0, "volume": -1.0})


def test_normalize_freecrypto_flat_json():
    d = normalize_freecrypto_dict(
        {
            "symbol": "BTC",
            "price": 67000,
            "market_cap": 1_300_000_000_000,
            "volume_24h": 25_000_000_000,
            "timestamp": 1_710_000_000,
        }
    )
    assert d["symbol"] == "BTC"
    assert d["price"] == 67000
    assert d["market_cap"] == 1_300_000_000_000
    assert d["volume"] == 25_000_000_000


def test_freecrypto_get_data_symbols_format():
    """Актуальный JSON getData: status success + symbols[]."""
    from bit_trend.data import freecrypto as fc

    body = {
        "status": "success",
        "symbols": [
            {
                "symbol": "BTC",
                "last": "70158.21",
                "source_exchange": "binance",
                "date": "2026-03-20 12:00:00",
            }
        ],
    }
    row = fc._row_from_get_data_body(body, "BTC")
    assert row is not None
    assert row.get("last") == "70158.21"
    out = fc._normalize_current_row(row, "BTC")
    assert out["price"] == 70158.21
    assert out["market_cap"] is not None and out["market_cap"] > 0


def test_normalize_freecrypto_wrapped_data_key():
    d = normalize_freecrypto_dict(
        {
            "status": True,
            "data": {
                "symbol": "BTC",
                "price": "50000",
                "market_cap": 1e12,
                "volume": 1e9,
            },
        }
    )
    assert d["price"] == 50000.0


def test_history_json_list_of_tuples_fixed():
    df = _history_json_to_df(
        {"status": True, "data": [[1609459200000, 29000.0, 5e11, 1e10]]},
        "BTC",
    )
    assert len(df) == 1
    assert df["price"].iloc[0] == 29000.0


def test_history_json_list_of_dicts_maps_volume_24h():
    """§11.1: маппинг полей истории (volume_24h → volume)."""
    df = _history_json_to_df(
        {
            "status": True,
            "data": [
                {
                    "timestamp": 1609459200000,
                    "price": 29000.0,
                    "market_cap": 5e11,
                    "volume_24h": 1.1e10,
                }
            ],
        },
        "BTC",
    )
    assert len(df) == 1
    assert df["volume"].iloc[0] == 1.1e10
    assert df["market_cap"].iloc[0] == 5e11


def test_history_json_unix_seconds_not_milliseconds():
    """API в unix seconds: не терять ряд из-за неверного unit=ms."""
    df = _history_json_to_df(
        {"status": True, "data": [[1609459200, 29000.0, 5e11, 1e10]]},
        "BTC",
    )
    assert len(df) == 1
    assert df["price"].iloc[0] == 29000.0
    year = pd.Timestamp(df["timestamp"].iloc[0]).year
    assert year == 2021


def test_normalize_history_df_empty():
    out = normalize_history_df(pd.DataFrame())
    assert list(out.columns) == ["timestamp", "price", "market_cap", "volume"]
    assert len(out) == 0


@patch("bit_trend.data.market_binance.http_get")
@patch("bit_trend.data.freecrypto.http_get")
def test_fallback_to_binance_when_freecrypto_http_503(mock_get_fc, mock_get_bn, monkeypatch):
    """§11.2: primary отдаёт 5xx — после ретраев выбирается Binance."""
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "freecrypto")
    monkeypatch.setenv("MARKET_DATA_FALLBACK", "binance")
    monkeypatch.setenv("FREECRYPTO_API_TOKEN", "dummy")
    monkeypatch.setenv("MARKET_SOURCE_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("MARKET_SOURCE_RETRY_BASE_SEC", "0")

    mock_bad = MagicMock()
    mock_bad.ok = False
    mock_bad.status_code = 503
    mock_get_fc.return_value = mock_bad

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={"lastPrice": "88001.12", "quoteVolume": "1000000.0"}
    )
    mock_get_bn.return_value = mock_resp

    row = get_market_current_with_fallback("BTC")
    assert row is not None
    assert row["source"] == "binance"
    assert abs(row["price"] - 88001.12) < 1e-6


@patch("bit_trend.data.market_binance.http_get")
def test_fallback_to_binance_when_cmc_no_key(mock_get, monkeypatch):
    monkeypatch.delenv("CMC_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "cmc")
    monkeypatch.setenv("MARKET_DATA_FALLBACK", "binance")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={"lastPrice": "95123.45", "quoteVolume": "1234567890.0"}
    )
    mock_get.return_value = mock_resp

    row = get_market_current_with_fallback("BTC")
    assert row is not None
    assert row["source"] == "binance"
    assert abs(row["price"] - 95123.45) < 1e-6


@patch("bit_trend.data.market_binance.http_get")
def test_fallback_to_binance_when_freecrypto_no_token(mock_get, monkeypatch):
    monkeypatch.delenv("FREECRYPTO_API_TOKEN", raising=False)
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "freecrypto")
    monkeypatch.setenv("MARKET_DATA_FALLBACK", "binance")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(
        return_value={"lastPrice": "95123.45", "quoteVolume": "1234567890.0"}
    )
    mock_get.return_value = mock_resp

    row = get_market_current_with_fallback("BTC")
    assert row is not None
    assert row["source"] == "binance"
    assert abs(row["price"] - 95123.45) < 1e-6


def test_market_data_migration_composite_pk_to_plan01(tmp_path, monkeypatch):
    """Старый PRIMARY KEY (timestamp, symbol) → plan01 §5 (только timestamp)."""
    db = tmp_path / "legacy_market.db"
    raw = sqlite3.connect(str(db))
    raw.executescript(
        """
        CREATE TABLE market_data (
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'BTC',
            price REAL NOT NULL,
            market_cap REAL,
            volume REAL,
            source TEXT,
            PRIMARY KEY (timestamp, symbol)
        );
        INSERT INTO market_data (timestamp, symbol, price, market_cap, volume, source)
        VALUES ('2020-01-01T00:00:00+00:00', 'BTC', 7000.0, 1e11, 1e9, 'legacy');
        """
    )
    raw.close()

    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)
    st.init_db()

    verify = sqlite3.connect(str(db))
    try:
        cols = verify.execute("PRAGMA table_info(market_data)").fetchall()
        pk_names = [r[1] for r in sorted((r for r in cols if r[5] > 0), key=lambda r: r[5])]
        assert pk_names == ["timestamp"]
        one = verify.execute(
            "SELECT price, source FROM market_data WHERE symbol = 'BTC'"
        ).fetchone()
        assert one[0] == 7000.0
        assert one[1] == "legacy"
    finally:
        verify.close()


def test_market_storage_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    ok_bad = st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 100.0,
            "market_cap": 0,
            "volume": 1.0,
            "timestamp": "2024-01-15T12:00:00+00:00",
            "source": "test",
        }
    )
    assert not ok_bad

    ok = st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 70000,
            "market_cap": 1.4e12,
            "volume": 3e10,
            "timestamp": "2024-01-15T12:00:00+00:00",
            "source": "test",
        }
    )
    assert ok
    df = st.load_market_data_history("BTC", "2024-01-01T00:00:00+00:00")
    assert len(df) == 1
    assert df["price"].iloc[0] == 70000


def test_save_market_rows_batch(tmp_path, monkeypatch):
    """plan_change §3: батч CMC-подобных строк, source=coinmarketcap."""
    db = tmp_path / "batch.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)
    n = st.save_market_rows(
        [
            {
                "timestamp": "2024-01-10T00:00:00+00:00",
                "price": 40000.0,
                "market_cap": 8e11,
                "volume": 1e10,
            },
            {"timestamp": "2024-01-11T00:00:00+00:00", "price": 0.0, "market_cap": 8e11, "volume": 0},
        ],
        symbol="BTC",
        source="coinmarketcap",
    )
    assert n == 1
    df = st.load_market_data_history("BTC", "2024-01-01T00:00:00+00:00")
    assert len(df) == 1
    assert float(df["price"].iloc[0]) == 40000.0


def test_save_market_snapshot_binance_without_cap_allowed(tmp_path, monkeypatch):
    """plan01 §7.2: для binance market_cap может отсутствовать."""
    db = tmp_path / "bn.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)
    assert st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 50000.0,
            "market_cap": None,
            "volume": 1e9,
            "timestamp": "2024-06-01T00:00:00+00:00",
            "source": "binance",
        }
    )


def test_sync_btc_from_cmc_requires_api_key(monkeypatch):
    monkeypatch.delenv("CMC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="CMC_API_KEY"):
        sync_btc_from_cmc(days_back=30)


@patch("bit_trend.data.cmc_market_import.CoinMarketCapDataSource.get_history")
def test_sync_btc_from_cmc_writes_market_data(mock_hist, tmp_path, monkeypatch):
    """plan_change §6.5–6.6: бэкфилл через save_market_rows, source=coinmarketcap."""
    monkeypatch.setenv("CMC_API_KEY", "dummy-key-for-test")
    db = tmp_path / "cmc_sync.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    mock_hist.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-03-01T00:00:00+00:00"], utc=True),
            "price": [62000.0],
            "market_cap": [1.2e12],
            "volume": [1.5e10],
        }
    )
    n = sync_btc_from_cmc(days_back=90)
    assert n == 1
    df = st.load_market_data_history("BTC", "2024-01-01T00:00:00+00:00")
    assert len(df) == 1
    assert float(df["price"].iloc[0]) == 62000.0


@patch("bit_trend.data.market_coinmarketcap.CoinMarketCapDataSource.get_history")
def test_build_market_history_cmc_primary_merges_db(mock_hist, tmp_path, monkeypatch):
    """plan_change §6.10: build_market_history при MARKET_DATA_PRIMARY=cmc."""
    db = tmp_path / "cmc_merge.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "cmc")
    monkeypatch.setenv("CMC_API_KEY", "dummy")
    import bit_trend.data.storage as st

    importlib.reload(st)

    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 60000,
            "market_cap": 1.2e12,
            "volume": 1e10,
            "timestamp": "2025-01-01T00:00:00+00:00",
            "source": "snapshot",
        }
    )
    mock_hist.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2025-06-01T00:00:00+00:00"], utc=True),
            "price": [70000.0],
            "market_cap": [1.3e12],
            "volume": [2e10],
        }
    )
    merged = build_market_history("BTC", 500)
    assert len(merged) == 2
    assert merged["price"].min() == 60000
    assert merged["price"].max() == 70000


@patch("bit_trend.data.freecrypto.FreeCryptoDataSource.get_history")
def test_build_market_history_merges_db(mock_hist, tmp_path, monkeypatch):
    db = tmp_path / "merge.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 60000,
            "market_cap": 1.2e12,
            "volume": 1e10,
            "timestamp": "2025-01-01T00:00:00+00:00",
            "source": "snapshot",
        }
    )
    api_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2025-06-01T00:00:00+00:00"], utc=True),
            "price": [70000.0],
            "market_cap": [1.3e12],
            "volume": [2e10],
        }
    )
    mock_hist.return_value = api_df
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "freecrypto")
    monkeypatch.setenv("FREECRYPTO_API_TOKEN", "dummy")

    merged = build_market_history("BTC", 500)
    assert len(merged) == 2
    assert merged["price"].min() == 60000
    assert merged["price"].max() == 70000


@patch("bit_trend.data.freecrypto.FreeCryptoDataSource.get_history")
def test_build_market_history_api_empty_uses_db_only(mock_hist, tmp_path, monkeypatch):
    db = tmp_path / "onlydb.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 61000,
            "market_cap": 1.2e12,
            "volume": 1e10,
            "timestamp": "2025-06-10T00:00:00+00:00",
            "source": "snapshot",
        }
    )
    mock_hist.return_value = pd.DataFrame()
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "freecrypto")
    monkeypatch.setenv("FREECRYPTO_API_TOKEN", "dummy")

    merged = build_market_history("BTC", 400)
    assert len(merged) == 1
    assert merged["price"].iloc[0] == 61000


@patch("bit_trend.data.freecrypto.FreeCryptoDataSource.get_history")
def test_build_market_history_clips_to_window(mock_hist, tmp_path, monkeypatch):
    """Строки старше запрошенного окна не попадают в результат (§4 окно days)."""
    now = pd.Timestamp.now(tz="UTC")
    old_ts = (now - pd.Timedelta(days=200)).isoformat()
    recent_ts = (now - pd.Timedelta(days=10)).isoformat()

    db = tmp_path / "clip.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 10000.0,
            "market_cap": 1e12,
            "volume": 1e10,
            "timestamp": old_ts,
            "source": "old",
        }
    )
    mock_hist.return_value = pd.DataFrame(
        {
            "timestamp": pd.to_datetime([recent_ts], utc=True),
            "price": [70000.0],
            "market_cap": [1.3e12],
            "volume": [2e10],
        }
    )
    monkeypatch.setenv("MARKET_DATA_PRIMARY", "freecrypto")
    monkeypatch.setenv("FREECRYPTO_API_TOKEN", "dummy")

    merged = build_market_history("BTC", 90)
    assert len(merged) == 1
    assert merged["price"].iloc[0] == 70000.0


@patch("bit_trend.data.market_source.get_market_current_with_fallback")
def test_collect_daily_snapshot_min_interval_skips_fetch(mock_fallback, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    db = tmp_path / "snap.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 50000,
            "market_cap": 1e12,
            "volume": 1e10,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "x",
        }
    )
    mock_fallback.side_effect = RuntimeError("не должны вызывать API")

    assert collect_daily_snapshot("BTC", min_interval_hours=24) is True
    assert mock_fallback.call_count == 0


def test_market_current_ttl_cache_single_fetch(monkeypatch):
    """plan01 §10: второй выбор из кэша без повторного get_current."""
    monkeypatch.setenv("MARKET_CURRENT_CACHE_TTL_SEC", "600")
    calls = {"n": 0}

    class Fake(MarketDataSource):
        def get_current(self, symbol):
            calls["n"] += 1
            return {
                "symbol": "BTC",
                "price": 1.0,
                "market_cap": 2.0,
                "volume": 3.0,
                "timestamp": 1,
                "source": "fake",
            }

        def get_history(self, symbol, days):
            return pd.DataFrame()

    with patch(
        "bit_trend.data.market_source.get_market_source_chain", lambda: [("xfc", Fake())]
    ):
        clear_market_current_cache()
        r1 = get_market_current_with_fallback("BTC")
        r2 = get_market_current_with_fallback("BTC")
        r3 = get_market_current_with_fallback("BTC", use_cache=False)
    assert r1["price"] == 1.0
    assert r2["price"] == 1.0
    assert calls["n"] == 2
    assert r3 is not None


def test_market_current_retries_transient_then_ok(monkeypatch):
    """plan01 §9: backoff между попытками одного источника при транзиентной ошибке."""
    monkeypatch.setenv("MARKET_SOURCE_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("MARKET_SOURCE_RETRY_BASE_SEC", "0")
    calls = {"n": 0}

    class Flaky(MarketDataSource):
        def get_current(self, symbol):
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("net down")
            return {
                "symbol": "BTC",
                "price": 50000.0,
                "market_cap": 1e12,
                "volume": 1e9,
                "timestamp": 1,
            }

        def get_history(self, symbol, days):
            return pd.DataFrame()

    with patch(
        "bit_trend.data.market_source.get_market_source_chain", lambda: [("flaky", Flaky())]
    ):
        row = get_market_current_with_fallback("btc")
    assert row is not None
    assert row["source"] == "flaky"
    assert row["price"] == 50000.0
    assert calls["n"] == 2


def test_get_last_market_snapshot_time(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("BITTREND_DB_PATH", str(db))
    import bit_trend.data.storage as st

    importlib.reload(st)

    assert st.get_last_market_snapshot_time("BTC") is None
    st.save_market_snapshot(
        {
            "symbol": "BTC",
            "price": 1,
            "market_cap": 1,
            "volume": 0,
            "timestamp": "2030-05-01T12:00:00+00:00",
            "source": "t",
        }
    )
    last = st.get_last_market_snapshot_time("BTC")
    assert last is not None
    assert last.year == 2030
    assert last.month == 5
