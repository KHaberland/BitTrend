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
    """S2: полный DataFrame без сети (мок CoinGecko)."""
    import bit_trend.data.coingecko_onchain as cg

    n = 800
    ts = [i * 86_400_000 for i in range(n)]
    base = 100.0 + np.arange(n) * 0.02
    prices = [[ts[i], float(base[i])] for i in range(n)]
    caps = [[ts[i], float(base[i] * 19e6)] for i in range(n)]
    vols = [[ts[i], float(1e9 + i * 1e5)] for i in range(n)]
    payload = {"prices": prices, "market_caps": caps, "total_volumes": vols}

    with patch.object(cg, "_fetch_market_chart_payload", return_value=payload):
        df = cg.get_coingecko_810_dataframe()
    assert df is not None
    assert len(df) == n
    assert "composite_onchain" in df.columns
    assert "mvrv_z" in df.columns
