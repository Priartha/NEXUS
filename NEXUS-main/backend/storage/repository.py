from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from backend.storage.schema import get_conn


# ─── Signals ──────────────────────────────────────────────

def save_signal(signal: dict) -> None:
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO signals
            (id, timestamp, symbol, timeframe, side, entry, stop_loss, exit_price,
             risk_reward, confidence, reason, status, exit_timestamp,
             institutional_score, liquidity_score, bias_score, expected_move,
             win_probability, kelly_fraction, suggested_risk_fraction,
             cvar95_loss, risk_of_ruin, trailing_stop, trailing_mode, model,
             created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            signal["id"], signal["timestamp"], signal.get("symbol", "BTC/USDT"),
            signal.get("timeframe", "5m"), signal["side"], signal["entry"],
            signal["stop_loss"], signal["exit_price"], signal["risk_reward"],
            signal["confidence"], signal["reason"], signal.get("status", "open"),
            signal.get("exit_timestamp"),
            signal.get("institutional_score", 0), signal.get("liquidity_score", 0),
            signal.get("bias_score", 0), signal.get("expected_move", 0),
            signal.get("win_probability", 0), signal.get("kelly_fraction", 0),
            signal.get("suggested_risk_fraction", 0), signal.get("cvar95_loss", 0),
            signal.get("risk_of_ruin", 0), signal.get("trailing_stop"),
            signal.get("trailing_mode", "atr_chandelier"),
            signal.get("model", "institutional-v2"),
            int(time.time() * 1000),
        ))
        conn.commit()
    finally:
        conn.close()


