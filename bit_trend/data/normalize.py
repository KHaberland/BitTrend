"""
Normalization layer: все метрики → диапазон 0–1.
Для единообразной работы с raw значениями.
"""

from typing import Optional


def normalize_mvrv(x: Optional[float]) -> Optional[float]:
    """MVRV Z-Score: -1..3.5 типично, нормализуем в 0–1."""
    if x is None:
        return None
    # x=0 → 0.2, x=3.5 → 0, x=-1 → 0.8 (низкий = хорошо для покупки)
    return min(max((3.5 - x) / 4.5, 0), 1)


def normalize_nupl(x: Optional[float]) -> Optional[float]:
    """NUPL: 0..1, >0.75 эйфория. Нормализуем: низкий = хорошо."""
    if x is None:
        return None
    return min(max((0.75 - x) / 0.75, 0), 1)


def normalize_sopr(x: Optional[float]) -> Optional[float]:
    """SOPR: 0.95..1.05 типично. <1 = дно, >1.05 = распределение."""
    if x is None:
        return None
    # 0.95 → 1, 1.05 → 0, 1.0 → 0.5
    return min(max((1.05 - x) / 0.1, 0), 1)


def normalize_all(data: dict) -> dict:
    """Нормализовать все метрики в data."""
    return {
        "mvrv_z_score_norm": normalize_mvrv(data.get("mvrv_z_score")),
        "nupl_norm": normalize_nupl(data.get("nupl")),
        "sopr_norm": normalize_sopr(data.get("sopr")),
    }
