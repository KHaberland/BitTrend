"""Персистентная история сигналов (P1): SQLite + опциональный CSV."""

import csv

import pytest

from bit_trend.data import storage as storage_mod


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    db = tmp_path / "test_bittrend.db"
    monkeypatch.setattr(storage_mod, "DB_PATH", db)
    storage_mod.init_db()
    yield db


def test_append_and_get_signal_history(isolated_db):
    assert storage_mod.get_signal_history(10) == []
    ok = storage_mod.append_signal_history(
        score=12.5,
        signal="HOLD",
        btc_price=100_000.0,
        usdt=4000.0,
        btc_amount=0.05,
        deviation_usdt=100.0,
        recommendation="SIGNAL: HOLD / ...",
        dedupe_within_seconds=0,
    )
    assert ok is True
    rows = storage_mod.get_signal_history(10)
    assert len(rows) == 1
    assert rows[0]["score"] == 12.5
    assert rows[0]["signal"] == "HOLD"
    assert rows[0]["btc_price"] == 100_000.0
    assert rows[0]["deviation_usdt"] == 100.0
    assert "timestamp" in rows[0]


def test_dedupe_skips_second_row(isolated_db):
    storage_mod.append_signal_history(
        score=10.0,
        signal="BUY",
        btc_price=50_000.0,
        usdt=1000.0,
        btc_amount=0.01,
        deviation_usdt=0.0,
        recommendation="r1",
        dedupe_within_seconds=3600,
    )
    ok2 = storage_mod.append_signal_history(
        score=10.0,
        signal="BUY",
        btc_price=50_000.0,
        usdt=1000.0,
        btc_amount=0.01,
        deviation_usdt=0.0,
        recommendation="r2",
        dedupe_within_seconds=3600,
    )
    assert ok2 is False
    assert len(storage_mod.get_signal_history(20)) == 1


def test_csv_mirror(monkeypatch, isolated_db, tmp_path):
    csv_path = tmp_path / "signals.csv"
    monkeypatch.setenv("BITTREND_SIGNAL_CSV_PATH", str(csv_path))
    storage_mod.append_signal_history(
        score=1.0,
        signal="EXIT",
        btc_price=1.0,
        usdt=1.0,
        btc_amount=0.0,
        deviation_usdt=0.0,
        recommendation="x",
        dedupe_within_seconds=0,
    )
    assert csv_path.exists()
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = list(csv.DictReader(f))
    assert len(r) == 1
    assert r[0]["signal"] == "EXIT"


def test_dedupe_disabled_with_zero(isolated_db):
    kwargs = dict(
        score=5.0,
        signal="HOLD",
        btc_price=1.0,
        usdt=1.0,
        btc_amount=1.0,
        deviation_usdt=0.0,
        recommendation="a",
    )
    assert storage_mod.append_signal_history(dedupe_within_seconds=0, **kwargs) is True
    assert storage_mod.append_signal_history(dedupe_within_seconds=0, **kwargs) is True
    assert len(storage_mod.get_signal_history(10)) == 2
