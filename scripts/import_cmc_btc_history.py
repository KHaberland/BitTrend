"""
Бэкфилл market_data из CoinMarketCap OHLCV (plan_change §3).

PowerShell:
  Set-Location D:\\CursorAI\\BitTrend
  $env:CMC_API_KEY = "ключ"
  python scripts\\import_cmc_btc_history.py
  python scripts\\import_cmc_btc_history.py --days 180
"""
from __future__ import annotations

import argparse
import logging
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    from bit_trend.data.coinmarketcap_history import sync_btc_from_cmc

    p = argparse.ArgumentParser(description="Импорт дневных котировок BTC (CMC) в SQLite market_data")
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Глубина в днях (иначе CMC_OHLCV_HISTORY_DAYS → ONCHAIN_PROXY_HISTORY_DAYS → 730)",
    )
    args = p.parse_args()
    try:
        n = sync_btc_from_cmc(days_back=args.days)
    except ValueError as e:
        logging.error("%s", e)
        return 1
    print(f"OK: записано строк: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
