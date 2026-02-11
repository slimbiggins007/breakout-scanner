"""
Database setup and query layer.
Stores scan results in SQLite for history tracking and win/loss analysis.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import config
from models import SCAN_RESULT_SCHEMA, TRADE_LOG_SCHEMA, INDEXES

DB_PATH = Path(__file__).parent / config.DB_PATH


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and indexes if they don't exist."""
    conn = get_connection()
    conn.execute(SCAN_RESULT_SCHEMA)
    conn.execute(TRADE_LOG_SCHEMA)
    for idx in INDEXES:
        conn.execute(idx)
    conn.commit()
    conn.close()


def clear_today():
    """Delete any existing results for today so re-runs don't create duplicates."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM scan_results WHERE scan_date = ?", (today,))
    conn.commit()
    conn.close()


def save_scan_result(result: dict):
    """Save a single scan result to the database."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO scan_results
           (scan_date, ticker, sector, setup_type, setup_name, score, status,
            price_at_scan, change_pct, breakout_triggered, note, criteria_json, iv_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            result["ticker"],
            result["sector"],
            result["setup_type"],
            result["setup_name"],
            result["score"],
            result["status"],
            result["price"],
            result.get("change_pct", 0),
            int(result.get("breakout_triggered", False)),
            result.get("note", ""),
            json.dumps({k: bool(v) for k, v in result.get("criteria_summary", {}).items()}),
            json.dumps(result.get("iv_info", {})),
        ),
    )
    conn.commit()
    conn.close()


def _parse_json_fields(rows: list[dict]) -> list[dict]:
    """Parse JSON fields (criteria, IV) back to dicts."""
    for row in rows:
        try:
            row["criteria_summary"] = json.loads(row.get("criteria_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            row["criteria_summary"] = {}
        try:
            row["iv_info"] = json.loads(row.get("iv_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            row["iv_info"] = {}
    return rows


def get_latest_scan() -> list[dict]:
    """Get all results from the most recent scan date."""
    conn = get_connection()
    cursor = conn.execute(
        """SELECT * FROM scan_results
           WHERE scan_date = (SELECT MAX(scan_date) FROM scan_results)
           ORDER BY score DESC"""
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return _parse_json_fields(rows)


def get_scan_history(ticker: str | None = None, days: int = 30) -> list[dict]:
    """Get scan history, optionally filtered by ticker."""
    conn = get_connection()
    if ticker:
        cursor = conn.execute(
            """SELECT * FROM scan_results
               WHERE ticker = ? AND scan_date >= date('now', ?)
               ORDER BY scan_date DESC, score DESC""",
            (ticker, f"-{days} days"),
        )
    else:
        cursor = conn.execute(
            """SELECT * FROM scan_results
               WHERE scan_date >= date('now', ?)
               ORDER BY scan_date DESC, score DESC""",
            (f"-{days} days",),
        )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_scan_dates() -> list[str]:
    """Get all unique scan dates, most recent first."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT DISTINCT scan_date FROM scan_results ORDER BY scan_date DESC"
    )
    dates = [r["scan_date"] for r in cursor.fetchall()]
    conn.close()
    return dates


def get_scan_by_date(date: str) -> list[dict]:
    """Get all results for a specific scan date."""
    conn = get_connection()
    cursor = conn.execute(
        """SELECT * FROM scan_results
           WHERE scan_date = ?
           ORDER BY score DESC""",
        (date,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    _parse_json_fields(rows)
    return rows


def get_stats() -> dict:
    """Get aggregate stats for the dashboard header."""
    conn = get_connection()

    # Total scans
    total = conn.execute("SELECT COUNT(DISTINCT scan_date) as cnt FROM scan_results").fetchone()["cnt"]

    # Stats from latest scan
    latest = conn.execute(
        """SELECT
             COUNT(*) as total_hits,
             SUM(CASE WHEN status = 'READY' THEN 1 ELSE 0 END) as ready,
             SUM(CASE WHEN status = 'WATCH' THEN 1 ELSE 0 END) as watch,
             SUM(CASE WHEN status = 'BUILDING' THEN 1 ELSE 0 END) as building,
             SUM(CASE WHEN breakout_triggered = 1 THEN 1 ELSE 0 END) as breakouts
           FROM scan_results
           WHERE scan_date = (SELECT MAX(scan_date) FROM scan_results)"""
    ).fetchone()

    conn.close()
    return {
        "total_scan_days": total,
        "total_hits": latest["total_hits"] if latest else 0,
        "ready": latest["ready"] if latest else 0,
        "watch": latest["watch"] if latest else 0,
        "building": latest["building"] if latest else 0,
        "breakouts": latest["breakouts"] if latest else 0,
    }
