"""
plan01 §11.2: интеграция с живыми API (сеть).

Запуск (PowerShell):
  $env:COINGECKO_VERIFY='1'
  $env:FREECRYPTO_API_TOKEN='<токен>'
  python -m pytest tests/test_market_plan01_integration.py -v -m integration

Или все тесты без integration по умолчанию:
  python -m pytest tests/ -v
"""

from __future__ import annotations

import os

import pytest

from bit_trend.data.freecrypto import FreeCryptoDataSource
from bit_trend.data.market_coingecko import CoinGeckoMarketDataSource


def _coingecko_verify_enabled() -> bool:
    return os.environ.get("COINGECKO_VERIFY", "").strip().lower() in ("1", "true", "yes", "on")


@pytest.mark.integration
def test_freecrypto_vs_coingecko_current_within_tolerance():
    """
    Сверка текущих котировок: отклонение цены < 3 % (plan01 §11.2).
    При заполненных market_cap / volume в обоих ответах — то же для капа и объёма.
    """
    if not _coingecko_verify_enabled():
        pytest.skip("включите COINGECKO_VERIFY=1 (см. .env.example, plan01 §12)")
    token = os.environ.get("FREECRYPTO_API_TOKEN", "").strip()
    if not token:
        pytest.skip("нужен FREECRYPTO_API_TOKEN для primary freecrypto")

    fc = FreeCryptoDataSource()
    cg = CoinGeckoMarketDataSource()
    a = fc.get_current("BTC")
    b = cg.get_current("BTC")

    assert a.get("price", 0) > 0 and b.get("price", 0) > 0
    rel_p = abs(float(a["price"]) - float(b["price"])) / float(b["price"])
    assert rel_p < 0.03, f"цена: отклонение {rel_p:.2%} (порог 3 %) freecrypto={a['price']} cg={b['price']}"

    cap_a, cap_b = a.get("market_cap"), b.get("market_cap")
    if cap_a and cap_b and float(cap_b) > 0:
        rel_c = abs(float(cap_a) - float(cap_b)) / float(cap_b)
        assert rel_c < 0.03, f"market_cap: отклонение {rel_c:.2%}"

    vol_a, vol_b = a.get("volume"), b.get("volume")
    if vol_a is not None and vol_b is not None and float(vol_b) > 0:
        rel_v = abs(float(vol_a) - float(vol_b)) / float(vol_b)
        assert rel_v < 0.03, f"volume: отклонение {rel_v:.2%}"