def update_signal_status(signal_id: str, status: str, exit_timestamp: int | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE signals SET status=?, exit_timestamp=? WHERE id=?",
            (status, exit_timestamp, signal_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_signals(symbol: str | None = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM signals WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Paper Trades ─────────────────────────────────────────

def save_paper_trade(trade: dict) -> None:
    required = ["id", "symbol", "side", "entry_price", "stop_loss", "take_profit"]
    for field in required:
        if field not in trade:
            raise ValueError(f"save_paper_trade missing required field: {field}")
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO paper_trades
            (id, signal_id, symbol, timeframe, side, entry_price, stop_loss,
             take_profit, quantity, status, opened_at, closed_at, exit_price,
             pnl, pnl_pct, risk_reward, confidence, reason, close_reason,
             bars_held, highest_price, lowest_price, initial_stop, atr_at_entry,
             entry_commission, slippage_pct, funding_rate, max_hold_minutes,
             regime, enriched_features)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            trade.get("id"), trade.get("signal_id"), trade.get("symbol"),
            trade.get("timeframe", "5m"), trade.get("side"), trade.get("entry_price"),
            trade.get("stop_loss"), trade.get("take_profit"), trade.get("quantity", 1.0),
            trade.get("status", "open"), trade.get("opened_at", trade.get("timestamp")),
            trade.get("closed_at"), trade.get("exit_price"),
            trade.get("pnl"), trade.get("pnl_pct"), trade.get("risk_reward"),
            trade.get("confidence"), trade.get("reason"), trade.get("close_reason"),
            trade.get("bars_held", 0), trade.get("highest_price"), trade.get("lowest_price"),
            trade.get("initial_stop", trade.get("stop_loss")), trade.get("atr_at_entry", 0),
            trade.get("entry_commission", trade.get("commission", 0)),
            trade.get("slippage_pct", 0), trade.get("funding_rate", 0),
            trade.get("max_hold_minutes", 25), trade.get("regime"),
            json.dumps(trade.get("enriched_features")) if trade.get("enriched_features") is not None else None,
        ))
        conn.commit()
    finally:
        conn.close()


ALLOWED_PAPER_COLS = {
    "bars_held", "stop_loss", "highest_price", "lowest_price",
}

def update_paper_trade(trade_id: str, updates: dict) -> None:
    cols = {k: v for k, v in updates.items() if k in ALLOWED_PAPER_COLS}
    if not cols:
        return
    set_clause = ", ".join(f"{k}=?" for k in cols)
    vals = list(cols.values()) + [trade_id]
    conn = get_conn()
    try:
        conn.execute(f"UPDATE paper_trades SET {set_clause} WHERE id=?", vals)
        conn.commit()
    except Exception as e:
        logging.getLogger("backend").warning("Failed to update paper trade %s: %s", trade_id, e)
    finally:
        conn.close()


def close_paper_trade(trade_id: str, exit_price: float, pnl: float,
                      pnl_pct: float, close_reason: str) -> None:
    conn = get_conn()
    try:
        conn.execute("""
            UPDATE paper_trades SET status='closed', closed_at=?,
            exit_price=?, pnl=?, pnl_pct=?, close_reason=?
            WHERE id=?
        """, (int(time.time() * 1000), exit_price, pnl, pnl_pct, close_reason, trade_id))
        conn.commit()
    finally:
        conn.close()


def get_paper_trades(symbol: str | None = None, status: str | None = None,
                     limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM paper_trades WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol=?"
            params.append(symbol)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("enriched_features"):
                try:
                    d["enriched_features"] = json.loads(d["enriched_features"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


def get_paper_trade_stats() -> dict:
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        closed = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'").fetchone()[0]
        wins = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed' AND pnl > 0").fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed' AND pnl <= 0").fetchone()[0]
        total_pnl = conn.execute("SELECT COALESCE(SUM(pnl),0) FROM paper_trades WHERE status='closed'").fetchone()[0]
        return {
            "total_trades": total,
            "closed_trades": closed,
            "winning_trades": wins,
            "losing_trades": losses,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(wins / closed, 4) if closed else 0,
        }
    finally:
        conn.close()


# ─── Backtests ────────────────────────────────────────────

def save_backtest_run(run: dict) -> None:
    conn = get_conn()
    try:
        if run.get("walk_forward"):
            combined = run.get("combined", {})
            train = run.get("train_period", {})
            test = run.get("test_period", {})
            start_date = train.get("start_date", 0)
            end_date = test.get("end_date", 0)
            candle_count = train.get("candle_count", 0) + test.get("candle_count", 0)
            initial_balance = combined.get("initial_balance", 10000.0)
            final_balance = combined.get("final_balance", 10000.0)
            total_pnl = combined.get("total_pnl", 0.0)
            total_pnl_pct = combined.get("total_pnl_pct", 0.0)
            total_trades = combined.get("total_trades", 0)
            winning_trades = combined.get("winning_trades", 0)
            losing_trades = combined.get("losing_trades", 0)
            win_rate = combined.get("win_rate", 0.0)
            profit_factor = combined.get("profit_factor", 0.0)
            max_drawdown = combined.get("max_drawdown", 0.0)
            max_drawdown_pct = combined.get("max_drawdown_pct", 0.0)
            sharpe = combined.get("sharpe_ratio", 0.0)
        else:
            start_date = run.get("start_date", 0)
            end_date = run.get("end_date", 0)
            candle_count = run.get("candle_count", 0)
            initial_balance = run.get("initial_balance", 10000.0)
            final_balance = run.get("final_balance")
            total_pnl = run.get("total_pnl", 0.0)
            total_pnl_pct = run.get("total_pnl_pct", 0.0)
            total_trades = run.get("total_trades", 0)
            winning_trades = run.get("winning_trades", 0)
            losing_trades = run.get("losing_trades", 0)
            win_rate = run.get("win_rate")
            profit_factor = run.get("profit_factor")
            max_drawdown = run.get("max_drawdown", 0.0)
            max_drawdown_pct = run.get("max_drawdown_pct", 0.0)
            sharpe = run.get("sharpe_ratio")
        conn.execute("""
            INSERT OR REPLACE INTO backtest_runs
            (id, symbol, timeframe, start_date, end_date, candle_count,
             initial_balance, final_balance,
             total_trades, winning_trades, losing_trades, total_pnl,
             total_pnl_pct, max_drawdown, max_drawdown_pct, sharpe_ratio,
             win_rate, avg_win, avg_loss, profit_factor, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            run.get("id"), run.get("symbol", ""), run.get("timeframe", ""),
            start_date, end_date, candle_count,
            initial_balance, final_balance,
            total_trades, winning_trades, losing_trades, total_pnl,
            total_pnl_pct, max_drawdown, max_drawdown_pct, sharpe,
            win_rate, run.get("avg_win"), run.get("avg_loss"),
            profit_factor, int(time.time() * 1000),
        ))
        conn.commit()
    except Exception as e:
        import traceback
        logging.getLogger("backend").error(f"save_backtest_run failed: {e}\n{traceback.format_exc()}")
    finally:
        conn.close()


def save_backtest_trades(run_id: str, trades: list[dict]) -> None:
    conn = get_conn()
    try:
        for t in trades:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO backtest_trades
                    (id, run_id, signal_id, timestamp, side, entry_price,
                     stop_loss, exit_price, exit_timestamp, pnl, pnl_pct,
                     risk_reward, confidence, reason, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    t.get("id"), run_id, t.get("signal_id"), t.get("timestamp"),
                    t.get("side"), t.get("entry_price"), t.get("stop_loss"), t.get("exit_price"),
                    t.get("exit_timestamp"), t.get("pnl"), t.get("pnl_pct"),
                    t.get("risk_reward"), t.get("confidence"), t.get("reason"),
                    t.get("status", "closed"),
                ))
            except Exception as e:
                logging.getLogger("backend").warning(f"Skipping bad trade row: {e}")
        conn.commit()
    except Exception as e:
        logging.getLogger("backend").error(f"save_backtest_trades: {e}")
    finally:
        conn.close()


def save_equity_points(points: list[dict]) -> None:
    conn = get_conn()
    try:
        for p in points:
            conn.execute("""
                INSERT INTO equity_curve (timestamp, account_balance, drawdown, drawdown_pct, source, run_id)
                VALUES (?,?,?,?,?,?)
            """, (
                p["timestamp"], p["account_balance"], p.get("drawdown", 0.0),
                p.get("drawdown_pct", 0.0), p.get("source", "backtest"),
                p.get("run_id"),
            ))
        conn.commit()
    finally:
        conn.close()


def get_backtest_runs(symbol: str | None = None, limit: int = 20) -> list[dict]:
    conn = get_conn()
    try:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM backtest_runs WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_backtest_trades(run_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id=? ORDER BY timestamp", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_equity_curve(run_id: str | None = None, limit: int = 5000) -> list[dict]:
    conn = get_conn()
    try:
        if run_id:
            rows = conn.execute(
                "SELECT * FROM equity_curve WHERE run_id=? ORDER BY timestamp LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM equity_curve ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Alerts ───────────────────────────────────────────────

def save_alert(alert: dict) -> None:
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO alerts
            (id, timestamp, type, severity, symbol, title, message, data, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            alert["id"], alert["timestamp"], alert["type"],
            alert.get("severity", "info"), alert.get("symbol"),
            alert["title"], alert.get("message"),
            json.dumps(alert["data"]) if alert.get("data") else None,
            int(time.time() * 1000),
        ))
        conn.commit()
    finally:
        conn.close()


def get_alerts(limit: int = 50, unread_only: bool = False) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM alerts"
        params: list[Any] = []
        if unread_only:
            query += " WHERE acknowledged=0"
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("data"):
                try:
                    d["data"] = json.loads(d["data"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


def acknowledge_alert(alert_id: str) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
        conn.commit()
    finally:
        conn.close()


# ─── Alert Configuration ──────────────────────────────────

def get_alert_config() -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT config_json FROM alert_config WHERE id=1").fetchone()
        if row and row["config_json"]:
            return json.loads(row["config_json"])
        return {
            "rules": [],
            "sound_enabled": True,
            "notification_enabled": False,
            "max_alerts_per_hour": 20,
        }
    finally:
        conn.close()


def save_alert_config(config: dict) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO alert_config (id, config_json, updated_at) VALUES (1, ?, ?)",
            (json.dumps(config), int(time.time() * 1000)),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Trade Journal ────────────────────────────────────────

def save_journal_entry(entry: dict) -> None:
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO trade_journal_entries
            (id, paper_trade_id, timestamp, entry_type, content, tags, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            entry["id"], entry.get("paper_trade_id"), entry["timestamp"],
            entry["entry_type"], entry["content"],
            json.dumps(entry["tags"]) if entry.get("tags") else None,
            int(time.time() * 1000),
        ))
        conn.commit()
    finally:
        conn.close()


def get_journal_entries(trade_id: str | None = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        if trade_id:
            rows = conn.execute(
                "SELECT * FROM trade_journal_entries WHERE paper_trade_id=? ORDER BY timestamp DESC LIMIT ?",
                (trade_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_journal_entries ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("tags"):
                try:
                    d["tags"] = json.loads(d["tags"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


# ─── Reset / Clear ──────────────────────────────────────

def reset_paper_trades() -> int:
    conn = get_conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM paper_trades")
        count = cur.fetchone()[0]
        conn.execute("DELETE FROM paper_trades")
        conn.commit()
        return count
    finally:
        conn.close()


def reset_backtests() -> int:
    conn = get_conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM backtest_runs")
        count = cur.fetchone()[0]
        conn.execute("DELETE FROM backtest_trades")
        conn.execute("DELETE FROM backtest_runs")
        conn.execute("DELETE FROM equity_curve WHERE source = 'backtest'")
        conn.commit()
        return count
    finally:
        conn.close()
