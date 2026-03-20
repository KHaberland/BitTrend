"""
План plan_change.md §6.7–§6.8: смоук-тест цепочки рынка и прокси §8.10 (опционально с сетью).

  Set-Location D:\\CursorAI\\BitTrend
  python scripts\\verify_market_proxy_chain.py

Переменные: ``MARKET_DATA_PRIMARY``, ``MARKET_DATA_FALLBACK``, ``CMC_API_KEY``,
``USE_COINGECKO_ONCHAIN``, ``USE_CMC_ONCHAIN`` (см. `.env.example`).
"""
from __future__ import annotations

import os
import sys

# Windows-консоль (cp1252): печать Unicode без падения
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
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


def main() -> None:
    print("=== BitTrend: цепочка рынка + прокси §8.10 (plan_change §6.7–8) ===")
    print(
        "MARKET_DATA_PRIMARY =",
        repr(os.environ.get("MARKET_DATA_PRIMARY", "")),
        "| MARKET_DATA_FALLBACK =",
        repr(os.environ.get("MARKET_DATA_FALLBACK", "")),
    )
    print(
        "USE_COINGECKO_ONCHAIN =",
        os.environ.get("USE_COINGECKO_ONCHAIN", "true"),
        "| USE_CMC_ONCHAIN =",
        os.environ.get("USE_CMC_ONCHAIN", "false"),
    )

    from bit_trend.data.market_source import build_market_history, get_market_current_with_fallback

    row = get_market_current_with_fallback("BTC", use_cache=False)
    if row:
        print(
            "get_market_current_with_fallback: OK | source =",
            row.get("source"),
            "| price =",
            row.get("price"),
        )
    else:
        print("get_market_current_with_fallback: нет данных (проверьте ключи и fallback)")

    try:
        h = build_market_history("BTC", 400)
        print("build_market_history(400d): строк =", len(h))
        if not h.empty:
            print("  первая/последняя метка времени:", h["timestamp"].iloc[0], "…", h["timestamp"].iloc[-1])
    except Exception as e:
        print("build_market_history: ошибка:", type(e).__name__, e)

    from bit_trend.data import coingecko_onchain as cg

    prov = cg._proxy_provenance_for_primary()
    print("provenance §8.10:", prov)

    if cg.USE_COINGECKO_ONCHAIN:
        bundle = cg.get_coingecko_810_bundle(force_refresh=True)
        if bundle:
            print(
                "get_coingecko_810_bundle: OK | mvrv_z_score =",
                bundle.get("mvrv_z_score"),
                "| source =",
                bundle.get("source"),
                "| parser =",
                bundle.get("parser_version"),
            )
        else:
            print("get_coingecko_810_bundle: None (мало истории или USE_COINGECKO_ONCHAIN / ряд пуст)")
    else:
        print("get_coingecko_810_bundle: пропущено (USE_COINGECKO_ONCHAIN=false)")

    try:
        from bit_trend.data.onchain import get_btc_onchain

        oc = get_btc_onchain() or {}
        triplet_ok = all(oc.get(k) is not None for k in ("mvrv_z_score", "nupl", "sopr"))
        print(
            "get_btc_onchain: triplet полный =" if triplet_ok else "get_btc_onchain: triplet неполный —",
            triplet_ok,
            "| onchain_source =",
            oc.get("onchain_source"),
        )
    except Exception as e:
        print("get_btc_onchain: ошибка:", type(e).__name__, e)

    print("Готово.")


if __name__ == "__main__":
    main()
