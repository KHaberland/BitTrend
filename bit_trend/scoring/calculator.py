"""
BitTrendScorer — расчёт score (-100..+100) и сигнала BUY/HOLD/REDUCE/EXIT.
Метрики и веса по plan.md; веса/пороги/аллокация — в bit_trend/config/scoring.yaml (E2).
"""
import math
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING

from bit_trend.config.loader import get_scoring_config

if TYPE_CHECKING:
    from bit_trend.config.loader import ScoringConfig


def _composite_810_to_component(z: Optional[float], scale: float) -> float:
    """
    Согласование со шкалой скорера: по plan.md §8.10 низкий/отрицательный composite → зона BUY.
    Переводим в вклад -100..+100 (положительный = благоприятно для накопления BTC).
    """
    if z is None:
        return 0.0
    try:
        zf = float(z)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(zf):
        return 0.0
    return max(-100.0, min(100.0, -zf * scale))


def _metric_to_score(value: Optional[float], low_good: float, high_bad: float) -> float:
    """
    Преобразовать метрику в score от -100 до +100.
    low_good: значение, при котором score = +100 (хорошо для покупки)
    high_bad: значение, при котором score = -100 (плохо для покупки)
    """
    if value is None:
        return 0.0
    if low_good == high_bad:
        return 0.0
    if value <= low_good:
        return 100.0
    if value >= high_bad:
        return -100.0
    return 100.0 - 200.0 * (value - low_good) / (high_bad - low_good)


def _mvrv_z_score_to_component(val: Optional[float]) -> float:
    """MVRV Z-Score: < 0 = недооценка (+), > 3.5 = переоценка (-)."""
    if val is None:
        return 0.0
    if val < 0:
        return min(100, 100 + val * 20)
    if val > 3.5:
        return max(-100, 100 - (val - 3.5) * 50)
    return 100.0 - 200.0 * val / 3.5


def _nupl_to_component(val: Optional[float]) -> float:
    """NUPL: < 0 = капитуляция (+), > 0.75 = эйфория (-)."""
    if val is None:
        return 0.0
    if val < 0:
        return min(100, 100 + val * 100)
    if val > 0.75:
        return max(-100, 100 - (val - 0.75) * 400)
    return 100.0 - 200.0 * val / 0.75


def _sopr_to_component(val: Optional[float]) -> float:
    """SOPR: < 1 = продажа в убыток, часто дно (+), > 1.05 = распределение (-)."""
    if val is None:
        return 0.0
    if val < 0.95:
        return 80.0
    if val > 1.05:
        return -80.0
    return 100.0 - 200.0 * (val - 0.95) / 0.1


def _ma200_to_component(price: float, ma200: Optional[float]) -> float:
    """MA200: цена выше MA = бычий (+), ниже = медвежий (-)."""
    if ma200 is None or ma200 <= 0:
        return 0.0
    pct = (price - ma200) / ma200 * 100
    if pct > 20:
        return -50
    if pct > 0:
        return 50.0 * (1 - pct / 20)
    if pct < -30:
        return 100.0
    return 50.0 - 50.0 * pct / 30


def _derivatives_to_component(
    funding_rate: Optional[float],
    oi_change: Optional[float]
) -> float:
    """Funding + OI: отрицательный funding = бычий, рост OI = перегрев."""
    score = 0.0
    if funding_rate is not None:
        if funding_rate < -0.00005:
            score += 50
        elif funding_rate > 0.0001:
            score -= 50
    if oi_change is not None and oi_change > 10:
        score -= 30
    return max(-100, min(100, score))


def _etf_to_component(flow_7d: Optional[float]) -> float:
    """ETF flows: приток = бычий (+), отток = медвежий (-)."""
    if flow_7d is None:
        return 0.0
    if flow_7d > 500_000_000:
        return 80.0
    if flow_7d < -500_000_000:
        return -80.0
    return flow_7d / 6_250_000


