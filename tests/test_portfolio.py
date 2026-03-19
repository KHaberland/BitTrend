"""
Unit-тесты для PortfolioManager и TradeCalculator.
"""

import pytest
from bit_trend.portfolio.manager import PortfolioManager
from bit_trend.portfolio.trade import TradeCalculator


class TestPortfolioManager:
    """Тесты целевой аллокации и отклонения."""

    def test_get_target_btc_pct(self):
        """Целевая доля BTC по score (plan.md таблица)."""
        pm = PortfolioManager()
        assert pm.get_target_btc_pct(80) == 95
        assert pm.get_target_btc_pct(70) == 95
        assert pm.get_target_btc_pct(55) == 80
        assert pm.get_target_btc_pct(40) == 65
        assert pm.get_target_btc_pct(20) == 50
        assert pm.get_target_btc_pct(0) == 40
        assert pm.get_target_btc_pct(-20) == 25
        assert pm.get_target_btc_pct(-40) == 15
        assert pm.get_target_btc_pct(-60) == 5

    def test_get_deviation_buy_btc(self):
        """deviation > 0: нужно докупить BTC."""
        pm = PortfolioManager()
        total, current_pct, deviation = pm.get_deviation(
            usdt=5000, btc_value_usdt=2000, target_btc_pct=80
        )
        assert total == 7000
        assert current_pct == pytest.approx(2000 / 7000 * 100)
        assert deviation > 0  # нужно докупить

    def test_get_deviation_sell_btc(self):
        """deviation < 0: нужно продать BTC."""
        pm = PortfolioManager()
        _, _, deviation = pm.get_deviation(
            usdt=1000, btc_value_usdt=9000, target_btc_pct=20
        )
        assert deviation < 0

    def test_get_deviation_zero_total(self):
        """Пустой портфель возвращает нули."""
        pm = PortfolioManager()
        total, current_pct, deviation = pm.get_deviation(0, 0, 50)
        assert total == 0
        assert current_pct == 0
        assert deviation == 0


class TestTradeCalculator:
    """Тесты расчёта сделки и разбиения на части."""

    def test_calculate_trade_3_parts(self):
        """Сделка разбивается на 3 части."""
        tc = TradeCalculator()
        total, parts = tc.calculate_trade(3000, 70000, num_parts=3)
        assert total == 3000
        assert len(parts) == 3
        assert sum(parts) == pytest.approx(3000)

    def test_calculate_trade_2_parts(self):
        """Сделка разбивается на 2 части."""
        tc = TradeCalculator()
        total, parts = tc.calculate_trade(2000, 70000, num_parts=2)
        assert len(parts) == 2
        assert sum(parts) == pytest.approx(2000)

    def test_calculate_trade_zero_deviation(self):
        """Нулевое отклонение — пустой список."""
        tc = TradeCalculator()
        total, parts = tc.calculate_trade(0, 70000, num_parts=3)
        assert total == 0
        assert parts == []

    def test_calculate_trade_negative_deviation(self):
        """Отрицательное отклонение — абсолютное значение."""
        tc = TradeCalculator()
        total, parts = tc.calculate_trade(-1500, 70000, num_parts=2)
        assert total == 1500
        assert len(parts) == 2

    def test_usdt_to_btc_amount(self):
        """Конвертация USDT в BTC."""
        tc = TradeCalculator()
        btc = tc.usdt_to_btc_amount(7000, 70000)
        assert btc == pytest.approx(0.1)

    def test_btc_to_usdt_amount(self):
        """Конвертация BTC в USDT."""
        tc = TradeCalculator()
        usdt = tc.btc_to_usdt_amount(0.1, 70000)
        assert usdt == 7000
