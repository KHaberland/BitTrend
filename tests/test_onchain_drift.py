"""S3: дрейф по истории SQLite и снижение весов в BitTrendScorer."""

from unittest.mock import patch

import pytest

from bit_trend.config.loader import reload_scoring_config
from bit_trend.data.onchain_drift import compute_onchain_drift_flags, onchain_drift_payload_for_fetcher
from bit_trend.scoring.calculator import BitTrendScorer


@pytest.fixture(autouse=True)
def _reload_cfg():
    reload_scoring_config()
    yield
    reload_scoring_config()


def _rows_desc_drifting_mvrv(n: int = 12):
    """DESC по id: последняя запись — первая в списке. mvrv «ползёт» на 1.0."""
    base = 2.0
    out = []
    for i in range(n):
        ts = f"2025-01-{i+1:02d}T00:00:00Z"
        mvrv = base + i * 0.15
        out.append(
            {
                "timestamp": ts,
                "mvrv_z_score": mvrv,
                "nupl": 0.4,
                "sopr": 1.01,
                "source": "lookintobitcoin",
                "confidence": 0.9,
            }
        )
    return list(reversed(out))


@patch("bit_trend.data.onchain_drift.get_history")
def test_drift_detects_creeping_mvrv(mock_gh):
    mock_gh.return_value = _rows_desc_drifting_mvrv(12)
    flags, _ = compute_onchain_drift_flags(
        enabled=True,
        history_limit=500,
        window=10,
        thresholds={"mvrv_z_score": 0.5, "nupl": 0.12, "sopr": 0.12},
        source_substring="lookintobitcoin",
    )
    assert flags["mvrv_z_score"] is True
    assert flags["nupl"] is False
    assert flags["sopr"] is False


@patch("bit_trend.data.onchain_drift.get_history")
def test_payload_note_when_any(mock_gh):
    mock_gh.return_value = _rows_desc_drifting_mvrv(12)
    pl = onchain_drift_payload_for_fetcher(
        enabled=True,
        history_limit=500,
        window=10,
        thresholds={"mvrv_z_score": 0.5, "nupl": 0.12, "sopr": 0.12},
        source_substring="lookintobitcoin",
    )
    assert pl["onchain_drift_any"] is True
    assert "mvrv_z_score" in pl["onchain_drift_labels"]
    assert pl["onchain_drift_note"]


def test_scorer_reduces_weights_when_drift_flag():
    data = {
        "btc_price": 70000.0,
        "ma200": 65000.0,
        "funding_rate": 0.0,
        "open_interest_7d_change_pct": 0.0,
        "fear_greed_value": 50,
        "macro_signal": 0,
        "mvrv_z_score": 1.0,
        "nupl": 0.4,
        "sopr": 1.0,
        "etf_flow_7d_usd": 0.0,
        "onchain_drift": {"mvrv_z_score": True, "nupl": False, "sopr": False},
    }
    scorer = BitTrendScorer()
    s1, _, _ = scorer.compute(data)
    data2 = {**data, "onchain_drift": {"mvrv_z_score": False, "nupl": False, "sopr": False}}
    s0, _, _ = scorer.compute(data2)
    assert s1 != s0