def _macro_to_component(macro_signal: int) -> float:
    """Macro: -1 -> -50, 0 -> 0, +1 -> +50."""
    return macro_signal * 50.0


def _fear_greed_to_component(val: Optional[int]) -> float:
    """Fear & Greed: < 25 = страх (+), > 75 = жадность (-)."""
    if val is None:
        return 0.0
    if val < 25:
        return 80.0
    if val > 75:
        return -80.0
    return 100.0 - 200.0 * (val - 25) / 50


class BitTrendScorer:
    """
    Расчёт итогового score (-100..+100) и сигнала BUY/HOLD/REDUCE/EXIT.
    """

    def __init__(self, config: Optional["ScoringConfig"] = None) -> None:
        self._cfg = config or get_scoring_config()

    def compute(self, data: Dict[str, Any]) -> Tuple[float, str, Dict[str, float]]:
        """
        Вычислить score и сигнал по данным из DataFetcher.

        Returns:
            (score, signal, components)
            score: от -100 до +100
            signal: "BUY" | "HOLD" | "REDUCE" | "EXIT"
            components: вклад каждой метрики в итоговый score
        """
        price = data.get("btc_price") or 0
        ma200 = data.get("ma200")

        c_mvrv = _mvrv_z_score_to_component(data.get("mvrv_z_score"))
        c_nupl = _nupl_to_component(data.get("nupl"))
        c_sopr = _sopr_to_component(data.get("sopr"))
        c_ma200 = _ma200_to_component(price, ma200)
        c_deriv = _derivatives_to_component(
            data.get("funding_rate"),
            data.get("open_interest_7d_change_pct")
        )
        c_etf = _etf_to_component(data.get("etf_flow_7d_usd"))
        c_macro = _macro_to_component(data.get("macro_signal", 0))
        c_fg = _fear_greed_to_component(data.get("fear_greed_value"))

        w = self._cfg.weights
        comp = self._cfg.composite_in_scorer
        c_comp810 = _composite_810_to_component(data.get("cg_composite_onchain"), comp.scale)

        components = {
            "mvrv_z_score": c_mvrv,
            "nupl": c_nupl,
            "sopr": c_sopr,
            "ma200": c_ma200,
            "derivatives": c_deriv,
            "etf": c_etf,
            "macro": c_macro,
            "fear_greed": c_fg,
            "composite_810": c_comp810,
        }

        score = (
            c_mvrv * w.mvrv_z
            + c_nupl * w.nupl
            + c_sopr * w.sopr
            + c_ma200 * w.ma200
            + c_deriv * w.derivatives
            + c_etf * w.etf
            + c_macro * w.macro
            + c_fg * w.fear_greed
        )
        if comp.weight > 0:
            score += c_comp810 * comp.weight

        score = max(-100.0, min(100.0, score))
        signal = self._score_to_signal(score)

        return round(score, 1), signal, components

    def _score_to_signal(self, score: float) -> str:
        """
        Маппинг score → сигнал (границы в scoring.yaml, поле scorer.signal_bands).
        """
        for band in self._cfg.signal_bands:
            if score >= band.min_score:
                return band.signal
        return self._cfg.signal_default


_LEGACY_WEIGHT_NAMES = {
    "WEIGHT_MVRV_Z": "mvrv_z",
    "WEIGHT_NUPL": "nupl",
    "WEIGHT_SOPR": "sopr",
    "WEIGHT_MA200": "ma200",
    "WEIGHT_DERIVATIVES": "derivatives",
    "WEIGHT_ETF": "etf",
    "WEIGHT_MACRO": "macro",
    "WEIGHT_FEAR_GREED": "fear_greed",
}


def __getattr__(name: str):
    """Обратная совместимость для ноутбуков: веса из scoring.yaml."""
    wkey = _LEGACY_WEIGHT_NAMES.get(name)
    if wkey is not None:
        return getattr(get_scoring_config().weights, wkey)
    if name == "WEIGHT_COMPOSITE_810":
        return get_scoring_config().composite_in_scorer.weight
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")