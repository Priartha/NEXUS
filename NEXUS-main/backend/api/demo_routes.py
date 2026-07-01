"""
Demo forward testing API routes.

Provides endpoints for:
- Starting/stopping demo trading
- Getting current status and stats
- Retrieving open and closed trades
- Resetting demo data
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import asyncio
import threading
from pathlib import Path
from datetime import datetime, timezone

router = APIRouter(prefix="/demo", tags=["demo"])

# In-memory state
_demo_state = {
    "running": False,
    "stats": None,
    "open_trades": [],
    "closed_trades": [],
    "last_update": None,
}

_demo_thread: Optional[threading.Thread] = None
_demo_stop_event = threading.Event()


class DemoStatus(BaseModel):
    running: bool
    stats: Optional[dict]
    open_trades: list
    last_update: Optional[str]


class DemoTrades(BaseModel):
    open_trades: list
    closed_trades: list


@router.get("/status", response_model=DemoStatus)
async def get_demo_status():
    """Get current demo trading status."""
    return DemoStatus(
        running=_demo_state["running"],
        stats=_demo_state["stats"],
        open_trades=_demo_state["open_trades"],
        last_update=_demo_state["last_update"],
    )


@router.get("/trades", response_model=DemoTrades)
async def get_demo_trades():
    """Get open and closed trades."""
    return DemoTrades(
        open_trades=_demo_state["open_trades"],
        closed_trades=_demo_state["closed_trades"],
    )


@router.post("/start")
async def start_demo():
    """Start the demo trading engine."""
    global _demo_thread, _demo_stop_event

    if _demo_state["running"]:
        return {"status": "already_running"}

    _demo_stop_event.clear()
    _demo_state["running"] = True
    _demo_state["last_update"] = datetime.now(timezone.utc).isoformat()

    # Load existing data if any
    data_dir = Path("demo_data")
    data_dir.mkdir(exist_ok=True)
    trades_file = data_dir / "trades.json"

    if trades_file.exists():
        with open(trades_file) as f:
            data = json.load(f)
            _demo_state["open_trades"] = data.get("open_trades", [])
            _demo_state["closed_trades"] = data.get("closed_trades", [])
            _demo_state["stats"] = {
                "balance": data.get("balance", 10000.0),
                "initial_balance": 10000.0,
                "total_pnl": data.get("total_pnl", 0.0),
                "total_pnl_pct": (data.get("total_pnl", 0.0) / 10000.0) * 100,
                "total_trades": len(data.get("closed_trades", [])),
                "winning_trades": data.get("winning_trades", 0),
                "losing_trades": data.get("losing_trades", 0),
                "win_rate": data.get("winning_trades", 0) / max(1, len(data.get("closed_trades", []))),
                "avg_win": 0,
                "avg_loss": 0,
                "signal_count": data.get("signal_count", 0),
                "peak_balance": data.get("peak_balance", 10000.0),
                "max_drawdown": data.get("peak_balance", 10000.0) - data.get("balance", 10000.0),
                "max_drawdown_pct": ((data.get("peak_balance", 10000.0) - data.get("balance", 10000.0)) / max(1, data.get("peak_balance", 10000.0))) * 100,
                "updated_at": data.get("updated_at"),
            }

    # Start demo thread
    _demo_thread = threading.Thread(target=_run_demo_loop, daemon=True)
    _demo_thread.start()

    return {"status": "started"}


@router.post("/stop")
async def stop_demo():
    """Stop the demo trading engine."""
    global _demo_thread

    if not _demo_state["running"]:
        return {"status": "not_running"}

    _demo_stop_event.set()
    _demo_state["running"] = False
    _demo_state["last_update"] = datetime.now(timezone.utc).isoformat()

    if _demo_thread:
        _demo_thread.join(timeout=5)
        _demo_thread = None

    return {"status": "stopped"}


@router.post("/reset")
async def reset_demo():
    """Reset all demo trading data."""
    global _demo_thread

    # Stop if running
    if _demo_state["running"]:
        _demo_stop_event.set()
        _demo_state["running"] = False
        if _demo_thread:
            _demo_thread.join(timeout=5)
            _demo_thread = None

    # Clear state
    _demo_state["stats"] = None
    _demo_state["open_trades"] = []
    _demo_state["closed_trades"] = []
    _demo_state["last_update"] = datetime.now(timezone.utc).isoformat()

    # Clear files
    data_dir = Path("demo_data")
    trades_file = data_dir / "trades.json"
    stats_file = data_dir / "stats.json"
    signals_file = data_dir / "signals.json"

    for f in [trades_file, stats_file, signals_file]:
        if f.exists():
            f.unlink()

    return {"status": "reset"}


def _run_demo_loop():
    """Run the demo trading loop in a background thread."""
    import httpx
    import websockets
    import json as json_mod

    from backend.models.types import Candle
    from backend.analysis.optimized_signals import detect_optimized_signals
    from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
    from backend.analysis.institutional import compute_market_metrics
    from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
    from backend.analysis.liquidity_engineering import detect_liquidity_events
    from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
    from backend.analysis.swing_detector import detect_swings

    # Config - ATR-based stops/targets, trending markets only
    SYMBOL = "BTCUSDT"
    INTERVAL = "5m"
    INITIAL_BALANCE = 10000.0
    POSITION_SIZE_PCT = 0.02
    MAX_HOLD_BARS = 10
    BREAKEVEN_THRESHOLD = 1.0
    PARTIAL_TP1_R = 1.0
    PARTIAL_TP2_R = 2.0
    STOP_LOSS_MULTIPLIER = 1.0
    USE_ADX_FILTER = False
    ADX_THRESHOLD = 20.0
    USE_LIMIT_ORDERS = False
    MIN_CONFIDENCE = 0.45
    SIGNAL_COOLDOWN_CANDLES = 6

    # State
    candles = []
    last_signal_ts = 0
    signal_count = 0

    def save_data():
        """Save trades and stats to file."""
        data_dir = Path("demo_data")
        data_dir.mkdir(exist_ok=True)
        trades_file = data_dir / "trades.json"

        balance = _demo_state["stats"]["balance"] if _demo_state["stats"] else INITIAL_BALANCE
        peak_balance = _demo_state["stats"]["peak_balance"] if _demo_state["stats"] else INITIAL_BALANCE
        total_pnl = _demo_state["stats"]["total_pnl"] if _demo_state["stats"] else 0.0
        winning = _demo_state["stats"]["winning_trades"] if _demo_state["stats"] else 0
        losing = _demo_state["stats"]["losing_trades"] if _demo_state["stats"] else 0

        trades_data = {
            "closed_trades": _demo_state["closed_trades"],
            "open_trades": _demo_state["open_trades"],
            "balance": balance,
            "peak_balance": peak_balance,
            "last_signal_ts": last_signal_ts,
            "signal_count": signal_count,
            "trade_count": len(_demo_state["closed_trades"]),
            "total_pnl": total_pnl,
            "winning_trades": winning,
            "losing_trades": losing,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(trades_file, "w") as f:
            json_mod.dump(trades_data, f, indent=2, default=str)

    def update_stats():
        """Update stats in global state."""
        balance = INITIAL_BALANCE
        for t in _demo_state["closed_trades"]:
            balance += t.get("pnl", 0)

        winning = [t for t in _demo_state["closed_trades"] if t.get("pnl", 0) > 0]
        losing = [t for t in _demo_state["closed_trades"] if t.get("pnl", 0) <= 0]

        total_pnl = balance - INITIAL_BALANCE
        peak_balance = INITIAL_BALANCE
        bal = INITIAL_BALANCE
        max_dd = 0

        for t in sorted(_demo_state["closed_trades"], key=lambda x: x.get("timestamp", 0)):
            bal += t.get("pnl", 0)
            if bal > peak_balance:
                peak_balance = bal
            dd = peak_balance - bal
            if dd > max_dd:
                max_dd = dd

        _demo_state["stats"] = {
            "balance": balance,
            "initial_balance": INITIAL_BALANCE,
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / INITIAL_BALANCE) * 100,
            "total_trades": len(_demo_state["closed_trades"]),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / max(1, len(_demo_state["closed_trades"])),
            "avg_win": sum(t["pnl"] for t in winning) / max(1, len(winning)),
            "avg_loss": abs(sum(t["pnl"] for t in losing)) / max(1, len(losing)),
            "signal_count": signal_count,
            "peak_balance": peak_balance,
            "max_drawdown": max_dd,
            "max_drawdown_pct": (max_dd / peak_balance * 100) if peak_balance > 0 else 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def process_trades(candle):
        """Process open trades against new candle."""
        for trade in list(_demo_state["open_trades"]):
            if trade.get("status") != "open":
                continue

            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp1 = trade["tp1"]
            tp2 = trade["tp2"]
            qty = trade["remaining_qty"]
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held

            # Move to breakeven
            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0 and not trade.get("tp1_hit", False):
                if side == "buy":
                    profit_r = (candle.high - entry) / risk
                    if profit_r >= BREAKEVEN_THRESHOLD:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    profit_r = (entry - candle.low) / risk
                    if profit_r >= BREAKEVEN_THRESHOLD:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]

            # Check TP1
            if not trade.get("tp1_hit", False):
                if side == "buy" and candle.high >= tp1:
                    pnl1 = (tp1 - entry) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1
                elif side == "sell" and candle.low <= tp1:
                    pnl1 = (entry - tp1) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1

            # Time exit
            if bars_held >= MAX_HOLD_BARS:
                exit_price = candle.close
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]

                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "time_exit"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()

                _demo_state["closed_trades"].append(trade)
                _demo_state["open_trades"].remove(trade)
                update_stats()
                save_data()
                continue

            # Check SL/TP2
            if side == "buy":
                hit_sl = candle.low <= sl
                hit_tp2 = candle.high >= tp2
            else:
                hit_sl = candle.high >= sl
                hit_tp2 = candle.low <= tp2

            if hit_sl:
                exit_price = sl
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]

                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "stop_loss"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()

                _demo_state["closed_trades"].append(trade)
                _demo_state["open_trades"].remove(trade)
                update_stats()
                save_data()

            elif hit_tp2:
                exit_price = tp2
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]

                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "tp2_hit"
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()

                _demo_state["closed_trades"].append(trade)
                _demo_state["open_trades"].remove(trade)
                update_stats()
                save_data()

    def check_signals():
        """Check for new trading signals."""
        nonlocal last_signal_ts, signal_count

        if len(candles) < 100:
            return

        # Run analysis
        swings = detect_swings(candles)[-100:]
        fvgs = detect_fvgs(candles[-80:])
        order_blocks = detect_order_blocks(candles[-80:], swings)
        liquidity = detect_equal_levels(swings)

        for c in candles[-20:]:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)

        metrics = compute_market_metrics(candles, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(candles[-80:], liquidity, atr)[-40:]

        # Detect signals
        signals = detect_optimized_signals(
            candles=candles,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=last_signal_ts,
            signal_cooldown_candles=SIGNAL_COOLDOWN_CANDLES,
            min_confidence=MIN_CONFIDENCE,
            stop_loss_multiplier=STOP_LOSS_MULTIPLIER,
            use_adx_filter=USE_ADX_FILTER,
            adx_threshold=ADX_THRESHOLD,
            use_limit_orders=USE_LIMIT_ORDERS,
        )

        for sig in signals:
            signal_count += 1

            # Check if we can take the trade
            if len([t for t in _demo_state["open_trades"] if t.get("status") == "open"]) >= 1:
                continue

            if sig.confidence < MIN_CONFIDENCE:
                continue

            # Calculate position size
            risk_per_trade = INITIAL_BALANCE * POSITION_SIZE_PCT
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0

            # Calculate TP levels
            risk = abs(sig.entry - sig.stop_loss)
            tp1 = sig.entry + (risk * PARTIAL_TP1_R) if sig.side == "buy" else sig.entry - (risk * PARTIAL_TP1_R)
            tp2 = sig.entry + (risk * PARTIAL_TP2_R) if sig.side == "buy" else sig.entry - (risk * PARTIAL_TP2_R)

            trade = {
                "id": f"demo-{signal_count}",
                "signal_id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry_price": round(sig.entry, 2),
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "tp1": round(tp1, 2),
                "tp2": round(tp2, 2),
                "quantity": quantity,
                "remaining_qty": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "reason": sig.reason,
                "slippage": 0.0,
                "commission": 0.0,
                "bars_held": 0,
                "tp1_hit": False,
                "total_pnl": 0.0,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }

            _demo_state["open_trades"].append(trade)
            last_signal_ts = sig.timestamp

    # Fetch initial candles
    try:
        with httpx.Client(timeout=30) as client:
            url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit=500"
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        for k in data:
            candles.append(Candle(
                timestamp=k[0],
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            ))
    except Exception as e:
        print(f"Demo: Failed to fetch initial candles: {e}")
        _demo_state["running"] = False
        return

    # Connect to Binance websocket
    ws_url = f"wss://stream.binance.com:9443/ws/{SYMBOL.lower()}@kline_{INTERVAL}"

    while not _demo_stop_event.is_set():
        try:
            with websockets.connect(ws_url) as ws:
                while not _demo_stop_event.is_set():
                    try:
                        message = ws.recv(timeout=10)
                        data = json_mod.loads(message)

                        if "k" in data:
                            kline = data["k"]

                            candle = Candle(
                                timestamp=kline["t"],
                                open=float(kline["o"]),
                                high=float(kline["h"]),
                                low=float(kline["l"]),
                                close=float(kline["c"]),
                                volume=float(kline["v"]),
                                is_closed=kline["x"],
                            )

                            # Only process closed candles
                            if candle.is_closed:
                                candles.append(candle)

                                # Keep last 2000 candles
                                if len(candles) > 2000:
                                    candles = candles[-2000:]

                                # Process open trades
                                process_trades(candle)

                                # Check for signals every 12 candles
                                if len(candles) % 12 == 0:
                                    check_signals()

                                # Update stats
                                update_stats()
                                _demo_state["last_update"] = datetime.now(timezone.utc).isoformat()

                                # Save data every 100 candles
                                if len(candles) % 100 == 0:
                                    save_data()

                    except websockets.exceptions.ConnectionClosed:
                        break
                    except Exception as e:
                        print(f"Demo: Websocket error: {e}")
                        break

        except Exception as e:
            print(f"Demo: Connection error: {e}")

        if not _demo_stop_event.is_set():
            import time
            time.sleep(10)

    _demo_state["running"] = False
