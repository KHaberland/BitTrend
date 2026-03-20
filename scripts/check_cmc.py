"""Проверка CoinMarketCap Pro: quotes/latest и ohlcv/historical (без вывода ключа).
Запуск из корня репозитория:

  Set-Location D:\\CursorAI\\BitTrend
  python scripts\\check_cmc.py
"""
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

from bit_trend.data.market_coinmarketcap import CoinMarketCapDataSource
from bit_trend.data.market_source import build_market_history


def main() -> None:
    k = (os.getenv("CMC_API_KEY") or "").strip()
    print("CMC_API_KEY задан:" if k else "CMC_API_KEY нет:", "длина =", len(k))
    if not k:
        print("Добавьте ключ в .env (CMC_API_KEY) и перезапустите.")
        print("План: https://coinmarketcap.com/api/documentation/v1/ — endpoints quotes/latest, ohlcv/historical.")
        return
    cmc = CoinMarketCapDataSource()
    try:
        row = cmc.get_current("BTC")
        print("get_current: OK | source =", row.get("source"), "| price =", row.get("price"))
    except Exception as e:
        print("get_current: ошибка:", type(e).__name__, str(e))
    try:
        df = cmc.get_history("BTC", 35)
        print("get_history(35d): строк =", len(df))
    except Exception as e:
        print("get_history: ошибка:", type(e).__name__, str(e))
    try:
        os.environ.setdefault("MARKET_DATA_PRIMARY", "cmc")
        h = build_market_history("BTC", 365)
        print("build_market_history(365d): строк =", len(h))
    except Exception as e:
        print("build_market_history: ошибка:", type(e).__name__, str(e))


if __name__ == "__main__":
    main()
