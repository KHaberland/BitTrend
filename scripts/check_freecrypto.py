"""Одноразовая проверка FreeCrypto (без вывода токена).
Запуск из корня репозитория: python scripts/check_freecrypto.py"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from bit_trend.config.loader import _try_load_dotenv

_try_load_dotenv()
try:
    from dotenv import load_dotenv

    load_dotenv(_root / ".env")
except ImportError:
    pass

import os

from bit_trend.data.freecrypto import FreeCryptoDataSource
from bit_trend.data.market_source import build_market_history


def main() -> None:
    t = (os.getenv("FREECRYPTO_API_TOKEN") or "").strip()
    print("FREECRYPTO_API_TOKEN zadan:" if t else "FREECRYPTO_API_TOKEN net:", "dlina =", len(t))
    if not t:
        print("Dobavte token v .env i perezapustite.")
        return
    fc = FreeCryptoDataSource()
    try:
        row = fc.get_current("BTC")
        print("get_current: OK | source =", row.get("source"), "| price =", row.get("price"))
    except Exception as e:
        print("get_current: oshibka:", type(e).__name__, str(e))
    try:
        df = fc.get_history("BTC", 30)
        print("get_history(30d): strok =", len(df))
    except Exception as e:
        print("get_history: oshibka:", type(e).__name__, str(e))
    try:
        h = build_market_history("BTC", 365)
        print("build_market_history(365d): strok =", len(h))
    except Exception as e:
        print("build_market_history: oshibka:", type(e).__name__, str(e))


if __name__ == "__main__":
    main()
