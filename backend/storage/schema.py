from __future__ import annotations

import sqlite3
import time
import threading
from pathlib import Path


DB_PATH = Path("data") / "nexus.db"
_local = threading.local()


def get_conn() -> sqlite3.Connection:
    existing = getattr(_local, "_conn", None)
    if existing is not None:
        try:
            existing.execute("SELECT 1")
            return existing
        except sqlite3.Error:
            pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    _local._conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            exit_price REAL NOT NULL,
            risk_reward REAL NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            exit_timestamp INTEGER,
            institutional_score REAL DEFAULT 0,
            liquidity_score REAL DEFAULT 0,
            bias_score REAL DEFAULT 0,
            expected_move REAL DEFAULT 0,
            win_probability REAL DEFAULT 0,
            kelly_fraction REAL DEFAULT 0,
            suggested_risk_fraction REAL DEFAULT 0,
            cvar95_loss REAL DEFAULT 0,
            risk_of_ruin REAL DEFAULT 0,
            trailing_stop REAL,
            trailing_mode TEXT DEFAULT 'atr_chandelier',
            model TEXT DEFAULT 'institutional-v2',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY,
            signal_id TEXT REFERENCES signals(id),
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            quantity REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at INTEGER NOT NULL,
            closed_at INTEGER,
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            risk_reward REAL,
            confidence REAL,
            reason TEXT,
            close_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS backtest_runs (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            start_date INTEGER NOT NULL,
            end_date INTEGER NOT NULL,
            candle_count INTEGER NOT NULL,
            initial_balance REAL DEFAULT 10000,
            final_balance REAL,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            total_pnl_pct REAL DEFAULT 0,
            max_drawdown REAL DEFAULT 0,
            max_drawdown_pct REAL DEFAULT 0,
            sharpe_ratio REAL,
            win_rate REAL,
            avg_win REAL,
            avg_loss REAL,
            profit_factor REAL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS backtest_trades (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES backtest_runs(id),
            signal_id TEXT,
            timestamp INTEGER NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stop_loss REAL NOT NULL,
            exit_price REAL NOT NULL,
            exit_timestamp INTEGER,
            pnl REAL,
            pnl_pct REAL,
            risk_reward REAL,
            confidence REAL,
            reason TEXT,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS equity_curve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            account_balance REAL NOT NULL,
            drawdown REAL DEFAULT 0,
            drawdown_pct REAL DEFAULT 0,
            source TEXT NOT NULL,
            run_id TEXT REFERENCES backtest_runs(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            timestamp INTEGER NOT NULL,
            type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            symbol TEXT,
            title TEXT NOT NULL,
            message TEXT,
            data JSON,
            acknowledged INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trade_journal_entries (
            id TEXT PRIMARY KEY,
            paper_trade_id TEXT REFERENCES paper_trades(id),
            timestamp INTEGER NOT NULL,
            entry_type TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
        CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
        CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
        CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
        CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);
        CREATE INDEX IF NOT EXISTS idx_backtest_runs_symbol ON backtest_runs(symbol);
        CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(type);
        CREATE INDEX IF NOT EXISTS idx_equity_curve_timestamp ON equity_curve(timestamp);
        """)
        conn.commit()
    finally:
        conn.close()
