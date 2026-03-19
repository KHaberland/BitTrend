"""
Unit-тесты для DataFetcher.
С моками внешних API.
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from bit_trend.data import fetcher as fetcher_module
from bit_trend.data.fetcher import DataFetcher


def _mock_fetch_all_sources():
    """Мок данных вместо реальных API."""
    return {
        "btc_price": 70800.0,
        "ma200": 65000.0,
        "funding_rate": 0.00005,
        "funding_rate_8h_avg": 0.00004,
        "open_interest_usd": 15e9,
        "open_interest_7d_change_pct": 5.0,
        "fear_greed_value": 45,
        "fear_greed_classification": "Neutral",
        "macro_signal": 0,
        "fed_funds_rate": 5.25,
        "dxy": 104.5,
        "dxy_30d_change_pct": 1.2,
        "treasury_10y": 4.5,
        "mvrv_z_score": 1.5,
        "nupl": 0.4,
        "sopr": 1.02,
        "sopr_signal": 0,
        "exchange_flow_signal": 0,
        "etf_flow_7d_usd": 300_000_000,
        "etf_flow_1d_usd": 50_000_000,
        "etf_interpretation": "inflow",
    }


@patch("bit_trend.data.fetcher.get_btc_price", return_value=70800.0)
@patch("bit_trend.data.fetcher.get_ma200", return_value=65000.0)
@patch("bit_trend.data.fetcher.get_btc_derivatives")
@patch("bit_trend.data.fetcher.get_fear_greed_index")
@patch("bit_trend.data.fetcher.get_macro_data")
@patch("bit_trend.data.fetcher.get_btc_onchain")
@patch("bit_trend.data.fetcher.get_etf_flows")
def test_fetch_all_structure(
    mock_etf,
    mock_onchain,
    mock_macro,
    mock_fg,
    mock_deriv,
    mock_ma200,
    mock_price,
):
    """fetch_all() возвращает словарь с ожидаемыми ключами."""
    mock_deriv.return_value = {"funding_rate": 0.00005, "open_interest_7d_change_pct": 5}
    mock_fg.return_value = {"value": 45, "classification": "Neutral"}
    mock_macro.return_value = {"macro_signal": 0}
    mock_onchain.return_value = {"mvrv_z_score": 1.5, "nupl": 0.4, "sopr": 1.02}
    mock_etf.return_value = {"flow_7d_usd": 300e6}

    fetcher = DataFetcher(ttl_seconds=300)
    data = fetcher.fetch_all(use_cache=False)

    required_keys = [
        "btc_price", "ma200", "funding_rate", "fear_greed_value",
        "macro_signal", "mvrv_z_score", "nupl", "sopr", "etf_flow_7d_usd"
    ]
    for key in required_keys:
        assert key in data, f"Отсутствует ключ: {key}"


def test_cache_works():
    """Кэш возвращает те же данные при use_cache=True."""
    fetcher = DataFetcher(ttl_seconds=3600)
    fetcher_module._shared_cache = _mock_fetch_all_sources()
    fetcher_module._shared_cache_time = datetime.now()

    data = fetcher.fetch_all(use_cache=True)
    assert data["btc_price"] == 70800.0


def test_clear_cache():
    """clear_cache() очищает кэш."""
    fetcher = DataFetcher(ttl_seconds=300)
    fetcher_module._shared_cache = {"btc_price": 1}
    fetcher_module._shared_cache_time = datetime.now()

    fetcher.clear_cache()
    assert fetcher_module._shared_cache is None
    assert fetcher_module._shared_cache_time is None
