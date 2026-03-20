"""
Unit-тесты для AlertGenerator.
"""

import pytest
from bit_trend.alerts.generator import (
    AlertGenerator,
    generate_from_portfolio,
    _confidence_from_score,
    _format_action,
)


class TestAlertGenerator:
    """Тесты форматирования рекомендаций."""

    def test_generate_format(self):
        """Рекомендация содержит SIGNAL, Action, Confidence."""
        gen = AlertGenerator()
        result = gen.generate(
            signal="BUY",
            score=65.0,
            deviation_usdt=2500.0,
            btc_price=70800.0,
            parts=[833.33, 833.33, 833.34],
        )
        assert "SIGNAL: BUY" in result
        assert "Action:" in result
        assert "Confidence:" in result

    def test_generate_extra_suffix(self):
        gen = AlertGenerator()
        r = gen.generate(
            signal="HOLD",
            score=10.0,
            deviation_usdt=0.0,
            btc_price=70000.0,
            extra_suffix="тест дрейфа",
        )
        assert "⚠" in r
        assert "тест дрейфа" in r

    def test_confidence_high(self):
        """|score| >= 60 → HIGH."""
        assert _confidence_from_score(65) == "HIGH"
        assert _confidence_from_score(-70) == "HIGH"

    def test_confidence_medium(self):
        """|score| 30-59 → MEDIUM."""
        assert _confidence_from_score(45) == "MEDIUM"
        assert _confidence_from_score(-40) == "MEDIUM"

    def test_confidence_low(self):
        """|score| < 30 → LOW."""
        assert _confidence_from_score(20) == "LOW"
        assert _confidence_from_score(-10) == "LOW"

    def test_format_action_buy(self):
        """Действие на покупку BTC."""
        result = _format_action(2500, 70000, None)
        assert "USDT" in result
        assert "BTC" in result
        assert "2500" in result or "2,500" in result or "2 500" in result

    def test_format_action_sell(self):
        """Действие на продажу BTC."""
        result = _format_action(-1500, 70000, None)
        assert "BTC" in result
        assert "USDT" in result

    def test_format_action_hold(self):
        """Малое отклонение — держать позицию."""
        result = _format_action(0.001, 70000, None)
        assert "держите" in result or "позицию" in result


class TestGenerateFromPortfolio:
    """Тесты единой точки входа generate_from_portfolio."""

    def test_returns_string(self):
        """Возвращает строку рекомендации."""
        result = generate_from_portfolio(
            usdt=4000,
            btc_value_usdt=3500,
            score=55,
            signal="BUY",
            btc_price=70000,
            num_parts=3,
        )
        assert isinstance(result, str)
        assert "SIGNAL:" in result
        assert "BUY" in result
