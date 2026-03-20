"""Цепочка fallback ончейна: Glassnode → LTB → CoinGecko (upgrade_plan D1)."""

from unittest.mock import patch

import pytest


@pytest.fixture
def no_glassnode(monkeypatch):
    monkeypatch.delenv("GLASSNODE_API_KEY", raising=False)


@patch("bit_trend.data.onchain._get_blockchain_stats", return_value=None)
@patch("bit_trend.data.onchain._get_blockchain_chart", return_value=None)
@patch("bit_trend.data.coingecko_onchain.get_coingecko_onchain_proxy")
@patch("bit_trend.data.lookintobitcoin.get_lookintobitcoin_metrics")
def test_coingecko_third_fallback_after_ltb_insufficient(
    mock_ltb,
    mock_cg_proxy,
    _mock_chart,
    _mock_stats,
    no_glassnode,
):
    from bit_trend.data.onchain import get_btc_onchain

    mock_ltb.return_value = {
        "source": "lookintobitcoin",
        "source_score": 0.2,
        "confidence": 0.4,
        "mvrv_z_score": None,
        "nupl": None,
        "sopr": None,
        "method": "parse",
    }
    mock_cg_proxy.return_value = {
        "mvrv_z_score": -0.5,
        "nupl": 0.1,
        "sopr": 1.01,
        "source": "coingecko",
        "method": "market_chart_proxy",
        "confidence": 0.55,
        "parser_version": "coingecko_v2",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "source_score": 0.52,
    }

    out = get_btc_onchain()
    assert out["mvrv_z_score"] == -0.5
    assert out["nupl"] == 0.1
    assert out["sopr"] == 1.01
    assert "coingecko" in str(out.get("onchain_source", ""))
    mock_cg_proxy.assert_called_once()


@patch("bit_trend.data.onchain._get_blockchain_stats", return_value=None)
@patch("bit_trend.data.onchain._get_blockchain_chart", return_value=None)
@patch("bit_trend.data.coingecko_onchain.get_coingecko_onchain_proxy")
@patch("bit_trend.data.lookintobitcoin.get_lookintobitcoin_metrics")
def test_coingecko_fills_only_missing_slots(
    mock_ltb,
    mock_cg_proxy,
    _mock_chart,
    _mock_stats,
    no_glassnode,
):
    from bit_trend.data.onchain import get_btc_onchain

    mock_ltb.return_value = {
        "source": "lookintobitcoin",
        "source_score": 0.8,
        "confidence": 0.7,
        "mvrv_z_score": 2.0,
        "nupl": None,
        "sopr": None,
        "method": "fast",
    }
    mock_cg_proxy.return_value = {
        "mvrv_z_score": -9.0,
        "nupl": 0.33,
        "sopr": 0.99,
        "source": "coingecko",
        "method": "market_chart_proxy",
        "confidence": 0.55,
        "parser_version": "coingecko_v2",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "source_score": 0.52,
    }

    out = get_btc_onchain()
    assert out["mvrv_z_score"] == 2.0
    assert out["nupl"] == 0.33
    assert out["sopr"] == 0.99
    mock_cg_proxy.assert_called_once()
