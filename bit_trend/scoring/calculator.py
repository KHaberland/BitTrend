"""
BitTrendScorer — расчёт score (-100..+100) и сигнала BUY/HOLD/REDUCE/EXIT.
Метрики и веса по plan.md.
"""
import math
import os
from typing import Dict, Any, Optional, Tuple

# Веса метрик (%)
WEIGHT_MVRV_Z = 0.25
WEIGHT_NUPL = 0.15
WEIGHT_SOPR = 0.10
WEIGHT_MA200 = 0.15
WEIGHT_DERIVATIVES = 0.15
WEIGHT_ETF = 0.15
WEIGHT_MACRO = 0.10
WEIGHT_FEAR_GREED = 0.05

# Опционально: вклад composite_onchain (z) из §8.10 — по умолчанию 0 (только UI), см. upgrade_plan S1
WEIGHT_COMPOSITE_810 = float(os.environ.get("SCORER_WEIGHT_COMPOSITE_810", "0"))
_COMPOSITE_810_SCALE = float(os.environ.get("SCORER_COMPOSITE_810_SCALE", "40"))


def _composite_810_to_component(z: Optional[float]) -> float:
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
    return max(-100.0, min(100.0, -zf * _COMPOSITE_810_SCALE))


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

        c_comp810 = _composite_810_to_component(data.get("cg_composite_onchain"))

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
            c_mvrv * WEIGHT_MVRV_Z
            + c_nupl * WEIGHT_NUPL
            + c_sopr * WEIGHT_SOPR
            + c_ma200 * WEIGHT_MA200
            + c_deriv * WEIGHT_DERIVATIVES
            + c_etf * WEIGHT_ETF
            + c_macro * WEIGHT_MACRO
            + c_fg * WEIGHT_FEAR_GREED
        )
        if WEIGHT_COMPOSITE_810 > 0:
            score += c_comp810 * WEIGHT_COMPOSITE_810

        score = max(-100.0, min(100.0, score))
        signal = self._score_to_signal(score)

        return round(score, 1), signal, components

    def _score_to_signal(self, score: float) -> str:
        """
        Маппинг score → сигнал:
        ≥ 50: BUY
        10 … 49: HOLD (накопление)
        -10 … 9: HOLD (осторожность)
        -30 … -11: REDUCE
        < -30: EXIT
        """
        if score >= 50:
            return "BUY"
        if score >= 10:
            return "HOLD"
        if score >= -10:
            return "HOLD"
        if score >= -30:
            return "REDUCE"
        return "EXIT"