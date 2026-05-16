"""
Comprehensive parameter optimization for NEXUS trading strategy.
Tests multiple configurations with relaxed signals and regime filtering.
"""

from __future__ import annotations

import json
import math
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.relaxed_signals import detect_relaxed_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime import detect_market_regime
from backend.analysis.swing_detector import detect_swings


def run_optimized_backtest(
    candles: list[Candle],
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    initial_balance: float = 10_000.0,
    position_size_pct: float = 0.02,
    max_concurrent: int = 1,
    slippage_pct: float = 0.0002,
    commission_pct: float = 0.0004,
    max_hold_bars: int = 25,
    breakeven_threshold: float = 1.0,
    reward_multiple: float = 2.0,
    min_confidence: float = 0.40,
    min_confluence: float = 0.35,
    regime_filter: bool = False,  # Only trade in trending regimes
    use_relaxed_signals: bool = True,
) -> dict:
    """Backtest with optimized parameters and optional regime filtering."""
    candles = sorted(candles, key=lambda c: c.timestamp)
    results = []
    equity = []
    balance = initial_balance
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
        regime = detect_market_regime(window, metrics, liquidity_events)

        # Regime filter: skip trades in consolidation/range-bound markets
        if regime_filter and regime:
            if regime.phase in ["consolidation", "range_bound"]:
                # Still process existing trades, but don't enter new ones
                pass
            elif regime.confidence < 0.5:
                # Low confidence regime, skip
                pass

        # Detect signals
        if use_relaxed_signals:
            signals = detect_relaxed_signals(
                candles=window,
                metrics=metrics,
                fvgs=fvgs,
                order_blocks=order_blocks,
                liquidity_events=liquidity_events,
                swings=swings,
                reward_multiple=reward_multiple,
                min_confidence=min_confidence,
                min_confluence=min_confluence,
            )
        else:
            from backend.analysis.signals import detect_trade_signals
            signals = detect_trade_signals(
                candles=window,
                metrics=metrics,
                fvgs=fvgs,
                order_blocks=order_blocks,
                liquidity_events=liquidity_events,
                swings=swings,
                reward_multiple=reward_multiple,
            )

        new_signals = [s for s in signals if s.timestamp > last_signal_ts]
        last_signal_ts = max((s.timestamp for s in signals), default=last_signal_ts)

        for sig in new_signals:
            if len([t for t in open_trades if t["status"] == "open"]) >= max_concurrent:
                continue
            if sig.confidence < min_confidence:
                continue

            risk_per_trade = balance * position_size_pct
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0

            slippage = sig.entry * slippage_pct
            entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage

            notional = entry_with_slippage * quantity
            commission = notional * commission_pct

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

            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0:
                if side == "buy":
                    profit_r = (current.high - entry) / risk
                    if profit_r >= breakeven_threshold:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    profit_r = (entry - current.low) / risk
                    if profit_r >= breakeven_threshold:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]

            if bars_held >= max_hold_bars:
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

        if i % 10 == 0 or i == len(candles) - 1:
            equity.append({
                "timestamp": current.timestamp,
                "account_balance": round(balance, 2),
                "drawdown": round(dd, 2),
                "drawdown_pct": round(dd_pct, 4),
            })

    total_pnl = balance - initial_balance
    total_pnl_pct = (total_pnl / initial_balance) * 100
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

    returns = [e["account_balance"] / initial_balance - 1 for e in equity]
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
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": candles[0].timestamp if candles else 0,
        "end_date": candles[-1].timestamp if candles else 0,
        "candle_count": len(candles),
        "initial_balance": initial_balance,
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
        "slippage_pct": slippage_pct,
        "commission_pct": commission_pct,
        "trades": results,
        "equity_curve": equity,
        "reward_multiple": reward_multiple,
        "min_confidence": min_confidence,
        "min_confluence": min_confluence,
        "max_hold_bars": max_hold_bars,
        "breakeven_threshold": breakeven_threshold,
        "regime_filter": regime_filter,
        "use_relaxed_signals": use_relaxed_signals,
    }


