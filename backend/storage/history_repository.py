from __future__ import annotations

import json
import time
from typing import Any

from backend.storage.schema import get_conn
from backend.analysis.data_quality import symbol_aliases


# ─── Market Snapshots ─────────────────────────────────────

def save_market_snapshot(data: dict) -> None:
    """Save a complete market state snapshot."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO market_snapshots
            (timestamp, symbol, timeframe, price, change_pct,
             regime_phase, regime_bias, regime_confidence,
             ai_direction, ai_grade, ai_confidence,
             pattern_count, bullish_patterns, bearish_patterns,
             active_fvgs, active_order_blocks, active_liquidity_levels,
             sentiment_label, sentiment_score,
             rsi14, atr14, vwap, trend_score, volume_zscore,
             candle_count, session, halving_phase, volatility_regime,
             raw_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("timestamp", int(time.time() * 1000)),
            data.get("symbol", "BTCUSDT"),
            data.get("timeframe", "5m"),
            data.get("price", 0),
            data.get("change_pct", 0),
            data.get("regime_phase"),
            data.get("regime_bias"),
            data.get("regime_confidence"),
            data.get("ai_direction"),
            data.get("ai_grade"),
            data.get("ai_confidence"),
            data.get("pattern_count", 0),
            data.get("bullish_patterns", 0),
            data.get("bearish_patterns", 0),
            data.get("active_fvgs", 0),
            data.get("active_order_blocks", 0),
            data.get("active_liquidity_levels", 0),
            data.get("sentiment_label"),
            data.get("sentiment_score"),
            data.get("rsi14"),
            data.get("atr14"),
            data.get("vwap"),
            data.get("trend_score"),
            data.get("volume_zscore"),
            data.get("candle_count", 0),
            data.get("session"),
            data.get("halving_phase"),
            data.get("volatility_regime"),
            json.dumps(data.get("raw_data", {})) if data.get("raw_data") else None,
        ))
        conn.commit()
    finally:
        conn.close()


def get_market_snapshots(
    symbol: str | None = None,
    timeframe: str | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query market snapshots with filters."""
    conn = get_conn()
    try:
        query = "SELECT * FROM market_snapshots WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if timeframe:
            query += " AND timeframe=?"
            params.append(timeframe)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        if end_ts:
            query += " AND timestamp<=?"
            params.append(end_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("raw_data"):
                try:
                    d["raw_data"] = json.loads(d["raw_data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


# ─── Pattern History ──────────────────────────────────────

def save_pattern(pattern: dict) -> None:
    """Save a detected pattern to history."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO pattern_history
            (timestamp, pattern_id, name, direction, confidence, score,
             description, candle_count, completed, symbol, timeframe,
             session, regime_phase)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pattern.get("timestamp", int(time.time() * 1000)),
            pattern["id"],
            pattern["name"],
            pattern["direction"],
            pattern["confidence"],
            pattern["score"],
            pattern.get("description", ""),
            pattern.get("candle_count", 0),
            1 if pattern.get("completed") else 0,
            pattern.get("symbol", "BTCUSDT"),
            pattern.get("timeframe", "5m"),
            pattern.get("session"),
            pattern.get("regime_phase"),
        ))
        conn.commit()
    finally:
        conn.close()


def get_pattern_history(
    name: str | None = None,
    direction: str | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query pattern history with filters."""
    conn = get_conn()
    try:
        query = "SELECT * FROM pattern_history WHERE 1=1"
        params: list[Any] = []
        if name:
            query += " AND name=?"
            params.append(name)
        if direction:
            query += " AND direction=?"
            params.append(direction)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        if end_ts:
            query += " AND timestamp<=?"
            params.append(end_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pattern_stats(days: int = 7) -> dict:
    """Get pattern statistics over recent days."""
    conn = get_conn()
    try:
        cutoff = int(time.time() * 1000) - (days * 24 * 60 * 60 * 1000)
        total = conn.execute(
            "SELECT COUNT(*) FROM pattern_history WHERE timestamp>=?", (cutoff,)
        ).fetchone()[0]
        bullish = conn.execute(
            "SELECT COUNT(*) FROM pattern_history WHERE timestamp>=? AND direction='bullish'", (cutoff,)
        ).fetchone()[0]
        bearish = conn.execute(
            "SELECT COUNT(*) FROM pattern_history WHERE timestamp>=? AND direction='bearish'", (cutoff,)
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM pattern_history WHERE timestamp>=? AND completed=1", (cutoff,)
        ).fetchone()[0]
        avg_conf = conn.execute(
            "SELECT AVG(confidence) FROM pattern_history WHERE timestamp>=?", (cutoff,)
        ).fetchone()[0] or 0
        avg_score = conn.execute(
            "SELECT AVG(score) FROM pattern_history WHERE timestamp>=?", (cutoff,)
        ).fetchone()[0] or 0

        top_patterns = conn.execute("""
            SELECT name, direction, COUNT(*) as count, AVG(confidence) as avg_conf
            FROM pattern_history WHERE timestamp>=?
            GROUP BY name ORDER BY count DESC LIMIT 10
        """, (cutoff,)).fetchall()

        return {
            "total_patterns": total,
            "bullish_patterns": bullish,
            "bearish_patterns": bearish,
            "completed_patterns": completed,
            "avg_confidence": round(avg_conf, 3),
            "avg_score": round(avg_score, 3),
            "top_patterns": [dict(r) for r in top_patterns],
        }
    finally:
        conn.close()


# ─── Regime History ───────────────────────────────────────

def save_regime(regime: dict) -> None:
    """Save a regime state to history."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO regime_history
            (timestamp, symbol, timeframe, phase, bias, confidence,
             range_high, range_low, range_mid, width_pct,
             atr_compression, efficiency_ratio, volume_state, reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            regime.get("timestamp", int(time.time() * 1000)),
            regime.get("symbol", "BTCUSDT"),
            regime.get("timeframe", "5m"),
            regime["phase"],
            regime["bias"],
            regime["confidence"],
            regime.get("range_high"),
            regime.get("range_low"),
            regime.get("range_mid"),
            regime.get("width_pct"),
            regime.get("atr_compression"),
            regime.get("efficiency_ratio"),
            regime.get("volume_state"),
            regime.get("reason", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def get_regime_history(
    symbol: str | None = None,
    start_ts: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query regime history."""
    conn = get_conn()
    try:
        query = "SELECT * FROM regime_history WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_regime_distribution(days: int = 7) -> dict:
    """Get regime phase distribution over recent days."""
    conn = get_conn()
    try:
        cutoff = int(time.time() * 1000) - (days * 24 * 60 * 60 * 1000)
        rows = conn.execute("""
            SELECT phase, COUNT(*) as count, AVG(confidence) as avg_conf
            FROM regime_history WHERE timestamp>=?
            GROUP BY phase ORDER BY count DESC
        """, (cutoff,)).fetchall()
        return {r["phase"]: {"count": r["count"], "avg_confidence": round(r["avg_conf"], 3)} for r in rows}
    finally:
        conn.close()


# ─── Metrics History ──────────────────────────────────────

def save_metrics(metrics: dict) -> None:
    """Save market metrics snapshot."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO metrics_history
            (timestamp, symbol, timeframe, price, atr14, ema20, ema50,
             rsi14, vwap, vwap_distance_pct, volume_zscore,
             realized_volatility, trend_score, volatility_score,
             institutional_bias, bias_score, expected_move,
             hurst_exponent, shannon_entropy, garch_volatility,
             kalman_trend_strength, markov_bull_prob, markov_bear_prob,
             monte_carlo_var95, fourier_dominant_period,
             volume_profile_poc, volume_profile_imbalance,
             return_skewness, return_kurtosis, fractal_dimension)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            metrics.get("timestamp", int(time.time() * 1000)),
            metrics.get("symbol", "BTCUSDT"),
            metrics.get("timeframe", "5m"),
            metrics.get("price"),
            metrics.get("atr14"),
            metrics.get("ema20"),
            metrics.get("ema50"),
            metrics.get("rsi14"),
            metrics.get("vwap"),
            metrics.get("vwap_distance_pct"),
            metrics.get("volume_zscore"),
            metrics.get("realized_volatility"),
            metrics.get("trend_score"),
            metrics.get("volatility_score"),
            metrics.get("institutional_bias"),
            metrics.get("bias_score"),
            metrics.get("expected_move"),
            metrics.get("hurst_exponent"),
            metrics.get("shannon_entropy"),
            metrics.get("garch_volatility"),
            metrics.get("kalman_trend_strength"),
            metrics.get("markov_bull_prob"),
            metrics.get("markov_bear_prob"),
            metrics.get("monte_carlo_var95"),
            metrics.get("fourier_dominant_period"),
            metrics.get("volume_profile_poc"),
            metrics.get("volume_profile_imbalance"),
            metrics.get("return_skewness"),
            metrics.get("return_kurtosis"),
            metrics.get("fractal_dimension"),
        ))
        conn.commit()
    finally:
        conn.close()


def get_metrics_history(
    symbol: str | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = 500,
) -> list[dict]:
    """Query metrics history."""
    conn = get_conn()
    try:
        query = "SELECT * FROM metrics_history WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        if end_ts:
            query += " AND timestamp<=?"
            params.append(end_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Candle Archive ───────────────────────────────────────

def save_candle(candle: dict) -> None:
    """Archive a closed candle."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO candle_archive
            (timestamp, symbol, timeframe, open, high, low, close, volume, is_closed)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            candle["timestamp"],
            candle.get("symbol", "BTCUSDT"),
            candle.get("timeframe", "5m"),
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
            candle["volume"],
            1 if candle.get("is_closed", True) else 0,
        ))
        conn.commit()
    finally:
        conn.close()


def save_candles(candles: list[dict]) -> None:
    """Batch archive candles."""
    conn = get_conn()
    try:
        for c in candles:
            conn.execute("""
                INSERT OR REPLACE INTO candle_archive
                (timestamp, symbol, timeframe, open, high, low, close, volume, is_closed)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                c["timestamp"],
                c.get("symbol", "BTCUSDT"),
                c.get("timeframe", "5m"),
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                c["volume"],
                1 if c.get("is_closed", True) else 0,
            ))
        conn.commit()
    finally:
        conn.close()


def get_candles(
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Query archived candles."""
    result = get_candles_with_source(symbol, timeframe, start_ts, end_ts, limit)
    return result["candles"]


def get_candles_with_source(
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    start_ts: int | None = None,
    end_ts: int | None = None,
    limit: int = 1000,
) -> dict:
    """Query archived candles and report the actual symbol key used."""
    conn = get_conn()
    try:
        aliases = symbol_aliases(symbol)
        for alias in aliases:
            query = "SELECT * FROM candle_archive WHERE symbol=? AND timeframe=?"
            params: list[Any] = [alias, timeframe]
            if start_ts:
                query += " AND timestamp>=?"
                params.append(start_ts)
            if end_ts:
                query += " AND timestamp<=?"
                params.append(end_ts)
            query += " ORDER BY timestamp ASC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            if rows or alias == aliases[-1]:
                return {
                    "requested_symbol": symbol,
                    "actual_symbol": alias,
                    "timeframe": timeframe,
                    "candles": [dict(r) for r in rows],
                }
        return {
            "requested_symbol": symbol,
            "actual_symbol": symbol,
            "timeframe": timeframe,
            "candles": [],
        }
    finally:
        conn.close()


# ─── AI Decisions History ─────────────────────────────────

def save_ai_decision(decision: dict) -> None:
    """Save an AI ICT decision to history."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO ai_decisions_history
            (timestamp, symbol, timeframe, provider, model,
             direction, grade, readiness, confidence, setup_score,
             entry, stop_loss, take_profit, risk_reward,
             summary, confirmations, blockers, calculations,
             momentum_score, option_symbol)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            decision.get("timestamp", int(time.time() * 1000)),
            decision.get("symbol", "BTCUSDT"),
            decision.get("timeframe", "5m"),
            decision.get("provider"),
            decision.get("model"),
            decision.get("direction"),
            decision.get("grade"),
            decision.get("readiness"),
            decision.get("confidence"),
            decision.get("setup_score"),
            decision.get("entry"),
            decision.get("stop_loss"),
            decision.get("take_profit"),
            decision.get("risk_reward"),
            decision.get("summary", ""),
            json.dumps(decision.get("confirmations", [])),
            json.dumps(decision.get("blockers", [])),
            json.dumps(decision.get("calculations", [])),
            decision.get("momentum_score"),
            decision.get("option_symbol"),
        ))
        conn.commit()
    finally:
        conn.close()


def get_ai_decisions(
    symbol: str | None = None,
    grade: str | None = None,
    start_ts: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query AI decision history."""
    conn = get_conn()
    try:
        query = "SELECT * FROM ai_decisions_history WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if grade:
            query += " AND grade=?"
            params.append(grade)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            for field in ("confirmations", "blockers", "calculations"):
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            results.append(d)
        return results
    finally:
        conn.close()


def get_ai_accuracy(days: int = 7, timeframe: str | None = None) -> dict:
    """Calculate AI decision accuracy over recent days."""
    conn = get_conn()
    try:
        cutoff = int(time.time() * 1000) - (days * 24 * 60 * 60 * 1000)
        where = "timestamp>=?"
        params: list[object] = [cutoff]
        if timeframe:
            where += " AND timeframe=?"
            params.append(timeframe)

        total_reviews = conn.execute(
            f"SELECT COUNT(*) FROM ai_decisions_history WHERE {where}", params
        ).fetchone()[0]
        actionable = conn.execute(
            f"SELECT COUNT(*) FROM ai_decisions_history WHERE {where} AND grade!='NO_TRADE'", params
        ).fetchone()[0]
        no_trade = conn.execute(
            f"SELECT COUNT(*) FROM ai_decisions_history WHERE {where} AND grade='NO_TRADE'", params
        ).fetchone()[0]
        grade_dist = conn.execute(f"""
            SELECT grade, COUNT(*) as count, AVG(confidence) as avg_conf
            FROM ai_decisions_history WHERE {where}
            GROUP BY grade ORDER BY count DESC
        """, params).fetchall()
        avg_conf = conn.execute(
            f"SELECT AVG(confidence) FROM ai_decisions_history WHERE {where}", params
        ).fetchone()[0] or 0
        avg_setup = conn.execute(
            f"SELECT AVG(setup_score) FROM ai_decisions_history WHERE {where}", params
        ).fetchone()[0] or 0

        return {
            "total_decisions": total_reviews,
            "actionable_decisions": actionable,
            "no_trade_decisions": no_trade,
            "grade_distribution": {r["grade"]: {"count": r["count"], "avg_confidence": round(r["avg_conf"], 3)} for r in grade_dist},
            "avg_confidence": round(avg_conf, 3),
            "avg_setup_score": round(avg_setup, 3),
        }
    finally:
        conn.close()


# ─── Liquidity History ────────────────────────────────────

def save_liquidity_event(event: dict) -> None:
    """Save a liquidity event to history."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO liquidity_history
            (timestamp, symbol, timeframe, side, swept_level, sweep_price,
             close_price, sweep_depth, displacement, reclaimed,
             engineered_score, reason, level_kind, level_price, touch_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            event.get("timestamp", int(time.time() * 1000)),
            event.get("symbol", "BTCUSDT"),
            event.get("timeframe", "5m"),
            event["side"],
            event.get("swept_level"),
            event.get("sweep_price"),
            event.get("close_price"),
            event.get("sweep_depth"),
            event.get("displacement"),
            1 if event.get("reclaimed") else 0,
            event.get("engineered_score"),
            event.get("reason", ""),
            event.get("level_kind"),
            event.get("level_price"),
            event.get("touch_count"),
        ))
        conn.commit()
    finally:
        conn.close()


def get_liquidity_history(
    symbol: str | None = None,
    side: str | None = None,
    start_ts: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Query liquidity event history."""
    conn = get_conn()
    try:
        query = "SELECT * FROM liquidity_history WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if side:
            query += " AND side=?"
            params.append(side)
        if start_ts:
            query += " AND timestamp>=?"
            params.append(start_ts)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Orderbook History ────────────────────────────────────

def save_orderbook_snapshot(data: dict) -> None:
    """Save orderbook state snapshot."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO orderbook_history
            (timestamp, symbol, bid, ask, spread, spread_pct, mid,
             imbalance_count, accumulation_count, spread_anomaly_count,
             raw_imbalances, raw_accumulations)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("timestamp", int(time.time() * 1000)),
            data.get("symbol", "BTCUSDT"),
            data.get("bid"),
            data.get("ask"),
            data.get("spread"),
            data.get("spread_pct"),
            data.get("mid"),
            data.get("imbalance_count", 0),
            data.get("accumulation_count", 0),
            data.get("spread_anomaly_count", 0),
            json.dumps(data.get("raw_imbalances", [])),
            json.dumps(data.get("raw_accumulations", [])),
        ))
        conn.commit()
    finally:
        conn.close()


# ─── Performance Daily ────────────────────────────────────

def save_daily_performance(data: dict) -> None:
    """Save daily aggregated performance stats."""
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO performance_daily
            (date, symbol, total_signals, bullish_signals, bearish_signals,
             avg_signal_confidence, total_paper_trades, paper_wins, paper_losses,
             paper_pnl, paper_win_rate, avg_regime, dominant_pattern,
             avg_atr, avg_rsi, max_drawdown_pct, raw_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["date"],
            data.get("symbol", "BTCUSDT"),
            data.get("total_signals", 0),
            data.get("bullish_signals", 0),
            data.get("bearish_signals", 0),
            data.get("avg_signal_confidence"),
            data.get("total_paper_trades", 0),
            data.get("paper_wins", 0),
            data.get("paper_losses", 0),
            data.get("paper_pnl", 0),
            data.get("paper_win_rate"),
            data.get("avg_regime"),
            data.get("dominant_pattern"),
            data.get("avg_atr"),
            data.get("avg_rsi"),
            data.get("max_drawdown_pct"),
            json.dumps(data.get("raw_data", {})),
        ))
        conn.commit()
    finally:
        conn.close()


def get_daily_performance(
    symbol: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 90,
) -> list[dict]:
    """Query daily performance stats."""
    conn = get_conn()
    try:
        query = "SELECT * FROM performance_daily WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if start_date:
            query += " AND date>=?"
            params.append(start_date)
        if end_date:
            query += " AND date<=?"
            params.append(end_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("raw_data"):
                try:
                    d["raw_data"] = json.loads(d["raw_data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


# ─── Data Retention / Cleanup ─────────────────────────────

def cleanup_old_data(
    keep_days_snapshots: int = 90,
    keep_days_patterns: int = 180,
    keep_days_metrics: int = 60,
    keep_days_candles: int = 365,
    keep_days_ai: int = 180,
    keep_days_liquidity: int = 90,
    keep_days_orderbook: int = 30,
) -> dict:
    """Delete data older than retention periods. Returns counts deleted."""
    conn = get_conn()
    try:
        now_ms = int(time.time() * 1000)
        cutoffs = {
            "snapshots": now_ms - (keep_days_snapshots * 86400000),
            "patterns": now_ms - (keep_days_patterns * 86400000),
            "metrics": now_ms - (keep_days_metrics * 86400000),
            "candles": now_ms - (keep_days_candles * 86400000),
            "ai": now_ms - (keep_days_ai * 86400000),
            "liquidity": now_ms - (keep_days_liquidity * 86400000),
            "orderbook": now_ms - (keep_days_orderbook * 86400000),
        }

        deleted = {}
        for table, cutoff in cutoffs.items():
            if table == "snapshots":
                cur = conn.execute("DELETE FROM market_snapshots WHERE timestamp<?", (cutoff,))
            elif table == "patterns":
                cur = conn.execute("DELETE FROM pattern_history WHERE timestamp<?", (cutoff,))
            elif table == "metrics":
                cur = conn.execute("DELETE FROM metrics_history WHERE timestamp<?", (cutoff,))
            elif table == "candles":
                cur = conn.execute("DELETE FROM candle_archive WHERE timestamp<?", (cutoff,))
            elif table == "ai":
                cur = conn.execute("DELETE FROM ai_decisions_history WHERE timestamp<?", (cutoff,))
            elif table == "liquidity":
                cur = conn.execute("DELETE FROM liquidity_history WHERE timestamp<?", (cutoff,))
            elif table == "orderbook":
                cur = conn.execute("DELETE FROM orderbook_history WHERE timestamp<?", (cutoff,))
            else:
                continue
            deleted[table] = cur.rowcount

        conn.commit()
        return deleted
    finally:
        conn.close()


def get_storage_stats() -> dict:
    """Get storage statistics for all tables."""
    conn = get_conn()
    try:
        tables = [
            "signals", "paper_trades", "backtest_runs", "alerts",
            "market_snapshots", "pattern_history", "regime_history",
            "metrics_history", "candle_archive", "ai_decisions_history",
            "liquidity_history", "orderbook_history", "performance_daily",
        ]
        stats = {}
        for table in tables:
            row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
            stats[table] = row["count"]

        oldest_candle = conn.execute(
            "SELECT MIN(timestamp) as ts FROM candle_archive"
        ).fetchone()
        newest_candle = conn.execute(
            "SELECT MAX(timestamp) as ts FROM candle_archive"
        ).fetchone()

        stats["oldest_candle"] = oldest_candle["ts"] if oldest_candle["ts"] else None
        stats["newest_candle"] = newest_candle["ts"] if newest_candle["ts"] else None
        stats["candle_date_range_days"] = (
            round((newest_candle["ts"] - oldest_candle["ts"]) / 86400000, 1)
            if oldest_candle["ts"] and newest_candle["ts"]
            else 0
        )

        return stats
    finally:
        conn.close()
