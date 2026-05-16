"""
Comprehensive Strategy Optimizer
Tests every parameter combination across signal generation + backtest engine.
Finds the absolute best configuration.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import itertools
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle


# ──────────────────────────────────────────────────────────────
# DATA FETCHING
# ──────────────────────────────────────────────────────────────
async def fetch_binance_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 1000,
) -> list[Candle]:
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return [
        Candle(
            timestamp=k[0],
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        )
        for k in data
    ]


async def fetch_multi_timeframe(
    symbol: str = "BTCUSDT",
    intervals: list[str] = None,
    limit: int = 1000,
) -> dict[str, list[Candle]]:
    if intervals is None:
        intervals = ["5m", "15m", "1h", "4h"]
    result = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for interval in intervals:
            try:
                url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                result[interval] = [
                    Candle(
                        timestamp=k[0],
                        open=float(k[1]),
                        high=float(k[2]),
                        low=float(k[3]),
                        close=float(k[4]),
                        volume=float(k[5]),
                    )
                    for k in data
                ]
                print(f"  Fetched {len(result[interval])} {interval} candles")
            except Exception as e:
                print(f"  Failed to fetch {interval}: {e}")
    return result


# ──────────────────────────────────────────────────────────────
# SIGNAL GENERATION (parameterized)
# ──────────────────────────────────────────────────────────────
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_structure import detect_structure
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime import detect_market_regime
from backend.analysis.swing_detector import detect_swings


def _sma(data: list[float], period: int) -> list[float]:
    result: list[float] = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(0.0)
        else:
            result.append(sum(data[i - period + 1 : i + 1]) / period)
    return result


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    recent = candles[-(period + 1) :]
    for prev, cur in zip(recent, recent[1:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes) - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def _is_killzone(timestamp_ms: int) -> tuple[bool, str]:
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    hour = dt.hour
    minute = dt.minute
    time_val = hour + minute / 60.0
    if 2.0 <= time_val < 5.0:
        return True, "london"
    if 8.5 <= time_val < 11.0:
        return True, "ny_am"
    if 13.5 <= time_val < 16.0:
        return True, "ny_pm"
    return False, "off_hours"


def _find_nearest_fvg(candles, fvgs, current_price, direction):
    active = [f for f in fvgs if not f.is_filled]
    if not active:
        return None
    if direction == "buy":
        below = [f for f in active if f.bottom < current_price]
        if below:
            return max(below, key=lambda f: f.bottom)
    else:
        above = [f for f in active if f.top > current_price]
        if above:
            return min(above, key=lambda f: f.top)
    return None


def _find_nearest_ob(candles, order_blocks, current_price, direction):
    active = [ob for ob in order_blocks if not ob.is_breaker]
    if not active:
        return None
    if direction == "buy":
        below = [ob for ob in active if ob.bottom < current_price and ob.direction == "bullish"]
        if below:
            return max(below, key=lambda ob: ob.bottom)
    else:
        above = [ob for ob in active if ob.top > current_price and ob.direction == "bearish"]
        if above:
            return min(above, key=lambda ob: ob.top)
    return None


def _has_liquidity_sweep(liquidity_events, direction, lookback_ms: int = 3600000):
    from datetime import datetime, timezone
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    recent = [e for e in liquidity_events if (now_ms - e.timestamp) < lookback_ms]
    if direction == "buy":
        return any(e.side == "sell_side" and e.reclaimed for e in recent)
    else:
        return any(e.side == "buy_side" and e.reclaimed for e in recent)


def _check_market_structure(candles, swings, direction):
    if len(swings) < 4:
        return False, "insufficient_swings"
    recent_swings = swings[-8:]
    if direction == "buy":
        last_hh = max((s.price for s in recent_swings if s.kind == "high"), default=0)
        if candles[-1].close > last_hh and last_hh > 0:
            return True, "BOS"
        lows = [s.price for s in recent_swings if s.kind == "low"]
        if len(lows) >= 2 and lows[-1] > lows[-2]:
            return True, "HL_confirmed"
    else:
        last_ll = min((s.price for s in recent_swings if s.kind == "low"), default=float("inf"))
        if candles[-1].close < last_ll and last_ll < float("inf"):
            return True, "BOS"
        highs = [s.price for s in recent_swings if s.kind == "high"]
        if len(highs) >= 2 and highs[-1] < highs[-2]:
            return True, "LH_confirmed"
    return False, "no_structure_break"


def _volume_confirmation(candles, direction):
    if len(candles) < 20:
        return 1.0
    recent_volumes = [c.volume for c in candles[-20:-1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes)
    if avg_volume == 0:
        return 1.0
    current_volume = candles[-1].volume
    volume_ratio = current_volume / avg_volume
    if direction == "buy" and candles[-1].close > candles[-2].close:
        return min(volume_ratio / 1.5, 2.0)
    elif direction == "sell" and candles[-1].close < candles[-2].close:
        return min(volume_ratio / 1.5, 2.0)
    return 0.5


@dataclass
class SignalConfig:
    """All tunable signal generation parameters."""
    min_trend_strength: float = 0.15        # Was 0.25
    pullback_range_buy: tuple = (-4.0, 1.0) # Was (-2.5, 0.5)
    pullback_range_sell: tuple = (-1.0, 4.0)# Was (-0.5, 2.5)
    rsi_buy_range: tuple = (20, 65)         # Was (25, 60)
    rsi_sell_range: tuple = (35, 80)        # Was (40, 75)
    min_confluence: float = 0.30            # Was 0.45
    min_confidence: float = 0.40            # Was 0.50
    reward_multiple: float = 2.5            # Was 3.0
    require_killzone: bool = False          # Was implicit
    require_structure: bool = False         # Was implicit
    require_liquidity_sweep: bool = False   # Was implicit
    require_fvg_or_ob: bool = True          # At least one ICT pattern
    use_regime_filter: bool = True          # New: adapt to regime
    atr_stop_multiplier: float = 1.5        # Was 1.5
    atr_stop_buffer: float = 0.3            # Was 0.3


def generate_signals_param(
    candles,
    metrics,
    fvgs,
    order_blocks,
    liquidity_events,
    swings,
    cfg: SignalConfig,
    regime=None,
) -> list:
    """Parameterized signal generation."""
    if len(candles) < 100:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    latest = ordered[-1]
    atr14 = _atr(ordered, 14)
    rsi_i = _rsi(closes, 14)

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    i = len(ordered) - 1
    sma20_i = sma20[i]
    sma50_i = sma50[i]

    trend_strength = (sma20_i - sma50_i) / sma50_i * 100 if sma50_i > 0 else 0

    in_killzone, session = _is_killzone(latest.timestamp)

    signals = []

    for direction in ["buy", "sell"]:
        is_uptrend = direction == "buy" and trend_strength > cfg.min_trend_strength
        is_downtrend = direction == "sell" and trend_strength < -cfg.min_trend_strength

        # Regime-aware: in ranging markets, allow counter-trend signals
        if cfg.use_regime_filter and regime:
            if regime.phase in ("consolidation", "range_bound"):
                # Mean reversion mode: trade toward range edges
                is_uptrend = direction == "buy" and latest.close < regime.range_mid
                is_downtrend = direction == "sell" and latest.close > regime.range_mid

        if not (is_uptrend or is_downtrend):
            continue

        confluence_score = 0.0
        reasons = []

        # Pullback check
        if is_uptrend:
            pullback_pct = (latest.close - sma20_i) / sma20_i * 100
            lo, hi = cfg.pullback_range_buy
            if not (lo < pullback_pct < hi):
                continue
            rsi_lo, rsi_hi = cfg.rsi_buy_range
            if not (rsi_lo < rsi_i < rsi_hi):
                continue
        else:
            pullback_pct = (latest.close - sma20_i) / sma20_i * 100
            lo, hi = cfg.pullback_range_sell
            if not (lo < pullback_pct < hi):
                continue
            rsi_lo, rsi_hi = cfg.rsi_sell_range
            if not (rsi_lo < rsi_i < rsi_hi):
                continue

        confluence_score += 0.20
        reasons.append(f"Trend {trend_strength:+.1f}%")

        fvg = _find_nearest_fvg(ordered, fvgs, latest.close, direction)
        if fvg:
            confluence_score += 0.15
            reasons.append(f"FVG {'bull' if fvg.direction == 'bullish' else 'bear'} nearby")

        ob = _find_nearest_ob(ordered, order_blocks, latest.close, direction)
        if ob:
            confluence_score += 0.15
            reasons.append(f"OB {ob.direction} active")

        sweep = _has_liquidity_sweep(liquidity_events, direction)
        if sweep:
            confluence_score += 0.15
            reasons.append("Liquidity sweep reclaimed")

        structure_ok, structure_type = _check_market_structure(ordered, swings, direction)
        if structure_ok:
            confluence_score += 0.10
            reasons.append(f"Structure: {structure_type}")

        vol_conf = _volume_confirmation(ordered, direction)
        if vol_conf >= 1.0:
            confluence_score += 0.10 * vol_conf
            reasons.append(f"Volume {vol_conf:.1f}x")

        if in_killzone:
            confluence_score += 0.10
            reasons.append(f"Killzone: {session}")

        # Required conditions
        if cfg.require_fvg_or_ob and not (fvg or ob):
            continue
        if cfg.require_structure and not structure_ok:
            continue
        if cfg.require_liquidity_sweep and not sweep:
            continue
        if cfg.require_killzone and not in_killzone:
            continue

        if confluence_score < cfg.min_confluence:
            continue

        # Entry/Stop calculation
        if is_uptrend:
            entry = latest.close
            stop = sma50_i
            if ob:
                stop = min(stop, ob.bottom - atr14 * cfg.atr_stop_buffer)
            if fvg:
                stop = min(stop, fvg.bottom - atr14 * cfg.atr_stop_buffer)
            if stop >= entry:
                stop = entry - atr14 * cfg.atr_stop_multiplier
        else:
            entry = latest.close
            stop = sma50_i
            if ob:
                stop = max(stop, ob.top + atr14 * cfg.atr_stop_buffer)
            if fvg:
                stop = max(stop, fvg.top + atr14 * cfg.atr_stop_buffer)
            if stop <= entry:
                stop = entry + atr14 * cfg.atr_stop_multiplier

        risk = abs(entry - stop)
        if risk < atr14 * 0.5:
            continue

        target = entry + (risk * cfg.reward_multiple) if is_uptrend else entry - (risk * cfg.reward_multiple)

        confidence = max(0.40, min(0.92, 0.40 + confluence_score * 0.55))

        # Create simple signal dict for backtest
        from backend.analysis.ids import stable_id
        sig_risk = abs(entry - stop)
        rr = abs(target - entry) / sig_risk if sig_risk > 0 else 0

        signal = type('SimpleSignal', (), {
            'id': stable_id("sel", direction, latest.timestamp, int(entry * 10), int(stop * 10)),
            'timestamp': latest.timestamp,
            'side': direction,
            'entry': round(entry, 2),
            'stop_loss': round(stop, 2),
            'exit_price': round(target, 2),
            'risk_reward': round(rr, 2),
            'confidence': round(confidence, 3),
            'reason': "; ".join(reasons),
        })()
        signals.append(signal)

    if not signals:
        return []
    return [max(signals, key=lambda s: s.confidence)]


# ──────────────────────────────────────────────────────────────
# BACKTEST ENGINE (parameterized)
# ──────────────────────────────────────────────────────────────
from backend.analysis.backtest import BacktestEngine


@dataclass
class BacktestConfig:
    """All tunable backtest engine parameters."""
    initial_balance: float = 10000.0
    position_size_pct: float = 0.02
    max_concurrent: int = 1
    slippage_pct: float = 0.0002
    commission_pct: float = 0.0004
    max_hold_bars: int = 25
    breakeven_threshold: float = 1.0
    trailing_stop: bool = True
    trailing_atr_multiplier: float = 1.0
    partial_exit_pct: float = 0.0   # 0 = no partial exit, 0.5 = exit 50% at 1.5R
    partial_exit_rr: float = 1.5


def run_param_backtest(
    candles: list[Candle],
    signal_cfg: SignalConfig,
    bt_cfg: BacktestConfig,
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
) -> dict:
    """Run backtest with both signal and engine parameters."""
    import uuid
    import math
    from collections import deque

    candles = sorted(candles, key=lambda c: c.timestamp)
    results = []
    equity = []
    balance = bt_cfg.initial_balance
    peak = balance
    open_trades = []

    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []
    metrics = None
    regime = None

    lookback = 80
    min_candles = max(lookback, 50)
    last_signal_ts = 0

    for i in range(min_candles, len(candles)):
        window = candles[:i + 1]
        recent = window[-lookback:]
        current = candles[i]

        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        order_blocks = detect_order_blocks(recent, swings)
        liquidity = detect_equal_levels(swings)

        for c in recent:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)

        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(recent, liquidity, atr)[-80:]
        structure = detect_structure(swings, window)
        regime = detect_market_regime(window, metrics, liquidity_events)

        # Generate signals with current config
        signals = generate_signals_param(
            candles=window,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            cfg=signal_cfg,
            regime=regime,
        )

        new_signals = [s for s in signals if s.timestamp > last_signal_ts]
        last_signal_ts = max((s.timestamp for s in signals), default=last_signal_ts)

        for sig in new_signals:
            if len([t for t in open_trades if t["status"] == "open"]) >= bt_cfg.max_concurrent:
                continue
            if sig.confidence < signal_cfg.min_confidence:
                continue

            risk_per_trade = balance * bt_cfg.position_size_pct
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0

            slippage = sig.entry * bt_cfg.slippage_pct
            entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage
            notional = entry_with_slippage * quantity
            commission = notional * bt_cfg.commission_pct

            tp = sig.exit_price
            trade = {
                "id": str(uuid.uuid4()),
                "signal_id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry_price": round(entry_with_slippage, 2),
                "raw_entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "take_profit": tp,
                "quantity": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "reason": sig.reason,
                "risk_reward": sig.risk_reward,
                "slippage": round(slippage, 2),
                "commission": round(commission, 2),
                "bars_held": 0,
                "partial_exited": False,
            }
            open_trades.append(trade)

        for trade in list(open_trades):
            if trade["status"] != "open":
                continue
            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            qty = trade["quantity"]
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held

            # Trailing stop
            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0 and bt_cfg.trailing_stop:
                if side == "buy":
                    trail_stop = current.high - atr * bt_cfg.trailing_atr_multiplier
                    trade["stop_loss"] = max(trade["stop_loss"], trail_stop)
                    sl = trade["stop_loss"]
                    # Breakeven
                    profit_r = (current.high - entry) / risk
                    if profit_r >= bt_cfg.breakeven_threshold:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    trail_stop = current.low + atr * bt_cfg.trailing_atr_multiplier
                    trade["stop_loss"] = min(trade["stop_loss"], trail_stop)
                    sl = trade["stop_loss"]
                    profit_r = (entry - current.low) / risk
                    if profit_r >= bt_cfg.breakeven_threshold:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]

            # Partial exit
            if bt_cfg.partial_exit_pct > 0 and not trade.get("partial_exited"):
                if side == "buy":
                    partial_tp = entry + risk * bt_cfg.partial_exit_rr
                    if current.high >= partial_tp:
                        partial_qty = qty * bt_cfg.partial_exit_pct
                        partial_pnl = (partial_tp - entry) * partial_qty
                        balance += partial_pnl
                        qty = qty * (1 - bt_cfg.partial_exit_pct)
                        trade["quantity"] = qty
                        trade["partial_exited"] = True
                else:
                    partial_tp = entry - risk * bt_cfg.partial_exit_rr
                    if current.low <= partial_tp:
                        partial_qty = qty * bt_cfg.partial_exit_pct
                        partial_pnl = (entry - partial_tp) * partial_qty
                        balance += partial_pnl
                        qty = qty * (1 - bt_cfg.partial_exit_pct)
                        trade["quantity"] = qty
                        trade["partial_exited"] = True

            # Time-based exit
            if bars_held >= bt_cfg.max_hold_bars:
                exit_price = current.close
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl -= trade["commission"]
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = current.timestamp
                trade["pnl"] = round(pnl, 2)
                trade["pnl_pct"] = round(pnl_pct, 4)
                trade["close_reason"] = "time_exit"
                balance += pnl
                results.append(dict(trade))
                continue

            if side == "buy":
                hit_stop = current.low <= sl
                hit_target = current.high >= tp
            else:
                hit_stop = current.high >= sl
                hit_target = current.low <= tp

            if hit_stop:
                exit_price = sl
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl -= trade["commission"]
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = current.timestamp
                trade["pnl"] = round(pnl, 2)
                trade["pnl_pct"] = round(pnl_pct, 4)
                trade["close_reason"] = "stop_loss"
                balance += pnl
                results.append(dict(trade))
            elif hit_target:
                exit_price = tp
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl -= trade["commission"]
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["exit_timestamp"] = current.timestamp
                trade["pnl"] = round(pnl, 2)
                trade["pnl_pct"] = round(pnl_pct, 4)
                trade["close_reason"] = "target_hit"
                balance += pnl
                results.append(dict(trade))

        if balance > peak:
            peak = balance
        dd = peak - balance
        dd_pct = dd / peak * 100 if peak > 0 else 0

        if i % 5 == 0 or i == len(candles) - 1:
            equity.append({
                "timestamp": current.timestamp,
                "account_balance": round(balance, 2),
                "drawdown": round(dd, 2),
                "drawdown_pct": round(dd_pct, 4),
            })

        total_pnl = balance - bt_cfg.initial_balance
        total_pnl_pct = (total_pnl / bt_cfg.initial_balance) * 100
        closed = [r for r in results if r.get("exit_price") is not None]
        wins = [r for r in closed if r.get("pnl", 0) > 0]
        losses = [r for r in closed if r.get("pnl", 0) <= 0]

        max_dd = max((e["drawdown_pct"] for e in equity), default=0)
        max_dd_val = max((e["drawdown"] for e in equity), default=0)
        avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(r["pnl"] for r in losses) / len(losses)) if losses else 0
        profit_factor = 0.0
        if wins and losses:
            gross_profit = sum(r["pnl"] for r in wins)
            gross_loss = abs(sum(r["pnl"] for r in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        elif wins:
            profit_factor = float("inf")

        returns = [e["account_balance"] / bt_cfg.initial_balance - 1 for e in equity]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_returns = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0
        sharpe = (avg_return / std_returns * math.sqrt(365)) if std_returns > 0 else 0

        max_consecutive_losses = 0
        current_consecutive = 0
        for r in closed:
            if r.get("pnl", 0) <= 0:
                current_consecutive += 1
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
            else:
                current_consecutive = 0

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "initial_balance": bt_cfg.initial_balance,
        "final_balance": round(balance, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "total_trades": len(closed),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(closed), 4) if closed else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.99,
        "max_drawdown": round(max_dd_val, 2),
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "max_consecutive_losses": max_consecutive_losses,
        "trades": results,
        "equity_curve": equity,
    }


# ──────────────────────────────────────────────────────────────
# PARAMETER GRID DEFINITIONS
# ──────────────────────────────────────────────────────────────
SIGNAL_GRID = {
    "min_trend_strength": [0.10, 0.15, 0.20, 0.25],
    "pullback_range_buy": [(-5.0, 1.5), (-4.0, 1.0), (-3.0, 0.5), (-2.0, 0.5)],
    "pullback_range_sell": [(-1.5, 5.0), (-1.0, 4.0), (-0.5, 3.0), (-0.5, 2.0)],
    "rsi_buy_range": [(15, 70), (20, 65), (25, 60), (30, 55)],
    "rsi_sell_range": [(30, 85), (35, 80), (40, 75), (45, 70)],
    "min_confluence": [0.25, 0.30, 0.35, 0.40],
    "min_confidence": [0.35, 0.40, 0.45, 0.50],
    "reward_multiple": [2.0, 2.5, 3.0, 3.5],
    "require_killzone": [False, True],
    "require_structure": [False, True],
    "require_liquidity_sweep": [False],
    "require_fvg_or_ob": [True, False],
    "use_regime_filter": [True, False],
    "atr_stop_multiplier": [1.0, 1.5, 2.0],
    "atr_stop_buffer": [0.2, 0.3, 0.5],
}

BACKTEST_GRID = {
    "position_size_pct": [0.01, 0.015, 0.02, 0.025],
    "max_hold_bars": [12, 18, 25, 35],
    "breakeven_threshold": [0.5, 0.8, 1.0, 1.5],
    "trailing_stop": [True, False],
    "trailing_atr_multiplier": [0.8, 1.0, 1.5, 2.0],
    "partial_exit_pct": [0.0, 0.3, 0.5],
    "partial_exit_rr": [1.5, 2.0],
    "slippage_pct": [0.0001, 0.0002, 0.0004],
    "commission_pct": [0.0004, 0.0006, 0.0008],
}


def generate_combinations(grid: dict, max_combos: int = 500) -> list[dict]:
    """Generate parameter combinations, prioritizing diversity."""
    keys = list(grid.keys())
    values = [grid[k] for k in keys]
    all_combos = list(itertools.product(*values))

    # If too many, sample strategically
    if len(all_combos) > max_combos:
        import random
        random.seed(42)
        # First, get the extremes and middle values
        sampled = []
        # Add first combo (all first values)
        sampled.append(all_combos[0])
        # Add last combo (all last values)
        sampled.append(all_combos[-1])
        # Add random samples
        remaining = max_combos - 2
        if remaining > 0:
            sampled.extend(random.sample(all_combos[1:-1], min(remaining, len(all_combos) - 2)))
        all_combos = sampled

    return [dict(zip(keys, combo)) for combo in all_combos]


def score_config(result: dict) -> float:
    """Score a configuration. Higher is better."""
    trades = result["total_trades"]
    if trades < 10:
        return -1000  # Penalize too few trades

    wr = result["win_rate"]
    pf = result["profit_factor"]
    dd = result["max_drawdown_pct"]
    sharpe = result["sharpe_ratio"]
    pnl_pct = result["total_pnl_pct"]

    # Minimum trade count bonus (more trades = more reliable)
    trade_bonus = min(trades / 100.0, 1.0) * 10

    # Core metrics scoring
    wr_score = wr * 50  # 0-50 points
    pf_score = min(pf, 5.0) * 10  # 0-50 points
    dd_penalty = max(0, (dd - 5.0)) * 3  # Penalize DD > 5%
    sharpe_score = max(sharpe, -5.0) * 3  # -15 to +15
    pnl_score = min(pnl_pct, 50.0) * 0.5  # 0-25 points

    # Consistency bonus
    consistency = 1.0 if wr >= 0.40 and pf >= 1.3 else 0.5

    total = wr_score + pf_score - dd_penalty + sharpe_score + pnl_score + trade_bonus
    return total * consistency


# ──────────────────────────────────────────────────────────────
# MAIN OPTIMIZER
# ──────────────────────────────────────────────────────────────
async def main():
    print("=" * 80)
    print("  NEXUS COMPREHENSIVE STRATEGY OPTIMIZER")
    print("=" * 80)

    # Fetch data
    print("\n[1/5] Fetching historical data...")
    data = await fetch_multi_timeframe(
        symbol="BTCUSDT",
        intervals=["5m", "15m", "1h"],
        limit=1000,
    )

    best_overall = None
    best_score = -float("inf")
    all_results = []

    for tf, candles in data.items():
        if len(candles) < 100:
            print(f"\n  Skipping {tf}: only {len(candles)} candles")
            continue

        print(f"\n{'=' * 80}")
        print(f"  OPTIMIZING {tf} TIMEFRAME ({len(candles)} candles)")
        print(f"{'=' * 80}")

        # Generate signal configs
        print("\n[2/5] Generating signal parameter combinations...")
        signal_combos = generate_combinations(SIGNAL_GRID, max_combos=200)
        print(f"  {len(signal_combos)} signal configs")

        # Generate backtest configs
        print("\n[3/5] Generating backtest parameter combinations...")
        bt_combos = generate_combinations(BACKTEST_GRID, max_combos=100)
        print(f"  {len(bt_combos)} backtest configs")

        # Phase 1: Quick scan - test signal configs with default backtest
        print(f"\n[4/5] Phase 1: Quick signal scan ({len(signal_combos)} configs)...")
        default_bt = BacktestConfig()
        signal_results = []

        for idx, sc in enumerate(signal_combos):
            sig_cfg = SignalConfig(**sc)
            try:
                result = run_param_backtest(candles, sig_cfg, default_bt, timeframe=tf)
                sc_score = score_config(result)
                signal_results.append((sc_score, sig_cfg, result))
            except Exception as e:
                print(f"    Config {idx} failed: {e}")
                continue

            if (idx + 1) % 50 == 0:
                print(f"    Progress: {idx + 1}/{len(signal_combos)}")

        # Sort by score, keep top 20
        signal_results.sort(key=lambda x: x[0], reverse=True)
        top_signals = signal_results[:20]

        print(f"\n  Top 5 signal configs:")
        for rank, (score, cfg, res) in enumerate(top_signals[:5], 1):
            print(f"    #{rank}: Score={score:.1f} | Trades={res['total_trades']} | WR={res['win_rate']*100:.1f}% | PF={res['profit_factor']:.2f} | PnL={res['total_pnl_pct']:.2f}%")

        # Phase 2: Deep scan - test top signal configs with various backtest configs
        print(f"\n[5/5] Phase 2: Deep backtest scan ({len(top_signals)} signal × {len(bt_combos)} engine configs)...")
        total_combos = len(top_signals) * len(bt_combos)
        combo_idx = 0

        for sig_score, sig_cfg, _ in top_signals:
            for bt_sc in bt_combos:
                bt_cfg = BacktestConfig(**bt_sc)
                try:
                    result = run_param_backtest(candles, sig_cfg, bt_cfg, timeframe=tf)
                    total_score = score_config(result)

                    combo_result = {
                        "timeframe": tf,
                        "signal_config": {
                            "min_trend_strength": sig_cfg.min_trend_strength,
                            "pullback_range_buy": sig_cfg.pullback_range_buy,
                            "pullback_range_sell": sig_cfg.pullback_range_sell,
                            "rsi_buy_range": sig_cfg.rsi_buy_range,
                            "rsi_sell_range": sig_cfg.rsi_sell_range,
                            "min_confluence": sig_cfg.min_confluence,
                            "min_confidence": sig_cfg.min_confidence,
                            "reward_multiple": sig_cfg.reward_multiple,
                            "require_killzone": sig_cfg.require_killzone,
                            "require_structure": sig_cfg.require_structure,
                            "require_liquidity_sweep": sig_cfg.require_liquidity_sweep,
                            "require_fvg_or_ob": sig_cfg.require_fvg_or_ob,
                            "use_regime_filter": sig_cfg.use_regime_filter,
                            "atr_stop_multiplier": sig_cfg.atr_stop_multiplier,
                            "atr_stop_buffer": sig_cfg.atr_stop_buffer,
                        },
                        "backtest_config": {
                            "position_size_pct": bt_cfg.position_size_pct,
                            "max_hold_bars": bt_cfg.max_hold_bars,
                            "breakeven_threshold": bt_cfg.breakeven_threshold,
                            "trailing_stop": bt_cfg.trailing_stop,
                            "trailing_atr_multiplier": bt_cfg.trailing_atr_multiplier,
                            "partial_exit_pct": bt_cfg.partial_exit_pct,
                            "partial_exit_rr": bt_cfg.partial_exit_rr,
                            "slippage_pct": bt_cfg.slippage_pct,
                            "commission_pct": bt_cfg.commission_pct,
                        },
                        "results": {
                            "total_trades": result["total_trades"],
                            "win_rate": result["win_rate"],
                            "profit_factor": result["profit_factor"],
                            "max_drawdown_pct": result["max_drawdown_pct"],
                            "sharpe_ratio": result["sharpe_ratio"],
                            "total_pnl_pct": result["total_pnl_pct"],
                            "avg_win": result["avg_win"],
                            "avg_loss": result["avg_loss"],
                        },
                        "score": total_score,
                    }
                    all_results.append(combo_result)

                    if total_score > best_score:
                        best_score = total_score
                        best_overall = combo_result

                except Exception as e:
                    continue

                combo_idx += 1
                if combo_idx % 100 == 0:
                    print(f"    Progress: {combo_idx}/{total_combos} | Best score so far: {best_score:.1f}")

        print(f"\n  Best {tf} config score: {best_score:.1f}")

    # Final results
    print(f"\n{'=' * 80}")
    print(f"  FINAL OPTIMIZATION RESULTS")
    print(f"{'=' * 80}")

    # Sort all results by score
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n  TOP 10 CONFIGURATIONS:")
    print(f"  {'#':<3} {'TF':<5} {'Score':<8} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8}")
    print(f"  {'-' * 60}")

    for rank, r in enumerate(all_results[:10], 1):
        res = r["results"]
        print(
            f"  {rank:<3} "
            f"{r['timeframe']:<5} "
            f"{r['score']:<8.1f} "
            f"{res['total_trades']:<7} "
            f"{res['win_rate']*100:<6.1f} "
            f"{res['profit_factor']:<6.2f} "
            f"{res['max_drawdown_pct']:<6.2f} "
            f"{res['sharpe_ratio']:<7.2f} "
            f"{res['total_pnl_pct']:<8.2f}"
        )

    if best_overall:
        print(f"\n{'=' * 80}")
        print(f"  ABSOLUTE BEST CONFIGURATION (Score: {best_score:.1f})")
        print(f"{'=' * 80}")

        print(f"\n  TIMEFRAME: {best_overall['timeframe']}")

        print(f"\n  SIGNAL PARAMETERS:")
        for k, v in best_overall["signal_config"].items():
            print(f"    {k}: {v}")

        print(f"\n  BACKTEST PARAMETERS:")
        for k, v in best_overall["backtest_config"].items():
            print(f"    {k}: {v}")

        print(f"\n  RESULTS:")
        for k, v in best_overall["results"].items():
            if isinstance(v, float):
                print(f"    {k}: {v:.4f}")
            else:
                print(f"    {k}: {v}")

        # Save to file
        output = {
            "best_config": best_overall,
            "top_10": all_results[:10],
            "all_results_count": len(all_results),
            "timestamp": time.time(),
        }

        output_path = Path(__file__).parent.parent / "optimization_results.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
