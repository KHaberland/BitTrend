"""
AlertGenerator — форматирование рекомендаций.

Пример вывода: SIGNAL: BUY / Action: перевести 2500 USDT → BTC / Confidence: HIGH

Этап 4.3: generate_from_portfolio() — единая точка входа для UI (PM + Trade + Alert).
"""

from typing import List, Optional


def _confidence_from_score(score: float) -> str:
    """
    Определить уровень уверенности по score.
    |score| >= 60: HIGH
    |score| 30-59: MEDIUM
    |score| < 30: LOW
    """
    abs_score = abs(score)
    if abs_score >= 60:
        return "HIGH"
    if abs_score >= 30:
        return "MEDIUM"
    return "LOW"


def _format_action(
    deviation_usdt: float,
    btc_price: float,
    parts: Optional[List[float]] = None
) -> str:
    """
    Сформировать текст действия по отклонению портфеля.

    Args:
        deviation_usdt: > 0 = докупить BTC, < 0 = продать BTC
        btc_price: текущая цена BTC
        parts: список сумм для частей сделки (опционально)

    Returns:
        Текст рекомендации, например "перевести 2500 USDT → BTC (3 части)"
    """
    total = abs(deviation_usdt)
    if total < 0.01:
        return "держите текущую позицию"

    total_str = f"{total:,.0f}".replace(",", " ")
    if deviation_usdt > 0:
        if parts and len(parts) > 1:
            parts_str = ", ".join(f"{p:.0f}" for p in parts)
            return f"перевести {total_str} USDT → BTC ({len(parts)} части: {parts_str} USDT)"
        return f"перевести {total_str} USDT → BTC"
    else:
        if parts and len(parts) > 1:
            parts_str = ", ".join(f"{p:.0f}" for p in parts)
            return f"продать BTC на {total_str} USDT ({len(parts)} части: {parts_str} USDT)"
        return f"продать BTC на {total_str} USDT"


class AlertGenerator:
    """
    Генератор форматированных рекомендаций для портфеля.
    """

    def generate(
        self,
        signal: str,
        score: float,
        deviation_usdt: float,
        btc_price: float,
        parts: Optional[List[float]] = None,
        extra_suffix: Optional[str] = None,
    ) -> str:
        """
        Сформировать полную рекомендацию.

        Args:
            signal: BUY | HOLD | REDUCE | EXIT
            score: итоговый score (-100..+100)
            deviation_usdt: отклонение портфеля (> 0 = докупить BTC)
            btc_price: текущая цена BTC
            parts: список сумм для частей сделки (опционально)

        Returns:
            Строка вида: "SIGNAL: BUY / Action: перевести 2500 USDT → BTC / Confidence: HIGH"
        """
        action = _format_action(deviation_usdt, btc_price, parts)
        confidence = _confidence_from_score(score)

        line = f"SIGNAL: {signal} / Action: {action} / Confidence: {confidence}"
        if extra_suffix:
            line = f"{line} / ⚠ {extra_suffix}"
        return line

    def generate_short(self, signal: str, score: float) -> str:
        """
        Краткая рекомендация без действия (только сигнал и уверенность).
        """
        confidence = _confidence_from_score(score)
        return f"SIGNAL: {signal} / Confidence: {confidence}"


def generate_from_portfolio(
    usdt: float,
    btc_value_usdt: float,
    score: float,
    signal: str,
    btc_price: float,
    num_parts: int = 3,
    extra_suffix: Optional[str] = None,
) -> str:
    """
    Этап 4.3: Единая точка входа — расчёт отклонения, частей сделки и форматирование.

    Объединяет PortfolioManager, TradeCalculator и AlertGenerator для удобной
    интеграции в Streamlit UI.

    Args:
        usdt: сумма в USDT
        btc_value_usdt: стоимость BTC в USDT
        score: итоговый score (-100..+100)
        signal: BUY | HOLD | REDUCE | EXIT
        btc_price: текущая цена BTC
        num_parts: количество частей сделки (2 или 3)

    Returns:
        Готовая рекомендация: "SIGNAL: BUY / Action: ... / Confidence: HIGH"
    """
    from bit_trend.portfolio.manager import PortfolioManager
    from bit_trend.portfolio.trade import TradeCalculator

    pm = PortfolioManager()
    tc = TradeCalculator()
    gen = AlertGenerator()

    target_btc_pct = pm.get_target_btc_pct(score)
    _, _, deviation_usdt = pm.get_deviation(usdt, btc_value_usdt, target_btc_pct)
    _, parts = tc.calculate_trade(deviation_usdt, btc_price, num_parts)

    return gen.generate(
        signal=signal,
        score=score,
        deviation_usdt=deviation_usdt,
        btc_price=btc_price,
        parts=parts if len(parts) > 1 else None,
        extra_suffix=extra_suffix,
    )


def example() -> str:
    """
    Возвращает пример вывода в формате из plan.md (этап 4.2):
    SIGNAL: BUY / Action: перевести X USDT → BTC / Confidence: HIGH
    """
    gen = AlertGenerator()
    return gen.generate(
        signal="BUY",
        score=65.0,
        deviation_usdt=2500.0,
        btc_price=70800.0,
        parts=None,  # простой формат без разбиения на части
    )


if __name__ == "__main__":
    # Демонстрация формата из plan.md этап 4.2
    print(example())
