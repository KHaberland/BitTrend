"""
PortfolioManager — целевая аллокация BTC по score и расчёт отклонения.
Таблица аллокации — bit_trend/config/scoring.yaml (E2).
"""

from typing import Any, Optional, Tuple, TYPE_CHECKING

from bit_trend.config.loader import get_scoring_config

if TYPE_CHECKING:
    from bit_trend.config.loader import ScoringConfig


def _score_to_btc_pct(score: float, cfg: "ScoringConfig") -> float:
    """Определить целевую долю BTC в портфеле по score."""
    for row in cfg.allocation:
        if score >= row.min_score:
            return float(row.btc_pct)
    return float(cfg.allocation_fallback_btc_pct)


class PortfolioManager:
    """
    Управление портфелем: целевая доля BTC, отклонение от цели.
    """

    def __init__(self, config: Optional["ScoringConfig"] = None) -> None:
        self._cfg = config or get_scoring_config()

    def get_target_btc_pct(self, score: float) -> float:
        """Получить целевую долю BTC (%) по score."""
        return _score_to_btc_pct(score, self._cfg)

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


def __getattr__(name: str) -> Any:
    """SCORE_TO_BTC_PCT — как раньше список пар (порог, %), из YAML (для ноутбуков)."""
    if name == "SCORE_TO_BTC_PCT":
        cfg = get_scoring_config()
        return [(r.min_score, r.btc_pct) for r in cfg.allocation]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")