"""Тесты P3: MVP по умолчанию, условия live без реального ccxt."""

import os
from unittest import mock

from bit_trend.execution.ccxt_executor import (
    execute_rebalance_part,
    is_live_trading_enabled,
    live_trading_status_message,
)


def test_mvp_no_env():
    with mock.patch.dict(os.environ, {}, clear=True):
        assert is_live_trading_enabled() is False
    r = execute_rebalance_part(1, 100.0, 500.0, 99000.0, onchain_drift_any=False)
    assert r.mode == "mvp"
    assert r.ok is True
    assert "MVP" in r.message


def test_live_requires_ack():
    with mock.patch.dict(
        os.environ,
        {
            "BITTREND_LIVE_TRADING": "true",
            "BITTREND_LIVE_TRADING_ACK": "no",
            "BITTREND_CCXT_API_KEY": "k",
            "BITTREND_CCXT_API_SECRET": "s",
        },
        clear=True,
    ):
        assert is_live_trading_enabled() is False


def test_live_enabled_with_ack_and_keys():
    with mock.patch.dict(
        os.environ,
        {
            "BITTREND_LIVE_TRADING": "1",
            "BITTREND_LIVE_TRADING_ACK": "YES",
            "BITTREND_CCXT_API_KEY": "k",
            "BITTREND_CCXT_API_SECRET": "s",
        },
        clear=True,
    ):
        assert is_live_trading_enabled() is True
        assert "LIVE" in live_trading_status_message()


def test_drift_blocks_live_defaults_to_mvp(monkeypatch):
    monkeypatch.setenv("BITTREND_LIVE_TRADING", "true")
    monkeypatch.setenv("BITTREND_LIVE_TRADING_ACK", "YES")
    monkeypatch.setenv("BITTREND_CCXT_API_KEY", "k")
    monkeypatch.setenv("BITTREND_CCXT_API_SECRET", "s")
    monkeypatch.setenv("BITTREND_LIVE_BLOCK_ON_DRIFT", "true")
    r = execute_rebalance_part(2, 50.0, -100.0, 100000.0, onchain_drift_any=True)
    assert r.mode == "mvp"
    assert r.ok is True
    assert "дрейф" in r.message.lower() or "drift" in r.message.lower()


def test_live_zero_deviation_skips_connect(monkeypatch):
    monkeypatch.setenv("BITTREND_LIVE_TRADING", "true")
    monkeypatch.setenv("BITTREND_LIVE_TRADING_ACK", "YES")
    monkeypatch.setenv("BITTREND_CCXT_API_KEY", "k")
    monkeypatch.setenv("BITTREND_CCXT_API_SECRET", "s")
    with mock.patch("bit_trend.execution.ccxt_executor._exchange_instance") as m_ex:
        r = execute_rebalance_part(1, 100.0, 0.0, 99000.0, onchain_drift_any=False)
    assert r.mode == "live"
    assert r.ok is True
    m_ex.assert_not_called()
