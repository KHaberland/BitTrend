"""Тесты макро: CPI YoY (окно FRED), порядок интерпретации."""
from unittest.mock import patch

from bit_trend.data import macro


def test_cpi_yoy_uses_enough_history():
    # sort desc: [0] последний месяц, [12] — ~12 мес. назад
    obs = [{"value": str(v)} for v in [310.0] + [300.0] * 11 + [280.0, 280.0]]
    with patch.object(macro, "_get_fred_observations", return_value=obs):
        lvl, yoy = macro._get_cpi_level_and_yoy()
    assert lvl == 310.0
    assert yoy is not None
    assert abs(yoy - (310.0 / 280.0 - 1.0) * 100.0) < 1e-6


def test_cpi_yoy_insufficient_observations():
    with patch.object(macro, "_get_fred_observations", return_value=[{"value": "100"}] * 5):
        lvl, yoy = macro._get_cpi_level_and_yoy()
    assert lvl is None
    assert yoy is None


def test_interpret_macro_prioritizes_cpi_sp_in_text():
    """В строке интерпретации сначала блок CPI/S&P (приоритет продукта), затем остальное."""
    data = {
        "fed_funds_rate": 5.5,
        "dxy_30d_change_pct": None,
        "treasury_10y": None,
        "cpi_yoy_pct": 5.5,
        "sp500_30d_change_pct": 5.0,
    }
    _sig, text = macro._interpret_macro(data)
    assert "ликвидность" in text
    idx_cpi = text.find("CPI")
    idx_fed = text.find("ФРС")
    assert idx_cpi != -1 and idx_fed != -1
    assert idx_cpi < idx_fed
