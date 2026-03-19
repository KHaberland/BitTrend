"""
Data contract для он-чейн метрик.
Убирает баги, делает код читаемым, готовит к API.
"""

from typing import TypedDict


class OnchainMetrics(TypedDict, total=False):
    """Контракт он-чейн метрик из LookIntoBitcoin / Glassnode."""
    mvrv_z_score: float | None
    nupl: float | None
    sopr: float | None
    source: str
    method: str
    confidence: float
    parser_version: str
    timestamp: str
    source_score: float
