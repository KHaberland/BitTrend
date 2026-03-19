"""
PortfolioManager — целевая аллокация BTC по score и расчёт отклонения.
"""

from typing import Tuple

# Таблица целевой аллокации BTC по score (plan.md)
SCORE_TO_BTC_PCT = [
    (70, 95),
    (50, 80),
    (30, 65),
    (10, 50),
    (-10, 40),
    (-29, 25),
    (-49, 15),
    (-100, 5),
]


def _score_to_btc_pct(score: float) -> float:
    """Определить целевую долю BTC в портфеле по score."""
    for threshold, pct in SCORE_TO_BTC_PCT:
        if score >= threshold:
            return float(pct)
    return 5.0


class PortfolioManager:
    """
    Управление портфелем: целевая доля BTC, отклонение от цели.
    """

    def get_target_btc_pct(self, score: float) -> float:
        """Получить целевую долю BTC (%) по score."""
        return _score_to_btc_pct(score)

    def get_deviation(
        self,
        usdt: float,
        btc_value_usdt: float,
        target_btc_pct: float
    ) -> Tuple[float, float, float]:
        """
        Рассчитать отклонение текущего портфеля от целевой доли.

        Args:
            usdt: сумма в USDT
            btc_value_usdt: стоимость BTC в USDT
            target_btc_pct: целевая доля BTC (0..100)

        Returns:
            (total_portfolio_usd, current_btc_pct, deviation_usdt)
            deviation_usdt > 0: нужно докупить BTC на эту сумму
            deviation_usdt < 0: нужно продать BTC на эту сумму
        """
        total = usdt + btc_value_usdt
        if total <= 0:
            return 0.0, 0.0, 0.0

        current_btc_pct = (btc_value_usdt / total) * 100
        target_btc_value = total * (target_btc_pct / 100)
        deviation_usdt = target_btc_value - btc_value_usdt

        return total, current_btc_pct, deviation_usdt