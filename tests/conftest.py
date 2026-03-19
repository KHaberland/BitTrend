"""
Pytest fixtures для BitTrend.
Общие данные и моки для тестов.
"""

import pytest
from typing import Dict, Any


@pytest.fixture
def sample_fetcher_data() -> Dict[str, Any]:
    """Пример данных из DataFetcher.fetch_all() для тестов."""
    return {
        "btc_price": 70800.0,
        "ma200": 65000.0,
        "funding_rate": 0.00005,
        "funding_rate_8h_avg": 0.00004,
        "open_interest_usd": 15_000_000_000,
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


@pytest.fixture
def bullish_data() -> Dict[str, Any]:
    """Данные с бычьим настроением (низкий MVRV, страх, приток ETF)."""
    return {
        "btc_price": 50000.0,
        "ma200": 55000.0,
        "funding_rate": -0.0001,
        "open_interest_7d_change_pct": -5.0,
        "fear_greed_value": 20,
        "macro_signal": 1,
        "mvrv_z_score": -0.5,
        "nupl": 0.1,
        "sopr": 0.95,
        "etf_flow_7d_usd": 600_000_000,
    }


@pytest.fixture
def bearish_data() -> Dict[str, Any]:
    """Данные с медвежьим настроением."""
    return {
        "btc_price": 95000.0,
        "ma200": 70000.0,
        "funding_rate": 0.0002,
        "open_interest_7d_change_pct": 15.0,
        "fear_greed_value": 85,
        "macro_signal": -1,
        "mvrv_z_score": 4.0,
        "nupl": 0.8,
        "sopr": 1.08,
        "etf_flow_7d_usd": -600_000_000,
    }
