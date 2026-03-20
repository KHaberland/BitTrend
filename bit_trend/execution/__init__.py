"""Исполнение сделок (P3): MVP-логирование по умолчанию, опционально ccxt."""

from bit_trend.execution.ccxt_executor import (
    ExecutionResult,
    execute_rebalance_part,
    is_live_trading_enabled,
    live_trading_status_message,
)

__all__ = [
    "ExecutionResult",
    "execute_rebalance_part",
    "is_live_trading_enabled",
    "live_trading_status_message",
]
