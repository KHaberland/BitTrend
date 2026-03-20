"""
Дрейф по истории ончейна в SQLite (S3 / upgrade_plan): detect_drift + снижение весов и алерты.

Историю пишет LookIntoBitcoin при успешном parse (save_history). Оцениваем подозрительное
«ползание» ряда по последним точкам — отдельные пороги для MVRV / NUPL / SOPR.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .lookintobitcoin import detect_drift
from .storage import get_history

_METRIC_KEYS = ("mvrv_z_score", "nupl", "sopr")
_ROW_FIELDS = {"mvrv_z_score": "mvrv_z_score", "nupl": "nupl", "sopr": "sopr"}


def _chronological_series(rows_chrono: List[Dict[str, Any]], field: str) -> List[float]:
    out: List[float] = []
    for r in rows_chrono:
        v = r.get(field)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def compute_onchain_drift_flags(
    *,
    enabled: bool,
    history_limit: int,
    window: int,
    thresholds: Dict[str, float],
    source_substring: str = "",
) -> Tuple[Dict[str, bool], Dict[str, List[float]]]:
    """
    Вернуть флаги дрейфа по метрикам и серии (для отладки/тестов).

    rows: из БД в порядке от новых к старым; внутри переворачиваем в хронологический порядок.
    """
    empty_flags = {k: False for k in _METRIC_KEYS}
    if not enabled or window < 2:
        return dict(empty_flags), {k: [] for k in _METRIC_KEYS}

    filt = source_substring.strip() or None
    rows_desc = get_history(limit=history_limit, source_contains=filt)
    chrono = list(reversed(rows_desc))

    flags: Dict[str, bool] = {}
    series_debug: Dict[str, List[float]] = {}
    for name in _METRIC_KEYS:
        field = _ROW_FIELDS[name]
        series = _chronological_series(chrono, field)
        series_debug[name] = series[-window:] if len(series) >= window else series
        th = float(thresholds.get(name, 0.5))
        flags[name] = detect_drift(series, window=window, threshold=th)

    return flags, series_debug


def onchain_drift_payload_for_fetcher(
    enabled: bool,
    history_limit: int,
    window: int,
    thresholds: Dict[str, float],
    source_substring: str,
) -> Dict[str, Any]:
    """Плоские поля для merge в результат DataFetcher и для BitTrendScorer."""
    flags, _ = compute_onchain_drift_flags(
        enabled=enabled,
        history_limit=history_limit,
        window=window,
        thresholds=thresholds,
        source_substring=source_substring,
    )
    any_drift = any(flags.values())
    labels = [name for name, v in flags.items() if v]
    note = ""
    if any_drift:
        note = "Дрейф ряда в истории LTB (" + ", ".join(labels) + ") — веса MVRV/NUPL/SOPR снижены"
    return {
        "onchain_drift": flags,
        "onchain_drift_any": any_drift,
        "onchain_drift_labels": labels,
        "onchain_drift_note": note,
    }
