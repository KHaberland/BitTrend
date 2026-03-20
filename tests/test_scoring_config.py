"""Загрузка scoring.yaml и переопределения окружения (E2)."""

from pathlib import Path

import pytest
import yaml

from bit_trend.config.loader import (
    get_scoring_config,
    reload_scoring_config,
)


@pytest.fixture(autouse=True)
def _clear_scoring_cache():
    reload_scoring_config()
    yield
    reload_scoring_config()


def test_default_yaml_loads():
    cfg = get_scoring_config()
    assert cfg.weights.mvrv_z == 0.25
    assert cfg.allocation[0].min_score == 70
    assert cfg.allocation[0].btc_pct == 95
    assert cfg.signal_bands[0].min_score == 50
    assert cfg.signal_bands[0].signal == "BUY"
    assert cfg.coingecko_composite.w_drawdown == 0.25
    assert cfg.onchain_drift.enabled is True
    assert cfg.onchain_drift.weight_factor == pytest.approx(0.25)


def test_env_overrides_composite_weights(monkeypatch, tmp_path: Path):
    minimal = {
        "version": 1,
        "scorer": {
            "weights": {
                "mvrv_z": 0.25,
                "nupl": 0.15,
                "sopr": 0.10,
                "ma200": 0.15,
                "derivatives": 0.15,
                "etf": 0.15,
                "macro": 0.10,
                "fear_greed": 0.05,
            },
            "composite_in_scorer": {"weight": 0.0, "scale": 40.0},
            "signal_bands": [{"min_score": 50, "signal": "BUY"}],
            "signal_default": "EXIT",
        },
        "allocation": {
            "rows": [{"min_score": 0, "btc_pct": 50}],
            "fallback_btc_pct": 5.0,
        },
        "coingecko_composite": {
            "w_mvrv": 0.30,
            "w_nupl": 0.25,
            "w_sopr": 0.20,
            "w_drawdown": 0.25,
            "w_volatility": -0.10,
            "z_window": 365,
            "z_min_periods": 30,
        },
    }
    p = tmp_path / "scoring.yaml"
    p.write_text(yaml.safe_dump(minimal), encoding="utf-8")
    monkeypatch.setenv("BITTREND_SCORING_CONFIG", str(p))
    monkeypatch.setenv("COMPOSITE_810_W_DRAWDOWN", "0.99")
    reload_scoring_config()
    cfg = get_scoring_config()
    assert cfg.coingecko_composite.w_drawdown == pytest.approx(0.99)


def test_custom_config_path(monkeypatch, tmp_path: Path):
    minimal = {
        "version": 1,
        "scorer": {
            "weights": {
                "mvrv_z": 1.0,
                "nupl": 0.0,
                "sopr": 0.0,
                "ma200": 0.0,
                "derivatives": 0.0,
                "etf": 0.0,
                "macro": 0.0,
                "fear_greed": 0.0,
            },
            "composite_in_scorer": {"weight": 0.0, "scale": 40.0},
            "signal_bands": [{"min_score": 0, "signal": "HOLD"}],
            "signal_default": "EXIT",
        },
        "allocation": {
            "rows": [{"min_score": -100, "btc_pct": 10}],
            "fallback_btc_pct": 5.0,
        },
        "coingecko_composite": {
            "w_mvrv": 0.30,
            "w_nupl": 0.25,
            "w_sopr": 0.20,
            "w_drawdown": 0.25,
            "w_volatility": -0.10,
            "z_window": 100,
            "z_min_periods": 30,
        },
    }
    p = tmp_path / "x.yaml"
    p.write_text(yaml.safe_dump(minimal), encoding="utf-8")
    reload_scoring_config()
    cfg = get_scoring_config(config_path=str(p))
    assert cfg.weights.mvrv_z == 1.0
    assert cfg.coingecko_composite.z_window == 100
