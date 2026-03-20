"""
Unit-тесты для DataFetcher.
С моками внешних API.
"""

import os
import pytest
from datetime import datetime, timedelta
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
        "cpi_index": 300.0,
        "cpi_yoy_pct": 3.1,
        "sp500": 5100.0,
        "sp500_30d_change_pct": 2.0,
        "mvrv_z_score": 1.5,
        "nupl": 0.4,
        "sopr": 1.02,
        "sopr_signal": 0,
        "exchange_flow_signal": 0,
        "onchain_source": "glassnode",
        "onchain_confidence": 0.95,
        "onchain_source_score": 0.9,
        "onchain_method": "api",
        "etf_flow_7d_usd": 300_000_000,
        "etf_flow_1d_usd": 50_000_000,
        "etf_interpretation": "inflow",
    }


def _split_fast_slow(m: dict) -> tuple:
    fast_keys = (
        "btc_price", "ma200", "funding_rate", "funding_rate_8h_avg",
        "open_interest_usd", "open_interest_7d_change_pct",
        "fear_greed_value", "fear_greed_classification",
    )
    slow_internal = {
        "macro_signal": m["macro_signal"],
        "fed_funds_rate": m["fed_funds_rate"],
        "dxy": m["dxy"],
        "dxy_30d_change_pct": m["dxy_30d_change_pct"],
        "treasury_10y": m["treasury_10y"],
        "cpi_index": m.get("cpi_index"),
        "cpi_yoy_pct": m.get("cpi_yoy_pct"),
        "sp500": m.get("sp500"),
        "sp500_30d_change_pct": m.get("sp500_30d_change_pct"),
        "macro_interpretation": m.get("macro_interpretation", "тест"),
        "mvrv_z_score": m["mvrv_z_score"],
        "nupl": m["nupl"],
        "sopr": m["sopr"],
        "sopr_signal": m["sopr_signal"],
        "exchange_flow_signal": m["exchange_flow_signal"],
        "onchain_source": m.get("onchain_source"),
        "onchain_confidence": m.get("onchain_confidence"),
        "onchain_source_score": m.get("onchain_source_score"),
        "onchain_method": m.get("onchain_method"),
        "etf_flow_7d_usd": m["etf_flow_7d_usd"],
        "etf_flow_1d_usd": m["etf_flow_1d_usd"],
        "etf_interpretation": m["etf_interpretation"],
    }
    fast_internal = {k: m[k] for k in fast_keys}
    return fast_internal, slow_internal


