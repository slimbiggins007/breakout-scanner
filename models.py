"""
Database models — defines the schema for scan results and trade tracking.
"""

# Schema definitions used by db.py
# Using raw SQL with sqlite3 for simplicity (no ORM dependency).

SCAN_RESULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    sector TEXT NOT NULL,
    setup_type INTEGER NOT NULL,
    setup_name TEXT NOT NULL,
    score INTEGER NOT NULL,
    status TEXT NOT NULL,
    price_at_scan REAL NOT NULL,
    change_pct REAL,
    breakout_triggered INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    criteria_json TEXT,
    iv_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

TRADE_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_result_id INTEGER REFERENCES scan_results(id),
    ticker TEXT NOT NULL,
    entry_date TEXT,
    entry_price REAL,
    exit_date TEXT,
    exit_price REAL,
    pnl_pct REAL,
    outcome TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

# Index for faster queries
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_scan_date ON scan_results(scan_date);",
    "CREATE INDEX IF NOT EXISTS idx_ticker ON scan_results(ticker);",
    "CREATE INDEX IF NOT EXISTS idx_status ON scan_results(status);",
    "CREATE INDEX IF NOT EXISTS idx_score ON scan_results(score);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_scan_date_ticker ON scan_results(scan_date, ticker);",
]