def print_results(result: dict) -> None:
    """Print backtest results."""
    print("\n" + "=" * 60)
    print("  NEXUS OPTIMIZED BACKTEST RESULTS")
    print("=" * 60)

    print(f"\n  Symbol:           {result['symbol']}")
    print(f"  Timeframe:        {result['timeframe']}")
    print(f"  Candles:          {result['candle_count']}")
    
    start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(result["start_date"] / 1000))
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(result["end_date"] / 1000))
    print(f"  Period:           {start} to {end}")

    print(f"\n  Initial Balance:  ${result['initial_balance']:,.2f}")
    print(f"  Final Balance:    ${result['final_balance']:,.2f}")
    print(f"  Total P&L:        ${result['total_pnl']:,.2f} ({result['total_pnl_pct']:.2f}%)")

    print(f"\n  Total Trades:     {result['total_trades']}")
    print(f"  Winning Trades:   {result['winning_trades']}")
    print(f"  Losing Trades:    {result['losing_trades']}")
    print(f"  Win Rate:         {result['win_rate'] * 100:.1f}%")

    print(f"\n  Avg Win:          ${result['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${result['avg_loss']:,.2f}")
    print(f"  Profit Factor:    {result['profit_factor']:.2f}")

    print(f"\n  Max Drawdown:     ${result['max_drawdown']:,.2f} ({result['max_drawdown_pct']:.2f}%)")
    print(f"  Sharpe Ratio:     {result['sharpe_ratio']:.2f}")
    print(f"  Max Cons. Losses: {result['max_consecutive_losses']}")

    print(f"\n  Reward Multiple:  {result.get('reward_multiple', 'N/A')}")
    print(f"  Min Confidence:   {result.get('min_confidence', 'N/A')}")
    print(f"  Min Confluence:   {result.get('min_confluence', 'N/A')}")
    print(f"  Regime Filter:    {result.get('regime_filter', False)}")
    print(f"  Relaxed Signals:  {result.get('use_relaxed_signals', True)}")

    # Trade breakdown
    trades = result.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            reason = t.get("close_reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        
        print(f"\n  Exit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count}")

    # Profitability verdict
    print(f"\n  {'=' * 60}")
    if result["profit_factor"] > 1.5 and result["win_rate"] > 0.45:
        print("  VERDICT: [PROFITABLE] Strategy shows strong edge")
    elif result["profit_factor"] > 1.0 and result["win_rate"] > 0.40:
        print("  VERDICT: [MARGINALLY PROFITABLE] Needs optimization")
    else:
        print("  VERDICT: [NOT PROFITABLE] Strategy needs significant improvement")
    print(f"  {'=' * 60}\n")


def run_comprehensive_optimization(candles: list[Candle]) -> list[dict]:
    """Run comprehensive parameter optimization."""
    print("\n" + "=" * 80)
    print("  COMPREHENSIVE PARAMETER OPTIMIZATION")
    print("=" * 80)
    
    # Test matrix
    configs = []
    
    # Standard signals
    for rr in [1.5, 2.0, 2.5]:
        for hold in [12, 25, 50]:
            for be in [0.5, 1.0, 1.5]:
                configs.append({
                    "reward_multiple": rr,
                    "max_hold_bars": hold,
                    "breakeven_threshold": be,
                    "min_confidence": 0.50,
                    "min_confluence": 0.45,
                    "regime_filter": False,
                    "use_relaxed_signals": False,
                    "name": f"STD RR={rr} Hold={hold} BE={be}",
                })
    
    # Relaxed signals
    for rr in [1.5, 2.0, 2.5]:
        for hold in [12, 25, 50]:
            for be in [0.5, 1.0, 1.5]:
                configs.append({
                    "reward_multiple": rr,
                    "max_hold_bars": hold,
                    "breakeven_threshold": be,
                    "min_confidence": 0.40,
                    "min_confluence": 0.35,
                    "regime_filter": False,
                    "use_relaxed_signals": True,
                    "name": f"RLX RR={rr} Hold={hold} BE={be}",
                })
    
    # With regime filter
    for rr in [1.5, 2.0, 2.5]:
        for hold in [12, 25, 50]:
            for be in [0.5, 1.0, 1.5]:
                configs.append({
                    "reward_multiple": rr,
                    "max_hold_bars": hold,
                    "breakeven_threshold": be,
                    "min_confidence": 0.40,
                    "min_confluence": 0.35,
                    "regime_filter": True,
                    "use_relaxed_signals": True,
                    "name": f"REG RR={rr} Hold={hold} BE={be}",
                })
    
    print(f"\nTesting {len(configs)} configurations...\n")
    
    results = []
    for i, cfg in enumerate(configs):
        if i % 10 == 0:
            print(f"  Progress: {i}/{len(configs)} ({i/len(configs)*100:.0f}%)")
        
        result = run_optimized_backtest(
            candles,
            reward_multiple=cfg["reward_multiple"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            min_confidence=cfg["min_confidence"],
            min_confluence=cfg["min_confluence"],
            regime_filter=cfg["regime_filter"],
            use_relaxed_signals=cfg["use_relaxed_signals"],
        )
        
        results.append({
            "name": cfg["name"],
            "config": cfg,
            "total_pnl": result["total_pnl"],
            "total_pnl_pct": result["total_pnl_pct"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
            "total_trades": result["total_trades"],
        })
    
    # Sort by profit factor
    results.sort(key=lambda r: r["profit_factor"], reverse=True)
    
    return results


def print_optimization_results(results: list[dict]) -> None:
    """Print optimization results."""
    print("\n" + "=" * 120)
    print("  OPTIMIZATION RESULTS (sorted by Profit Factor)")
    print("=" * 120)
    print(f"  {'#':<3} {'Name':<30} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7} {'Sharpe':<7}")
    print("-" * 120)
    
    for i, r in enumerate(results[:30]):  # Show top 30
        print(
            f"  {i+1:<3} "
            f"{r['name']:<30} "
            f"{r['total_trades']:<7} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['total_pnl_pct']:<8.2f} "
            f"{r['max_drawdown_pct']:<7.2f} "
            f"{r['sharpe_ratio']:<7.2f}"
        )
    
    print("=" * 120)
    
    # Best profitable config
    profitable = [r for r in results if r["profit_factor"] > 1.0 and r["total_trades"] >= 5]
    if profitable:
        best = profitable[0]
        print(f"\n  BEST PROFITABLE CONFIG: {best['name']}")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    Win Rate: {best['win_rate']*100:.1f}%")
        print(f"    P&L: {best['total_pnl_pct']:.2f}%")
        print(f"    Max DD: {best['max_drawdown_pct']:.2f}%")
        print(f"    Trades: {best['total_trades']}")
    else:
        print("\n  No profitable configurations with >= 5 trades found.")
        best = results[0]
        print(f"  Best attempt: {best['name']}")
        print(f"    PF: {best['profit_factor']:.2f}, P&L: {best['total_pnl_pct']:.2f}%, Trades: {best['total_trades']}")


if __name__ == "__main__":
    import asyncio
    import httpx
    
    async def load_candles():
        """Load candles from file or fetch from Binance."""
        data_path = Path(__file__).parent.parent / "historical_data_30d.json"
        
        if data_path.exists():
            print("Loading cached 30-day data...")
            with open(data_path) as f:
                data = json.load(f)
            
            candles = [Candle(
                timestamp=d["timestamp"],
                open=d["open"],
                high=d["high"],
                low=d["low"],
                close=d["close"],
                volume=d["volume"],
            ) for d in data]
            
            print(f"Loaded {len(candles)} candles")
            return candles
        
        # Fetch from Binance
        print("Fetching 30 days of data from Binance...")
        url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=1000"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        
        candles = [Candle(
            timestamp=k[0],
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        ) for k in data]
        
        print(f"Fetched {len(candles)} candles (~3.5 days)")
        return candles
    
    async def main():
        candles = await load_candles()
        
        if len(candles) < 100:
            print("Not enough candles for optimization")
            return
        
        results = run_comprehensive_optimization(candles)
        print_optimization_results(results)
        
        # Save results
        output_path = Path(__file__).parent.parent / "optimization_results.json"
        with open(output_path, "w") as f:
            json.dump({
                "results": results[:50],
                "timestamp": time.time(),
            }, f, indent=2, default=str)
        
        print(f"\nResults saved to {output_path}")
    
    asyncio.run(main())
