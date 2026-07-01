"""
NEXUS Production Backtest Optimizer - FAST VERSION

Precomputes analysis state once, then tests different trade management configs.
Uses the REAL production signal engine with psychology + readability.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.price_action_readability import assess_price_action_readability
from backend.analysis.regime import detect_market_regime
from backend.analysis.signals import detect_trade_signals
from backend.analysis.swing_detector import detect_swings
from backend.models.types import Candle


# ─── Data Fetching ──────────────────────────────────────────

async def fetch_binance_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 1000,
    start_time: int | None = None,
) -> list[Candle]:
    url = "https://api.binance.com/api/v3/klines"
    params: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "limit": min(limit, 1000),
    }
    if start_time:
        params["startTime"] = start_time

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    return [
        Candle(
            timestamp=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            is_closed=True,
        )
        for k in data
    ]


async def fetch_historical_range(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    days: int = 30,
) -> list[Candle]:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    all_candles: list[Candle] = []

    current = start_ms
    while current < now_ms:
        batch = await fetch_binance_candles(symbol, interval, 1000, current)
        if not batch:
            break
        all_candles.extend(batch)
        current = batch[-1].timestamp + 60000
        print(f"  Fetched {len(all_candles)} candles...")
        await asyncio.sleep(0.2)

    seen = set()
    unique = []
    for c in all_candles:
        if c.timestamp not in seen:
            seen.add(c.timestamp)
            unique.append(c)

    return sorted(unique, key=lambda c: c.timestamp)


# ─── Precomputed Analysis State ─────────────────────────────

@dataclass
class AnalysisSnapshot:
    """Precomputed analysis at each candle index."""
    signals: list  # TradeSignal objects
    regime: Any
    psychology: Any
    readability: Any
    metrics: Any
    atr: float


def precompute_analysis(candles: list[Candle], lookback: int = 80) -> dict[int, AnalysisSnapshot]:
    """Run full analysis pipeline once for all candles."""
    snapshots = {}
    min_candles = max(lookback, 50)

    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []

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
        regime = detect_market_regime(window, metrics, liquidity_events)

        psychology = detect_market_psychology(window, liquidity_events, regime)
        readability = assess_price_action_readability(window, swings, liquidity, regime)

        signals = detect_trade_signals(
            candles=window,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            regime=regime,
            psychology=psychology,
            readability=readability,
        )

        snapshots[i] = AnalysisSnapshot(
            signals=signals,
            regime=regime,
            psychology=psychology,
            readability=readability,
            metrics=metrics,
            atr=atr,
        )

    return snapshots


# ─── Trade Management Config ────────────────────────────────

@dataclass
class TradeConfig:
    """Only trade management parameters (fast to test)."""
    name: str
    min_confidence: float = 0.55
    max_hold_bars: int = 10
    trailing_stop: bool = True
    trailing_atr_mult: float = 1.5
    breakeven_at_r: float = 1.0
    reward_multiple: float = 3.0
    position_size_pct: float = 0.02
    max_concurrent: int = 1
    slippage_pct: float = 0.0001
    commission_pct: float = 0.0002
    # Signal filters
    require_killzone: bool = False
    avoid_extreme_fear_shorts: bool = True
    avoid_extreme_greed_longs: bool = True
    min_readability_grade: str = "C"
    # Psychology/readability toggle
    use_psychology: bool = True
    use_readability: bool = True


GRADE_ORDER = {"F": 0, "D": 1, "C": 2, "C+": 3, "B": 4, "B+": 5, "A": 6, "A+": 7}


def grade_meets_minimum(grade: str, minimum: str) -> bool:
    return GRADE_ORDER.get(grade, 0) >= GRADE_ORDER.get(minimum, 0)


# ─── Fast Backtest (uses precomputed analysis) ──────────────

def run_fast_backtest(
    candles: list[Candle],
    snapshots: dict[int, AnalysisSnapshot],
    config: TradeConfig,
) -> dict:
    initial_balance = 10_000.0
    balance = initial_balance
    peak = balance
    open_trades: list[dict] = []
    closed_trades: list[dict] = []
    equity: list[dict] = []
    returns: list[float] = []

    sorted_indices = sorted(snapshots.keys())

    for i in sorted_indices:
        snap = snapshots[i]
        current = candles[i]

        # Process signals
        for sig in snap.signals:
            if len([t for t in open_trades if t["status"] == "open"]) >= config.max_concurrent:
                continue

            if sig.confidence < config.min_confidence:
                continue

            # Killzone filter
            if config.require_killzone:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(sig.timestamp / 1000, tz=timezone.utc)
                hour = dt.hour + dt.minute / 60.0
                in_kz = (2.0 <= hour < 5.0) or (8.5 <= hour < 11.0) or (13.5 <= hour < 16.0)
                if not in_kz:
                    continue

            # Readability filter
            if config.use_readability and snap.readability:
                if not grade_meets_minimum(snap.readability.grade, config.min_readability_grade):
                    continue

            # Psychology conflict filter
            if config.use_psychology and snap.psychology:
                if config.avoid_extreme_fear_shorts and snap.psychology.fear_greed_label == "extreme_fear" and sig.side == "sell":
                    continue
                if config.avoid_extreme_greed_longs and snap.psychology.fear_greed_label == "extreme_greed" and sig.side == "buy":
                    continue

            risk_per_trade = balance * config.position_size_pct
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
            if quantity <= 0:
                continue

            slippage = sig.entry * config.slippage_pct
            entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage
            notional = entry_with_slippage * quantity
            commission = notional * config.commission_pct

            trade = {
                "id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry_price": round(entry_with_slippage, 2),
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "take_profit": sig.exit_price,
                "quantity": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "reason": sig.reason,
                "commission": round(commission, 2),
                "bars_held": 0,
                "psychology_fg": snap.psychology.fear_greed_label if snap.psychology else "unknown",
                "readability_grade": snap.readability.grade if snap.readability else "unknown",
            }
            open_trades.append(trade)

        # Manage open trades
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
            if config.trailing_stop:
                risk = abs(entry - trade.get("initial_sl", sl))
                if risk > 0:
                    if side == "buy":
                        profit_r = (current.high - entry) / risk
                        if profit_r >= config.breakeven_at_r:
                            trade["stop_loss"] = max(trade["stop_loss"], entry)
                            sl = trade["stop_loss"]
                        if profit_r >= config.trailing_atr_mult:
                            trail = current.high - snap.atr * config.trailing_atr_mult
                            trade["stop_loss"] = max(trade["stop_loss"], trail)
                            sl = trade["stop_loss"]
                    else:
                        profit_r = (entry - current.low) / risk
                        if profit_r >= config.breakeven_at_r:
                            trade["stop_loss"] = min(trade["stop_loss"], entry)
                            sl = trade["stop_loss"]
                        if profit_r >= config.trailing_atr_mult:
                            trail = current.low + snap.atr * config.trailing_atr_mult
                            trade["stop_loss"] = min(trade["stop_loss"], trail)
                            sl = trade["stop_loss"]

            # Time exit
            if bars_held >= config.max_hold_bars:
                exit_price = current.close
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed",
                    "exit_price": exit_price,
                    "exit_timestamp": current.timestamp,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl / (entry * qty) * 100 if entry * qty > 0 else 0, 4),
                    "close_reason": "time_exit",
                })
                balance += pnl
                returns.append(pnl / initial_balance)
                closed_trades.append(dict(trade))
                continue

            # Check SL / TP
            if side == "buy":
                hit_stop = current.low <= sl
                hit_target = current.high >= tp
            else:
                hit_stop = current.high >= sl
                hit_target = current.low <= tp

            if hit_stop:
                pnl = (sl - entry) * qty if side == "buy" else (entry - sl) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed",
                    "exit_price": sl,
                    "exit_timestamp": current.timestamp,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl / (entry * qty) * 100 if entry * qty > 0 else 0, 4),
                    "close_reason": "stop_loss",
                })
                balance += pnl
                returns.append(pnl / initial_balance)
                closed_trades.append(dict(trade))
            elif hit_target:
                pnl = (tp - entry) * qty if side == "buy" else (entry - tp) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed",
                    "exit_price": tp,
                    "exit_timestamp": current.timestamp,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl / (entry * qty) * 100 if entry * qty > 0 else 0, 4),
                    "close_reason": "target_hit",
                })
                balance += pnl
                returns.append(pnl / initial_balance)
                closed_trades.append(dict(trade))

        # Track equity
        if balance > peak:
            peak = balance
        dd = peak - balance
        dd_pct = dd / peak * 100 if peak > 0 else 0

        if i % 10 == 0 or i == sorted_indices[-1]:
            equity.append({
                "timestamp": current.timestamp,
                "balance": round(balance, 2),
                "drawdown_pct": round(dd_pct, 4),
            })

    # Compute stats
    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    total_pnl = balance - initial_balance
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0)

    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0
    max_dd = max((e["drawdown_pct"] for e in equity), default=0)

    if returns and len(returns) > 1:
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe = (avg_ret / std_ret * (365 * 288) ** 0.5) if std_ret > 0 else 0
    else:
        sharpe = 0

    max_consec_loss = 0
    cur_consec = 0
    for t in closed_trades:
        if t.get("pnl", 0) <= 0:
            cur_consec += 1
            max_consec_loss = max(max_consec_loss, cur_consec)
        else:
            cur_consec = 0

    bh_return = (candles[-1].close - candles[sorted_indices[0]].close) / candles[sorted_indices[0]].close * 100

    return {
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_balance * 100, 2),
        "final_balance": round(balance, 2),
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(closed_trades), 4) if closed_trades else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != 999.99 else 999.99,
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_consecutive_losses": max_consec_loss,
        "buy_hold_return_pct": round(bh_return, 2),
        "candle_count": len(candles),
        "trades": closed_trades,
        "equity_curve": equity,
    }


# ─── Parameter Grid ─────────────────────────────────────────

def generate_configs() -> list[TradeConfig]:
    """Generate trade management configs to test."""
    configs = []

    # Core combos: psychology/readability on/off + confidence + trailing + RR + bars
    for use_psych in [True, False]:
        for use_read in [True, False]:
            for min_conf in [0.55, 0.60, 0.65]:
                for trailing in [True, False]:
                    for trail_mult in [1.0, 1.5, 2.0]:
                        for max_bars in [8, 12, 16]:
                            for rr in [2.0, 3.0, 4.0]:
                                configs.append(TradeConfig(
                                    name=f"psych={'Y' if use_psych else 'N'}_read={'Y' if use_read else 'N'}_conf{min_conf}_trail{'Y' if trailing else 'N'}_tm{trail_mult}_bars{max_bars}_rr{rr}",
                                    use_psychology=use_psych,
                                    use_readability=use_read,
                                    min_confidence=min_conf,
                                    trailing_stop=trailing,
                                    trailing_atr_mult=trail_mult,
                                    max_hold_bars=max_bars,
                                    reward_multiple=rr,
                                ))

    # Killzone + grade filter combos
    for use_psych in [True, False]:
        for use_read in [True, False]:
            for min_conf in [0.55, 0.60]:
                for min_grade in ["B", "B+"]:
                    configs.append(TradeConfig(
                        name=f"psych={'Y' if use_psych else 'N'}_read={'Y' if use_read else 'N'}_conf{min_conf}_kz_grade{min_grade}",
                        use_psychology=use_psych,
                        use_readability=use_read,
                        min_confidence=min_conf,
                        trailing_stop=True,
                        max_hold_bars=10,
                        reward_multiple=3.0,
                        require_killzone=True,
                        min_readability_grade=min_grade,
                    ))

    return configs


def score_config(result: dict) -> float:
    """Score a backtest result for ranking."""
    if result["total_trades"] < 5:
        return -1000

    win_rate = result["win_rate"]
    pf = result["profit_factor"]
    dd = result["max_drawdown_pct"]
    sharpe = result["sharpe_ratio"]
    pnl_pct = result["total_pnl_pct"]
    trades = result["total_trades"]

    score = (
        win_rate * 30 +
        min(pf, 3.0) * 15 +
        max(0, 30 - dd) * 0.5 +
        max(0, sharpe) * 10 +
        min(pnl_pct, 100) * 0.2 +
        min(trades, 50) * 0.2
    )

    if dd > 20:
        score -= (dd - 20) * 2
    if win_rate < 0.40:
        score -= 20
    if result["max_consecutive_losses"] > 5:
        score -= 10

    return score


# ─── Main ───────────────────────────────────────────────────

async def main():
    print("=" * 70)
    print("NEXUS PRODUCTION BACKTEST OPTIMIZER (FAST)")
    print("=" * 70)

    # Fetch data
    print("\n[1/4] Fetching BTCUSDT 5m candles from Binance...")
    try:
        candles = await fetch_historical_range("BTCUSDT", "5m", days=30)
        print(f"  Loaded {len(candles)} candles ({len(candles) * 5 / 60 / 24:.1f} days)")
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Falling back to 1000 candles")
        candles = await fetch_binance_candles("BTCUSDT", "5m", 1000)
        print(f"  Loaded {len(candles)} candles")

    if len(candles) < 100:
        print("ERROR: Not enough data")
        return

    # Precompute analysis (slow, done once)
    print(f"\n[2/4] Precomputing analysis pipeline ({len(candles)} candles)...")
    t0 = time.time()
    snapshots = precompute_analysis(candles)
    analysis_time = time.time() - t0
    print(f"  Analysis precomputed in {analysis_time:.1f}s ({len(snapshots)} snapshots)")

    # Generate configs
    all_configs = generate_configs()
    print(f"\n[3/4] Testing {len(all_configs)} trade management configs...")

    results = []
    t_start = time.time()

    for idx, config in enumerate(all_configs):
        try:
            result = run_fast_backtest(candles, snapshots, config)
            result["config_name"] = config.name
            result["config"] = {
                "use_psychology": config.use_psychology,
                "use_readability": config.use_readability,
                "min_confidence": config.min_confidence,
                "trailing_stop": config.trailing_stop,
                "trailing_atr_mult": config.trailing_atr_mult,
                "max_hold_bars": config.max_hold_bars,
                "reward_multiple": config.reward_multiple,
                "require_killzone": config.require_killzone,
                "min_readability_grade": config.min_readability_grade,
            }
            result["score"] = score_config(result)
            results.append(result)
        except Exception as e:
            pass

        if (idx + 1) % 50 == 0:
            elapsed = time.time() - t_start
            rate = (idx + 1) / elapsed
            eta = (len(all_configs) - idx - 1) / rate
            print(f"  Progress: {idx + 1}/{len(all_configs)} ({elapsed:.0f}s, ~{eta:.0f}s remaining)")

    elapsed = time.time() - t_start
    print(f"\n  Completed in {elapsed:.1f}s (analysis: {analysis_time:.1f}s, configs: {elapsed - analysis_time:.1f}s)")

    # Sort and display
    results.sort(key=lambda r: r["score"], reverse=True)

    print(f"\n[4/4] TOP 15 SETUPS (ranked by score)")
    print("=" * 140)
    print(f"{'#':<3} {'Name':<50} {'PnL%':>8} {'Win%':>6} {'PF':>6} {'Sharpe':>8} {'DD%':>7} {'Trades':>6} {'Score':>7}")
    print("-" * 140)

    for i, r in enumerate(results[:15]):
        name = r["config_name"][:50]
        print(
            f"{i+1:<3} {name:<50} "
            f"{r['total_pnl_pct']:>+7.2f}% "
            f"{r['win_rate']*100:>5.1f}% "
            f"{r['profit_factor']:>5.2f} "
            f"{r['sharpe_ratio']:>7.3f} "
            f"{r['max_drawdown_pct']:>6.1f}% "
            f"{r['total_trades']:>6} "
            f"{r['score']:>7.1f}"
        )

    # Best config detail
    if results:
        best = results[0]
        bc = best["config"]
        print(f"\n{'=' * 70}")
        print(f"BEST CONFIGURATION: {best['config_name']}")
        print(f"  Psychology:           {'ON' if bc['use_psychology'] else 'OFF'}")
        print(f"  Readability:          {'ON' if bc['use_readability'] else 'OFF'}")
        print(f"  Min Confidence:       {bc['min_confidence']}")
        print(f"  Trailing Stop:        {'ON' if bc['trailing_stop'] else 'OFF'} (ATR x{bc['trailing_atr_mult']})")
        print(f"  Max Hold Bars:        {bc['max_hold_bars']}")
        print(f"  Reward Multiple:      {bc['reward_multiple']}R")
        print(f"  Require Killzone:     {'YES' if bc['require_killzone'] else 'NO'}")
        print(f"  Min Readability:      {bc['min_readability_grade']}")
        print(f"\n  RESULTS:")
        print(f"  Total PnL:            ${best['total_pnl']:.2f} ({best['total_pnl_pct']:.2f}%)")
        print(f"  Win Rate:             {best['win_rate']*100:.1f}%")
        print(f"  Profit Factor:        {best['profit_factor']:.2f}")
        print(f"  Sharpe Ratio:         {best['sharpe_ratio']:.3f}")
        print(f"  Max Drawdown:         {best['max_drawdown_pct']:.1f}%")
        print(f"  Total Trades:         {best['total_trades']}")
        print(f"  Buy & Hold Return:    {best['buy_hold_return_pct']:.2f}%")
        print(f"  Score:                {best['score']:.1f}")

        # Psychology breakdown
        fg_breakdown = {}
        for t in best["trades"]:
            fg = t.get("psychology_fg", "unknown")
            if fg not in fg_breakdown:
                fg_breakdown[fg] = {"trades": 0, "wins": 0, "pnl": 0}
            fg_breakdown[fg]["trades"] += 1
            fg_breakdown[fg]["pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                fg_breakdown[fg]["wins"] += 1

        print(f"\n  BY PSYCHOLOGY STATE:")
        for state, stats in sorted(fg_breakdown.items(), key=lambda x: x[1]["pnl"], reverse=True):
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            print(f"    {state:<15} {stats['trades']:>3} trades  WR: {wr:>5.1f}%  PnL: ${stats['pnl']:>+8.2f}")

        # Readability breakdown
        grade_breakdown = {}
        for t in best["trades"]:
            g = t.get("readability_grade", "unknown")
            if g not in grade_breakdown:
                grade_breakdown[g] = {"trades": 0, "wins": 0, "pnl": 0}
            grade_breakdown[g]["trades"] += 1
            grade_breakdown[g]["pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                grade_breakdown[g]["wins"] += 1

        print(f"\n  BY READABILITY GRADE:")
        for grade, stats in sorted(grade_breakdown.items(), key=lambda x: GRADE_ORDER.get(x[0], 0)):
            wr = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
            print(f"    {grade:<5} {stats['trades']:>3} trades  WR: {wr:>5.1f}%  PnL: ${stats['pnl']:>+8.2f}")

        # Psychology vs Readability comparison
        print(f"\n  PSYCHOLOGY IMPACT:")
        psych_on = [r for r in results if r["config"]["use_psychology"]]
        psych_off = [r for r in results if not r["config"]["use_psychology"]]
        if psych_on and psych_off:
            avg_on = sum(r["total_pnl_pct"] for r in psych_on) / len(psych_on)
            avg_off = sum(r["total_pnl_pct"] for r in psych_off) / len(psych_off)
            print(f"    With psychology:    avg PnL {avg_on:+.2f}% ({len(psych_on)} configs)")
            print(f"    Without psychology: avg PnL {avg_off:+.2f}% ({len(psych_off)} configs)")
            print(f"    Difference:         {avg_on - avg_off:+.2f}%")

        print(f"\n  READABILITY IMPACT:")
        read_on = [r for r in results if r["config"]["use_readability"]]
        read_off = [r for r in results if not r["config"]["use_readability"]]
        if read_on and read_off:
            avg_on = sum(r["total_pnl_pct"] for r in read_on) / len(read_on)
            avg_off = sum(r["total_pnl_pct"] for r in read_off) / len(read_off)
            print(f"    With readability:    avg PnL {avg_on:+.2f}% ({len(read_on)} configs)")
            print(f"    Without readability: avg PnL {avg_off:+.2f}% ({len(read_off)} configs)")
            print(f"    Difference:          {avg_on - avg_off:+.2f}%")

    # Save results
    output = {
        "timestamp": int(time.time() * 1000),
        "candle_count": len(candles),
        "configs_tested": len(results),
        "analysis_time_sec": round(analysis_time, 1),
        "top_15": [
            {
                "name": r["config_name"],
                "config": r["config"],
                "pnl_pct": r["total_pnl_pct"],
                "win_rate": r["win_rate"],
                "profit_factor": r["profit_factor"],
                "sharpe": r["sharpe_ratio"],
                "max_dd": r["max_drawdown_pct"],
                "trades": r["total_trades"],
                "score": r["score"],
            }
            for r in results[:15]
        ],
    }

    with open("optimization_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to optimization_results.json")


if __name__ == "__main__":
    asyncio.run(main())
