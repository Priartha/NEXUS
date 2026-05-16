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

        -- ═══════════════════════════════════════════════════
        -- HISTORICAL DATA STORAGE
        -- ═══════════════════════════════════════════════════

        -- Market snapshots: periodic full-state captures
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            price REAL NOT NULL,
            change_pct REAL DEFAULT 0,
            regime_phase TEXT,
            regime_bias TEXT,
            regime_confidence REAL,
            ai_direction TEXT,
            ai_grade TEXT,
            ai_confidence REAL,
            pattern_count INTEGER DEFAULT 0,
            bullish_patterns INTEGER DEFAULT 0,
            bearish_patterns INTEGER DEFAULT 0,
            active_fvgs INTEGER DEFAULT 0,
            active_order_blocks INTEGER DEFAULT 0,
            active_liquidity_levels INTEGER DEFAULT 0,
            sentiment_label TEXT,
            sentiment_score REAL,
            rsi14 REAL,
            atr14 REAL,
            vwap REAL,
            trend_score REAL,
            volume_zscore REAL,
            candle_count INTEGER DEFAULT 0,
            session TEXT,
            halving_phase TEXT,
            volatility_regime TEXT,
            raw_data JSON
        );

        -- Pattern history: tracks every detected pattern over time
        CREATE TABLE IF NOT EXISTS pattern_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            pattern_id TEXT NOT NULL,
            name TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            score REAL NOT NULL,
            description TEXT,
            candle_count INTEGER,
            completed INTEGER DEFAULT 0,
            symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
            timeframe TEXT NOT NULL DEFAULT '5m',
            session TEXT,
            regime_phase TEXT
        );

        -- Regime history: tracks regime changes over time
        CREATE TABLE IF NOT EXISTS regime_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            phase TEXT NOT NULL,
            bias TEXT NOT NULL,
            confidence REAL NOT NULL,
            range_high REAL,
            range_low REAL,
            range_mid REAL,
            width_pct REAL,
            atr_compression REAL,
            efficiency_ratio REAL,
            volume_state TEXT,
            reason TEXT
        );

        -- Metrics history: periodic market metrics snapshots
        CREATE TABLE IF NOT EXISTS metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            price REAL,
            atr14 REAL,
            ema20 REAL,
            ema50 REAL,
            rsi14 REAL,
            vwap REAL,
            vwap_distance_pct REAL,
            volume_zscore REAL,
            realized_volatility REAL,
            trend_score REAL,
            volatility_score REAL,
            institutional_bias TEXT,
            bias_score REAL,
            expected_move REAL,
            hurst_exponent REAL,
            shannon_entropy REAL,
            garch_volatility REAL,
            kalman_trend_strength REAL,
            markov_bull_prob REAL,
            markov_bear_prob REAL,
            monte_carlo_var95 REAL,
            fourier_dominant_period REAL,
            volume_profile_poc REAL,
            volume_profile_imbalance REAL,
            return_skewness REAL,
            return_kurtosis REAL,
            fractal_dimension REAL
        );

        -- Candle archive: stores closed candles for historical replay
        CREATE TABLE IF NOT EXISTS candle_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            is_closed INTEGER NOT NULL DEFAULT 1,
            UNIQUE(timestamp, symbol, timeframe)
        );

        -- AI ICT decisions history
        CREATE TABLE IF NOT EXISTS ai_decisions_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            direction TEXT,
            grade TEXT,
            readiness TEXT,
            confidence REAL,
            setup_score REAL,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            risk_reward REAL,
            summary TEXT,
            confirmations JSON,
            blockers JSON,
            calculations JSON,
            momentum_score REAL,
            option_symbol TEXT
        );

        -- Liquidity history: tracks liquidity events over time
        CREATE TABLE IF NOT EXISTS liquidity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            side TEXT NOT NULL,
            swept_level REAL,
            sweep_price REAL,
            close_price REAL,
            sweep_depth REAL,
            displacement REAL,
            reclaimed INTEGER DEFAULT 0,
            engineered_score REAL,
            reason TEXT,
            level_kind TEXT,
            level_price REAL,
            touch_count INTEGER
        );

        -- Orderbook history: periodic orderbook state snapshots
        CREATE TABLE IF NOT EXISTS orderbook_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            bid REAL,
            ask REAL,
            spread REAL,
            spread_pct REAL,
            mid REAL,
            imbalance_count INTEGER DEFAULT 0,
            accumulation_count INTEGER DEFAULT 0,
            spread_anomaly_count INTEGER DEFAULT 0,
            raw_imbalances JSON,
            raw_accumulations JSON
        );

        -- Performance analytics: aggregated daily/weekly/monthly stats
        CREATE TABLE IF NOT EXISTS performance_daily (
            date TEXT PRIMARY KEY,
            symbol TEXT NOT NULL DEFAULT 'BTCUSDT',
            total_signals INTEGER DEFAULT 0,
            bullish_signals INTEGER DEFAULT 0,
            bearish_signals INTEGER DEFAULT 0,
            avg_signal_confidence REAL,
            total_paper_trades INTEGER DEFAULT 0,
            paper_wins INTEGER DEFAULT 0,
            paper_losses INTEGER DEFAULT 0,
            paper_pnl REAL DEFAULT 0,
            paper_win_rate REAL,
            avg_regime TEXT,
            dominant_pattern TEXT,
            avg_atr REAL,
            avg_rsi REAL,
            max_drawdown_pct REAL,
            raw_data JSON
        );

        -- Indexes for historical tables
        CREATE INDEX IF NOT EXISTS idx_market_snapshots_timestamp ON market_snapshots(timestamp);
        CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol ON market_snapshots(symbol);
        CREATE INDEX IF NOT EXISTS idx_pattern_history_timestamp ON pattern_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_pattern_history_name ON pattern_history(name);
        CREATE INDEX IF NOT EXISTS idx_regime_history_timestamp ON regime_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_regime_history_phase ON regime_history(phase);
        CREATE INDEX IF NOT EXISTS idx_metrics_history_timestamp ON metrics_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_candle_archive_timestamp ON candle_archive(timestamp);
        CREATE INDEX IF NOT EXISTS idx_candle_archive_symbol_tf ON candle_archive(symbol, timeframe, timestamp);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_timestamp ON ai_decisions_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_ai_decisions_grade ON ai_decisions_history(grade);
        CREATE INDEX IF NOT EXISTS idx_liquidity_history_timestamp ON liquidity_history(timestamp);
        CREATE INDEX IF NOT EXISTS idx_orderbook_history_timestamp ON orderbook_history(timestamp);

        -- Daily reports: automated daily summary reports
        CREATE TABLE IF NOT EXISTS daily_reports (
            date TEXT PRIMARY KEY,
            generated_at INTEGER NOT NULL,
            report_data JSON NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports(date);
        """)
        conn.commit()
    finally:
        conn.close()
