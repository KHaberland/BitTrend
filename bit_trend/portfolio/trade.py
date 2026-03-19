"""
TradeCalculator — расчёт объёма сделки и деление на 2–3 части.
"""

from typing import List, Tuple


class TradeCalculator:
    """
    Расчёт объёма сделки USDT ↔ BTC и разбиение на части.
    """

    def calculate_trade(
        self,
        deviation_usdt: float,
        btc_price: float,
        num_parts: int = 3
    ) -> Tuple[float, List[float]]:
        """
        Рассчитать объём сделки и разбить на части.

        Args:
            deviation_usdt: отклонение в USDT (> 0 = докупить BTC, < 0 = продать BTC)
            btc_price: текущая цена BTC
            num_parts: количество частей (2 или 3)

        Returns:
            (total_usdt, [part1, part2, ...])
            total_usdt: общий объём сделки в USDT (абсолютное значение)
            parts: список сумм для каждой части
        """
        total = abs(deviation_usdt)
        if total <= 0 or btc_price <= 0:
            return 0.0, []

        num_parts = max(1, min(num_parts, 5))
        base = total / num_parts
        parts = [round(base, 2) for _ in range(num_parts)]
        diff = round(total, 2) - sum(parts)
        if diff != 0 and parts:
            parts[0] = round(parts[0] + diff, 2)

        return round(total, 2), parts

    def usdt_to_btc_amount(self, usdt: float, btc_price: float) -> float:
        """Конвертировать USDT в количество BTC."""
        if btc_price <= 0:
            return 0.0
        return usdt / btc_price

    def btc_to_usdt_amount(self, btc_amount: float, btc_price: float) -> float:
        """Конвертировать BTC в USDT."""
        return btc_amount * btc_price