@patch("bit_trend.data.fetcher.get_btc_price", return_value=70800.0)
@patch("bit_trend.data.fetcher.get_ma200", return_value=65000.0)
@patch("bit_trend.data.fetcher.get_btc_derivatives")
@patch("bit_trend.data.fetcher.get_fear_greed_index")
@patch("bit_trend.data.fetcher.get_macro_data")
@patch("bit_trend.data.fetcher.get_btc_onchain")
@patch("bit_trend.data.fetcher.get_etf_flows")
@patch("bit_trend.data.fetcher.get_coingecko_810_bundle", return_value=None)
def test_fetch_all_structure(
    mock_cg810,
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
    m = _mock_fetch_all_sources()
    m["macro_interpretation"] = "нейтральная среда"
    fast, slow = _split_fast_slow(m)
    fetcher_module._shared_fast_cache = fast
    fetcher_module._shared_fast_time = datetime.now()
    fetcher_module._shared_slow_cache = slow
    fetcher_module._shared_slow_time = datetime.now()

    data = fetcher.fetch_all(use_cache=True)
    assert data["btc_price"] == 70800.0


def test_clear_cache():
    """clear_cache() очищает кэш."""
    fetcher = DataFetcher(ttl_seconds=300)
    fetcher_module._shared_fast_cache = {"btc_price": 1}
    fetcher_module._shared_fast_time = datetime.now()
    fetcher_module._shared_slow_cache = {"macro_signal": 0}
    fetcher_module._shared_slow_time = datetime.now()

    fetcher.clear_cache()
    assert fetcher_module._shared_fast_cache is None
    assert fetcher_module._shared_fast_time is None
    assert fetcher_module._shared_slow_cache is None
    assert fetcher_module._shared_slow_time is None


def test_empty_cache_ttl_fast_falls_back_to_constructor():
    """Пустой CACHE_TTL_FAST в .env не ломает конструктор (D3)."""
    with patch.dict(os.environ, {"CACHE_TTL_FAST": ""}, clear=False):
        f = DataFetcher(ttl_seconds=123)
    assert f.ttl_fast == timedelta(seconds=123)
    with patch.dict(os.environ, {"CACHE_TTL_SLOW": "  "}, clear=False):
        f2 = DataFetcher(ttl_seconds=60)
    assert f2.ttl_slow == timedelta(seconds=3600)


@patch("bit_trend.data.fetcher.get_coingecko_810_bundle", return_value=None)
@patch("bit_trend.data.fetcher.get_etf_flows")
@patch("bit_trend.data.fetcher.get_btc_onchain")
@patch("bit_trend.data.fetcher.get_macro_data")
@patch("bit_trend.data.fetcher.get_fear_greed_index")
@patch("bit_trend.data.fetcher.get_btc_derivatives")
@patch("bit_trend.data.fetcher.get_ma200")
@patch("bit_trend.data.fetcher.get_btc_price")
def test_only_fast_sources_when_slow_cache_still_valid(
    mock_price,
    mock_ma,
    mock_deriv,
    mock_fg,
    mock_macro,
    mock_onchain,
    mock_etf,
    mock_cg,
):
    """Истёк TTL только быстрого блока — макро/ончейн/ETF не дергаются (D3)."""
    mock_price.return_value = 70800.0
    mock_ma.return_value = 65000.0
    mock_deriv.return_value = {}
    mock_fg.return_value = {}

    fetcher = DataFetcher(ttl_seconds=300)
    m = _mock_fetch_all_sources()
    m["macro_interpretation"] = "ok"
    fast, slow = _split_fast_slow(m)
    fetcher_module._shared_fast_cache = fast
    fetcher_module._shared_fast_time = datetime.now() - timedelta(seconds=99999)
    fetcher_module._shared_slow_cache = slow
    fetcher_module._shared_slow_time = datetime.now()

    fetcher.fetch_all(use_cache=True)

    mock_macro.assert_not_called()
    mock_onchain.assert_not_called()
    mock_etf.assert_not_called()
    mock_cg.assert_not_called()
    mock_price.assert_called()


@patch("bit_trend.data.fetcher.get_coingecko_810_bundle", return_value=None)
@patch("bit_trend.data.fetcher.get_etf_flows")
@patch("bit_trend.data.fetcher.get_btc_onchain")
@patch("bit_trend.data.fetcher.get_macro_data")
@patch("bit_trend.data.fetcher.get_fear_greed_index")
@patch("bit_trend.data.fetcher.get_btc_derivatives")
@patch("bit_trend.data.fetcher.get_ma200")
@patch("bit_trend.data.fetcher.get_btc_price")
def test_only_slow_sources_when_fast_cache_still_valid(
    mock_price,
    mock_ma,
    mock_deriv,
    mock_fg,
    mock_macro,
    mock_onchain,
    mock_etf,
    mock_cg,
):
    """Истёк TTL только медленного блока — цена/деривативы/F&G не запрашиваются снова (D3)."""
    mock_macro.return_value = {"macro_signal": 0}
    mock_onchain.return_value = {"mvrv_z_score": 1.0}
    mock_etf.return_value = {}

    fetcher = DataFetcher(ttl_seconds=300)
    m = _mock_fetch_all_sources()
    m["macro_interpretation"] = "ok"
    fast, slow = _split_fast_slow(m)
    fetcher_module._shared_fast_cache = fast
    fetcher_module._shared_fast_time = datetime.now()
    fetcher_module._shared_slow_cache = slow
    fetcher_module._shared_slow_time = datetime.now() - timedelta(seconds=99999)

    fetcher.fetch_all(use_cache=True)

    mock_price.assert_not_called()
    mock_ma.assert_not_called()
    mock_deriv.assert_not_called()
    mock_fg.assert_not_called()
    mock_macro.assert_called()
    mock_onchain.assert_called()
    mock_etf.assert_called()
