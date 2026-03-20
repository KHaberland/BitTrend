"""
Загрузка scoring.yaml с опциональными переопределениями из окружения (.env подхватывается через python-dotenv при импорте app или явном load_dotenv).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _try_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


@dataclass(frozen=True)
class SignalBand:
    min_score: float
    signal: str


@dataclass(frozen=True)
class AllocationRow:
    min_score: float
    btc_pct: float


@dataclass(frozen=True)
class ScorerWeights:
    mvrv_z: float
    nupl: float
    sopr: float
    ma200: float
    derivatives: float
    etf: float
    macro: float
    fear_greed: float


@dataclass(frozen=True)
class CompositeInScorer:
    weight: float
    scale: float


@dataclass(frozen=True)
class CoingeckoCompositeConfig:
    w_mvrv: float
    w_nupl: float
    w_sopr: float
    w_drawdown: float
    w_volatility: float
    z_window: int
    z_min_periods: int


@dataclass(frozen=True)
class ScoringConfig:
    weights: ScorerWeights
    composite_in_scorer: CompositeInScorer
    signal_bands: List[SignalBand]
    signal_default: str
    allocation: List[AllocationRow]
    allocation_fallback_btc_pct: float
    coingecko_composite: CoingeckoCompositeConfig


def _default_yaml_path() -> Path:
    return Path(__file__).resolve().parent / "scoring.yaml"


def _as_float(val: Any, key: str) -> float:
    try:
        return float(val)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{key}: ожидается число, получено {val!r}") from e


def _as_int(val: Any, key: str) -> int:
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{key}: ожидается целое, получено {val!r}") from e


def _parse_scoring_dict(raw: Dict[str, Any]) -> ScoringConfig:
    if int(raw.get("version", 1)) != 1:
        raise ValueError("scoring.yaml: поддерживается только version: 1")

    s = raw["scorer"]
    w = s["weights"]
    weights = ScorerWeights(
        mvrv_z=_as_float(w["mvrv_z"], "weights.mvrv_z"),
        nupl=_as_float(w["nupl"], "weights.nupl"),
        sopr=_as_float(w["sopr"], "weights.sopr"),
        ma200=_as_float(w["ma200"], "weights.ma200"),
        derivatives=_as_float(w["derivatives"], "weights.derivatives"),
        etf=_as_float(w["etf"], "weights.etf"),
        macro=_as_float(w["macro"], "weights.macro"),
        fear_greed=_as_float(w["fear_greed"], "weights.fear_greed"),
    )
    c = s["composite_in_scorer"]
    composite_in_scorer = CompositeInScorer(
        weight=_as_float(c["weight"], "composite_in_scorer.weight"),
        scale=_as_float(c["scale"], "composite_in_scorer.scale"),
    )
    bands_raw = s["signal_bands"]
    signal_bands = sorted(
        [
            SignalBand(
                min_score=_as_float(b["min_score"], f"signal_bands[{i}].min_score"),
                signal=str(b["signal"]),
            )
            for i, b in enumerate(bands_raw)
        ],
        key=lambda b: b.min_score,
        reverse=True,
    )

    sig_def = str(s.get("signal_default", "EXIT"))

    a = raw["allocation"]
    rows_raw = a["rows"]
    allocation = [
        AllocationRow(
            min_score=_as_float(r["min_score"], f"allocation.rows[{i}].min_score"),
            btc_pct=_as_float(r["btc_pct"], f"allocation.rows[{i}].btc_pct"),
        )
        for i, r in enumerate(rows_raw)
    ]
    allocation = sorted(allocation, key=lambda r: r.min_score, reverse=True)
    fallback = _as_float(a.get("fallback_btc_pct", 5.0), "allocation.fallback_btc_pct")

    cg = raw["coingecko_composite"]
    coingecko = CoingeckoCompositeConfig(
        w_mvrv=_as_float(cg["w_mvrv"], "coingecko_composite.w_mvrv"),
        w_nupl=_as_float(cg["w_nupl"], "coingecko_composite.w_nupl"),
        w_sopr=_as_float(cg["w_sopr"], "coingecko_composite.w_sopr"),
        w_drawdown=_as_float(cg["w_drawdown"], "coingecko_composite.w_drawdown"),
        w_volatility=_as_float(cg["w_volatility"], "coingecko_composite.w_volatility"),
        z_window=_as_int(cg["z_window"], "coingecko_composite.z_window"),
        z_min_periods=_as_int(cg["z_min_periods"], "coingecko_composite.z_min_periods"),
    )

    return ScoringConfig(
        weights=weights,
        composite_in_scorer=composite_in_scorer,
        signal_bands=signal_bands,
        signal_default=sig_def,
        allocation=allocation,
        allocation_fallback_btc_pct=fallback,
        coingecko_composite=coingecko,
    )


def _env_override_raw(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Переопределения из .env для обратной совместимости и секретов не требуются — только числа."""
    data = copy.deepcopy(raw)

    s = data.setdefault("scorer", {})
    c = s.setdefault("composite_in_scorer", {})

    if os.environ.get("SCORER_WEIGHT_COMPOSITE_810") is not None:
        c["weight"] = float(os.environ["SCORER_WEIGHT_COMPOSITE_810"])
    if os.environ.get("SCORER_COMPOSITE_810_SCALE") is not None:
        c["scale"] = float(os.environ["SCORER_COMPOSITE_810_SCALE"])

    cg = data.setdefault("coingecko_composite", {})
    if os.environ.get("COMPOSITE_810_W_MVRV") is not None:
        cg["w_mvrv"] = float(os.environ["COMPOSITE_810_W_MVRV"])
    if os.environ.get("COMPOSITE_810_W_NUPL") is not None:
        cg["w_nupl"] = float(os.environ["COMPOSITE_810_W_NUPL"])
    if os.environ.get("COMPOSITE_810_W_SOPR") is not None:
        cg["w_sopr"] = float(os.environ["COMPOSITE_810_W_SOPR"])
    if os.environ.get("COMPOSITE_810_W_DRAWDOWN") is not None:
        cg["w_drawdown"] = float(os.environ["COMPOSITE_810_W_DRAWDOWN"])
    if os.environ.get("COMPOSITE_810_W_VOLATILITY") is not None:
        cg["w_volatility"] = float(os.environ["COMPOSITE_810_W_VOLATILITY"])
    if os.environ.get("COMPOSITE_810_Z_WINDOW") is not None:
        cg["z_window"] = int(os.environ["COMPOSITE_810_Z_WINDOW"])
    if os.environ.get("COMPOSITE_810_Z_MIN_PERIODS") is not None:
        cg["z_min_periods"] = int(os.environ["COMPOSITE_810_Z_MIN_PERIODS"])

    return data


def _read_yaml_file(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: ожидается YAML-об object")
    return loaded


@lru_cache(maxsize=4)
def _cached_config(path_normalized: str) -> ScoringConfig:
    path = Path(path_normalized)
    if not path.is_file():
        raise FileNotFoundError(f"Файл конфигурации скоринга не найден: {path}")
    raw = _read_yaml_file(path)
    raw = _env_override_raw(raw)
    return _parse_scoring_dict(raw)


def get_scoring_config(
    config_path: Optional[str] = None,
) -> ScoringConfig:
    """
    Вернуть загруженный конфиг. Путь: аргумент → BITTREND_SCORING_CONFIG → bit_trend/config/scoring.yaml.
    При первом вызове подгружается .env через load_dotenv (если установлен python-dotenv).
    """
    _try_load_dotenv()
    if config_path:
        p = Path(config_path).resolve()
    else:
        env_p = os.environ.get("BITTREND_SCORING_CONFIG")
        p = Path(env_p).resolve() if env_p else _default_yaml_path()
    return _cached_config(str(p))


def reload_scoring_config() -> None:
    """Сброс кэша (тесты или смена файла без перезапуска процесса)."""
    _cached_config.cache_clear()
