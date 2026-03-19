"""
Time-series storage для он-чейн метрик.
Графики, backtesting, сигналы.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Путь к БД (рядом с проектом)
_default_db = Path(__file__).resolve().parent.parent.parent / "data" / "bittrend.db"
DB_PATH = Path(os.environ["BITTREND_DB_PATH"]) if os.environ.get("BITTREND_DB_PATH") else _default_db
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS onchain_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mvrv REAL,
    nupl REAL,
    sopr REAL,
    source TEXT,
    confidence REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_onchain_timestamp ON onchain_history(timestamp);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создать таблицу при первом запуске."""
    conn = _get_conn()
    try:
        conn.executescript(CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def _is_same(prev: Optional[float], current: Optional[float], eps: float = 1e-6) -> bool:
    """Deduplication: не писать в БД одно и то же."""
    if prev is None and current is None:
        return True
    if prev is None or current is None:
        return False
    return abs(prev - current) < eps


def save_history(data: Dict[str, Any], eps: float = 1e-6) -> bool:
    """
    Записать в историю, если значение изменилось (deduplication).
    Returns True если запись выполнена.
    """
    prev = get_last_history()
    mvrv = data.get("mvrv_z_score")
    nupl = data.get("nupl")
    sopr = data.get("sopr")

    # Deduplication: не писать одно и то же
    if prev:
        if (
            _is_same(prev.get("mvrv_z_score"), mvrv, eps)
            and _is_same(prev.get("nupl"), nupl, eps)
            and _is_same(prev.get("sopr"), sopr, eps)
        ):
            return False

    if mvrv is None and nupl is None and sopr is None:
        return False

    init_db()
    conn = _get_conn()
    try:
        ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO onchain_history (timestamp, mvrv, nupl, sopr, source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ts,
                mvrv,
                nupl,
                sopr,
                data.get("source", ""),
                data.get("confidence", 0),
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.warning(f"save_history: {e}")
        return False
    finally:
        conn.close()


def get_last_history() -> Optional[Dict[str, Any]]:
    """Последняя запись — last_known_good_value."""
    init_db()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT timestamp, mvrv, nupl, sopr, source, confidence FROM onchain_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            return {
                "timestamp": row["timestamp"],
                "mvrv_z_score": row["mvrv"],
                "nupl": row["nupl"],
                "sopr": row["sopr"],
                "source": row["source"],
                "confidence": row["confidence"],
            }
        return None
    finally:
        conn.close()


def get_history(limit: int = 1000) -> List[Dict[str, Any]]:
    """История для графиков, backtesting."""
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT timestamp, mvrv, nupl, sopr, source, confidence
            FROM onchain_history ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "timestamp": r["timestamp"],
                "mvrv_z_score": r["mvrv"],
                "nupl": r["nupl"],
                "sopr": r["sopr"],
                "source": r["source"],
                "confidence": r["confidence"],
            }
            for r in rows
        ]
    finally:
        conn.close()
