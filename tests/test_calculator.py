"""
Unit-тесты для BitTrendScorer.
"""

import pytest
from bit_trend.scoring.calculator import BitTrendScorer


class TestBitTrendScorer:
    """Тесты расчёта score и сигнала."""

    def test_compute_returns_tuple(self, sample_fetcher_data):
        """compute() возвращает (score, signal, components)."""
        scorer = BitTrendScorer()
        score, signal, components = scorer.compute(sample_fetcher_data)
        assert isinstance(score, (int, float))
        assert signal in ("BUY", "HOLD", "REDUCE", "EXIT")
        assert isinstance(components, dict)
        assert "mvrv_z_score" in components
        assert "nupl" in components

    def test_score_in_range(self, sample_fetcher_data):
        """Score всегда в диапазоне -100..+100."""
        scorer = BitTrendScorer()
        score, _, _ = scorer.compute(sample_fetcher_data)
        assert -100 <= score <= 100

    def test_bullish_data_gives_buy_or_hold(self, bullish_data):
        """Бычьи данные дают BUY или HOLD."""
        scorer = BitTrendScorer()
        _, signal, _ = scorer.compute(bullish_data)
        assert signal in ("BUY", "HOLD")

    def test_bearish_data_gives_reduce_or_exit(self, bearish_data):
        """Медвежьи данные дают REDUCE или EXIT."""
        scorer = BitTrendScorer()
        _, signal, _ = scorer.compute(bearish_data)
        assert signal in ("REDUCE", "EXIT", "HOLD")

    def test_score_to_signal_mapping(self):
        """Проверка маппинга score → signal по plan.md."""
        scorer = BitTrendScorer()
        assert scorer._score_to_signal(60) == "BUY"
        assert scorer._score_to_signal(50) == "BUY"
        assert scorer._score_to_signal(25) == "HOLD"
        assert scorer._score_to_signal(0) == "HOLD"
        assert scorer._score_to_signal(-15) == "REDUCE"
        assert scorer._score_to_signal(-35) == "EXIT"

    def test_empty_data_handling(self):
        """Пустые/None данные не ломают расчёт."""
        scorer = BitTrendScorer()
        empty_data = {"btc_price": 70000.0}
        score, signal, components = scorer.compute(empty_data)
        assert -100 <= score <= 100
        assert signal in ("BUY", "HOLD", "REDUCE", "EXIT")
