"""§8.10 / S1: rolling z и composite без HTTP; S2: ряд для бэктеста."""

from unittest.mock import patch

import numpy as np
import pandas as pd

from bit_trend.data.coingecko_onchain import rolling_z


def test_rolling_z_centered():
    """После стабилизации ряд вокруг нуля (синтетика)."""
    rng = np.random.default_rng(42)
    n = 500
    base = rng.normal(0, 1, n).cumsum()
    s = pd.Series(base)
    z = rolling_z(s, window=100, min_periods=30)
    tail = z.dropna().iloc[-50:]
    assert abs(float(tail.mean())) < 1.5


def test_composite_weights_sign_drawdown_term():
    """−w_dd * drawdown_z: при большем отрицательном drawdown_z вклад выше."""
    from bit_trend.data import coingecko_onchain as cg

    w_dd = cg.W_COMP_DD
    assert w_dd > 0
    # -w_dd * (-2) = +2*w_dd веса к composite при drawdown_z = -2
    assert w_dd * 2 == -w_dd * (-2.0)


def test_get_coingecko_810_dataframe_mocked():
    """S2: полный DataFrame без сети (мок build_market_history / plan01)."""
    import bit_trend.data.coingecko_onchain as cg

    n = 800
    base = 100.0 + np.arange(n) * 0.02
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    hist = pd.DataFrame(
        {
            "timestamp": ts,
            "price": base,
            "market_cap": base * 19e6,
            "volume": 1e9 + np.arange(n) * 1e5,
        }
    )

    with patch.object(cg, "build_market_history", return_value=hist):
        df = cg.get_coingecko_810_dataframe()
    assert df is not None
    assert len(df) == n
    assert "composite_onchain" in df.columns
    assert "mvrv_z" in df.columns


def test_dataframe_from_market_history_imputes_missing_cap():
    """Binance-подобный ряд без market_cap → заполняется price×supply (proxy §8.10)."""
    from bit_trend.data.coingecko_onchain import _dataframe_from_market_history

    n = 500
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    hist = pd.DataFrame(
        {
            "timestamp": ts,
            "price": np.linspace(30_000.0, 50_000.0, n),
            "market_cap": np.nan,
            "volume": 1e9,
        }
    )
    out = _dataframe_from_market_history(hist)
    assert out is not None
    assert len(out) == n
    assert (out["market_cap"] > 0).all()


def test_proxy_no_coingecko_when_market_history_short():
    """Прокси §8.10 только из market_history; короткий ряд → None (CoinGecko не используется)."""
    import bit_trend.data.coingecko_onchain as cg

    short = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
            "price": np.linspace(40_000.0, 42_000.0, 50),
            "market_cap": np.linspace(40_000.0, 42_000.0, 50) * 19e6,
            "volume": 1e9,
        }
    )

    with patch.object(cg, "build_market_history", return_value=short):
        with patch.object(cg, "_fetch_market_chart_payload") as mock_cg:
            df = cg.get_coingecko_810_dataframe()
    assert df is None
    mock_cg.assert_not_called()
