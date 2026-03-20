"""
P3: опциональное реальное исполнение через ccxt.

По умолчанию — только явное MVP-логирование (ордер не отправляется).
Включение live: BITTREND_LIVE_TRADING=true и BITTREND_LIVE_TRADING_ACK=YES,
ключи BITTREND_CCXT_* и установленный пакет ccxt.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class ExecutionResult:
    """Результат попытки исполнения части ребаланса."""

    mode: str  # "mvp" | "live"
    ok: bool
    message: str
    order: Optional[Dict[str, Any]] = None


def is_live_trading_enabled() -> bool:
    """Live только при явном ack и ключах (без ордеров, пока не задано)."""
    if not _truthy(os.getenv("BITTREND_LIVE_TRADING")):
        return False
    if (os.getenv("BITTREND_LIVE_TRADING_ACK") or "").strip() != "YES":
        return False
    key = (os.getenv("BITTREND_CCXT_API_KEY") or "").strip()
    secret = (os.getenv("BITTREND_CCXT_API_SECRET") or "").strip()
    return bool(key and secret)


def live_trading_status_message() -> str:
    """Короткая подсказка для UI: MVP или условия включения live."""
    if is_live_trading_enabled():
        ex = (os.getenv("BITTREND_CCXT_EXCHANGE") or "binance").strip().lower()
        sym = (os.getenv("BITTREND_CCXT_SYMBOL") or "BTC/USDT").strip()
        testnet = _truthy(os.getenv("BITTREND_CCXT_TESTNET"))
        return f"Режим **LIVE** ({ex}, {sym})" + (" — testnet/sandbox" if testnet else "")
    return "Режим **MVP**: только логирование, ордера не отправляются."


def _import_ccxt():  # pragma: no cover - import guard
    try:
        import ccxt  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Пакет ccxt не установлен. Выполните: pip install ccxt>=4.0.0"
        ) from e
    return ccxt


def _exchange_instance():
    ccxt = _import_ccxt()
    ex_id = (os.getenv("BITTREND_CCXT_EXCHANGE") or "binance").strip().lower()
    if not hasattr(ccxt, ex_id):
        raise ValueError(f"Неизвестная биржа для ccxt: {ex_id}")
    cls = getattr(ccxt, ex_id)
    key = os.getenv("BITTREND_CCXT_API_KEY", "").strip()
    secret = os.getenv("BITTREND_CCXT_API_SECRET", "").strip()
    password = (os.getenv("BITTREND_CCXT_PASSWORD") or "").strip() or None
    opts: Dict[str, Any] = {"apiKey": key, "secret": secret, "enableRateLimit": True}
    if password:
        opts["password"] = password
    ex = cls(opts)
    if _truthy(os.getenv("BITTREND_CCXT_TESTNET")):
        if hasattr(ex, "set_sandbox_mode"):
            ex.set_sandbox_mode(True)
    return ex


def _market_buy_quote(ex: Any, symbol: str, spend_usdt: float) -> Dict[str, Any]:
    """Купить BTC на сумму в котируемой валюте (USDT) — unified `cost` или quoteOrderQty."""
    spend_usdt = float(spend_usdt)
    if spend_usdt <= 0:
        raise ValueError("spend_usdt должен быть > 0")
    try:
        return ex.create_order(symbol, "market", "buy", None, None, {"cost": spend_usdt})
    except Exception:
        return ex.create_order(
            symbol,
            "market",
            "buy",
            spend_usdt,
            None,
            {"quoteOrderQty": spend_usdt},
        )


def _market_sell_base(ex: Any, symbol: str, usdt_notional: float, reference_btc_price: float) -> Dict[str, Any]:
    """Продать BTC примерно на usdt_notional (по reference цене → округление amount)."""
    if reference_btc_price <= 0:
        raise ValueError("reference_btc_price должен быть > 0")
    base_amt = float(usdt_notional) / float(reference_btc_price)
    base_amt = float(ex.amount_to_precision(symbol, base_amt))
    if base_amt <= 0:
        raise ValueError("После округления объём продажи 0")
    return ex.create_order(symbol, "market", "sell", base_amt)


def execute_rebalance_part(
    part_num: int,
    part_usdt: float,
    deviation_usdt: float,
    btc_price: float,
    *,
    onchain_drift_any: bool = False,
) -> ExecutionResult:
    """
    Исполнить одну часть ребаланса или залогировать MVP.

    deviation_usdt > 0 — докупка BTC; < 0 — продажа BTC.
    """
    part_usdt = float(part_usdt)
    dev = float(deviation_usdt)

    block_on_drift = _truthy(os.getenv("BITTREND_LIVE_BLOCK_ON_DRIFT", "true"))
    if onchain_drift_any and block_on_drift and is_live_trading_enabled():
        logger.warning(
            "[MVP] Live отключён для этой сессии: флаг ончейн-дрейфа (BITTREND_LIVE_BLOCK_ON_DRIFT). "
            f"Part {part_num}: {part_usdt:.2f} USDT — только логирование."
        )
        return ExecutionResult(
            mode="mvp",
            ok=True,
            message=(
                f"Part {part_num}: {part_usdt:,.2f} USDT — дрейф ончейна: live заблокирован, "
                "ордер не отправлен (см. BITTREND_LIVE_BLOCK_ON_DRIFT)."
            ),
        )

    if not is_live_trading_enabled():
        logger.info(
            f"[MVP] Execute Part {part_num}: {part_usdt:.2f} USDT "
            "(логирование, ордер не исполнен)"
        )
        return ExecutionResult(
            mode="mvp",
            ok=True,
            message=f"Part {part_num}: {part_usdt:,.0f} USDT — MVP: логирование, ордер не исполнен.",
        )

    symbol = (os.getenv("BITTREND_CCXT_SYMBOL") or "BTC/USDT").strip()
    if part_usdt <= 0:
        return ExecutionResult(mode="live", ok=False, message="Объём части должен быть > 0.")
    if btc_price <= 0:
        return ExecutionResult(mode="live", ok=False, message="Нет цены BTC — отказ от live-ордера.")

    if dev == 0:
        logger.info(f"[LIVE] deviation_usdt=0, Part {part_num} пропущен.")
        return ExecutionResult(
            mode="live",
            ok=True,
            message="Отклонение 0 — live-ордер не требуется.",
        )

    try:
        ex = _exchange_instance()
        ex.load_markets()
    except Exception as e:
        logger.exception("ccxt: не удалось подключиться к бирже")
        return ExecutionResult(mode="live", ok=False, message=f"Ошибка биржи: {e}")

    try:
        if dev > 0:
            order = _market_buy_quote(ex, symbol, part_usdt)
            side = "buy"
        else:
            order = _market_sell_base(ex, symbol, part_usdt, btc_price)
            side = "sell"
    except Exception as e:
        logger.exception("ccxt: ордер отклонён")
        return ExecutionResult(mode="live", ok=False, message=f"Ордер не принят: {e}")

    oid = order.get("id") or order.get("orderId") or order.get("info")
    logger.info(
        f"[LIVE] Execute Part {part_num}: {side} ~{part_usdt:.2f} USDT на {symbol}, order={oid!r}"
    )
    return ExecutionResult(
        mode="live",
        ok=True,
        message=f"Part {part_num}: live {side} ~{part_usdt:,.0f} USDT ({symbol}), id: {oid}",
        order=dict(order) if isinstance(order, dict) else {"raw": order},
    )
