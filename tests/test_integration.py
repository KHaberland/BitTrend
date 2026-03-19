"""
Интеграционный тест: полная цепочка DataFetcher → Scorer → PM → Trade → Alert.
Без реальных API-вызовов (моки).
"""

import pytest
from unittest.mock import patch

from bit_trend.data.fetcher import DataFetcher
from bit_trend.scoring.calculator import BitTrendScorer
from bit_trend.portfolio.manager import PortfolioManager
from bit_trend.portfolio.trade import TradeCalculator
from bit_trend.alerts.generator import generate_from_portfolio


def _mock_fetch_all():
    """Мок DataFetcher.fetch_all() — возвращает полный набор данных."""
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


@patch.object(DataFetcher, "fetch_all", return_value=_mock_fetch_all())
def test_full_pipeline(mock_fetch):
    """
    Полная цепочка: fetch → score → target → deviation → trade → alert.
    Проверяет, что все модули работают вместе без ошибок.
    """
    # 1. Data
    fetcher = DataFetcher(ttl_seconds=300)
    data = fetcher.fetch_all(use_cache=False)
    btc_price = data["btc_price"]

    # 2. Score
    scorer = BitTrendScorer()
    score, signal, components = scorer.compute(data)
    assert -100 <= score <= 100
    assert signal in ("BUY", "HOLD", "REDUCE", "EXIT")

    # 3. Portfolio
    usdt = 4000.0
    btc_amount = 0.05
    btc_value_usdt = btc_amount * btc_price

    pm = PortfolioManager()
    target_btc_pct = pm.get_target_btc_pct(score)
    total, current_pct, deviation_usdt = pm.get_deviation(
        usdt, btc_value_usdt, target_btc_pct
    )

    # 4. Trade
    tc = TradeCalculator()
    total_trade, parts = tc.calculate_trade(deviation_usdt, btc_price, num_parts=3)

    # 5. Alert (единая точка входа)
    recommendation = generate_from_portfolio(
        usdt=usdt,
        btc_value_usdt=btc_value_usdt,
        score=score,
        signal=signal,
        btc_price=btc_price,
        num_parts=3,
    )

    # Проверки
    assert total > 0
    assert "SIGNAL:" in recommendation
    assert signal in recommendation
    assert "Confidence:" in recommendation

    if abs(deviation_usdt) > 0.01:
        assert len(parts) <= 3
        assert sum(parts) == pytest.approx(total_trade)


def test_generate_from_portfolio_integration():
    """generate_from_portfolio объединяет PM + Trade + Alert."""
    result = generate_from_portfolio(
        usdt=4000,
        btc_value_usdt=3500,
        score=55,
        signal="BUY",
        btc_price=70000,
        num_parts=3,
    )
    assert isinstance(result, str)
    assert "BUY" in result
    assert "SIGNAL:" in result
    assert "Action:" in result
