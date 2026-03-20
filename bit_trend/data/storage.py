"""
Time-series storage для он-чейн метрик.
Графики, backtesting, сигналы.
"""

import csv
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
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

CREATE TABLE IF NOT EXISTS signal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    score REAL NOT NULL,
    signal TEXT NOT NULL,
    btc_price REAL,
    usdt REAL,
    btc_amount REAL,
    deviation_usdt REAL,
    recommendation TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_created ON signal_history(created_at);
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


def get_history(limit: int = 1000, source_contains: Optional[str] = None) -> List[Dict[str, Any]]:
    """История для графиков, backtesting и detect_drift (S3): source_contains — фильтр по подстроке source."""
    init_db()
    conn = _get_conn()
    try:
        if source_contains:
            rows = conn.execute(
                """
                SELECT timestamp, mvrv, nupl, sopr, source, confidence
                FROM onchain_history
                WHERE source LIKE ?
                ORDER BY id DESC LIMIT ?
                """,
                (f"%{source_contains}%", limit),
            ).fetchall()
        else:
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


def _parse_iso_utc(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _row_to_signal_display(row: sqlite3.Row) -> Dict[str, Any]:
    """Строка БД → словарь для UI/CSV (плоские имена)."""
    ca = row["created_at"]
    ts_disp = ca
    if "T" in ca:
        ts_disp = ca.replace("T", " ")[:16]
    return {
        "timestamp": ts_disp,
        "score": row["score"],
        "signal": row["signal"],
        "btc_price": row["btc_price"],
        "usdt": row["usdt"],
        "btc_amount": row["btc_amount"],
        "deviation_usdt": row["deviation_usdt"],
        "recommendation": row["recommendation"],
    }


def _signal_rows_match_for_dedupe(a: sqlite3.Row, b_score: float, b_signal: str, b_price: Optional[float], b_usdt: float, b_btc: float, b_dev: float) -> bool:
    if a["signal"] != b_signal:
        return False
    if abs(float(a["score"]) - float(b_score)) > 1e-6:
        return False
    ap, bp = a["btc_price"], b_price
    if ap is None and bp is None:
        pass
    elif ap is None or bp is None:
        return False
    elif abs(float(ap) - float(bp)) > 1.0:
        return False
    au, bu = a["usdt"], b_usdt
    if au is not None and bu is not None and abs(float(au) - float(bu)) > 0.01:
        return False
    if au is None and bu is not None or au is not None and bu is None:
        return False
    abtc, bbtc = a["btc_amount"], b_btc
    if abtc is not None and bbtc is not None and abs(float(abtc) - float(bbtc)) > 1e-6:
        return False
    if (abtc is None) != (bbtc is None):
        return False
    ad, bd = a["deviation_usdt"], b_dev
    if (ad is None) != (bd is None):
        return False
    if ad is not None and bd is not None and abs(float(ad) - float(bd)) > 0.5:
        return False
    return True


def append_signal_history(
    *,
    score: float,
    signal: str,
    btc_price: Optional[float],
    usdt: float,
    btc_amount: float,
    deviation_usdt: float,
    recommendation: str,
    dedupe_within_seconds: int = 90,
) -> bool:
    """
    Добавить запись в историю сигналов (P1). Дедупликация: повтор с теми же
    score/signal/ценой/портфелем в дефолтном окне 90 с — не пишем второй раз.
    Опционально дублировать строку в CSV: переменная BITTREND_SIGNAL_CSV_PATH.
    """
    init_db()
    now = datetime.now(timezone.utc)
    created_iso = now.isoformat()

    conn = _get_conn()
    try:
        if dedupe_within_seconds > 0:
            last = conn.execute(
                """
                SELECT created_at, score, signal, btc_price, usdt, btc_amount, deviation_usdt
                FROM signal_history ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
            if last:
                prev_t = _parse_iso_utc(last["created_at"])
                if prev_t is not None:
                    if prev_t.tzinfo is None:
                        prev_t = prev_t.replace(tzinfo=timezone.utc)
                    else:
                        prev_t = prev_t.astimezone(timezone.utc)
                    if (now - prev_t) <= timedelta(seconds=dedupe_within_seconds):
                        if _signal_rows_match_for_dedupe(
                            last, score, signal, btc_price, usdt, btc_amount, deviation_usdt
                        ):
                            return False

        conn.execute(
            """
            INSERT INTO signal_history (
                created_at, score, signal, btc_price, usdt, btc_amount, deviation_usdt, recommendation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_iso,
                score,
                signal,
                btc_price,
                usdt,
                btc_amount,
                deviation_usdt,
                recommendation,
            ),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"append_signal_history: {e}")
        return False
    finally:
        conn.close()

    csv_path_raw = os.environ.get("BITTREND_SIGNAL_CSV_PATH", "").strip()
    if csv_path_raw:
        csv_path = Path(csv_path_raw)
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = [
                "created_at", "score", "signal", "btc_price", "usdt", "btc_amount",
                "deviation_usdt", "recommendation",
            ]
            row = {
                "created_at": created_iso,
                "score": score,
                "signal": signal,
                "btc_price": btc_price,
                "usdt": usdt,
                "btc_amount": btc_amount,
                "deviation_usdt": deviation_usdt,
                "recommendation": recommendation,
            }
            new_file = not csv_path.exists()
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                if new_file:
                    w.writeheader()
                w.writerow(row)
        except Exception as e:
            logger.warning(f"signal_history CSV mirror: {e}")

    return True


def get_signal_history(limit: int = 500) -> List[Dict[str, Any]]:
    """Последние N записей, хронологически от старых к новым (удобно для таблицы в UI)."""
    if limit < 1:
        return []
    init_db()
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT created_at, score, signal, btc_price, usdt, btc_amount, deviation_usdt, recommendation
            FROM signal_history ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = [_row_to_signal_display(r) for r in reversed(rows)]
        return out
    finally:
        conn.close()
