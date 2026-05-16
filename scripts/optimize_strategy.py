from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch_binance_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 1000,
) -> list[Candle]:
    """Fetch historical candles from Binance."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    candles = []
    for k in data:
        candles.append(Candle(
            timestamp=k[0],
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        ))
    return candles


def run_backtest_with_rr(
    candles: list[Candle],
    reward_multiple: float = 3.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    initial_balance: float = 10_000.0,
    position_size_pct: float = 0.02,
    max_concurrent: int = 1,
    slippage_pct: float = 0.0002,
    commission_pct: float = 0.0004,
    max_hold_bars: int = 25,
    breakeven_threshold: float = 1.0,
    min_confidence: float = 0.50,
) -> dict:
    """Run backtest with custom reward multiple and confidence threshold."""
    from backend.analysis.signals import detect_trade_signals
    from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
    from backend.analysis.institutional import compute_market_metrics
    from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
    from backend.analysis.liquidity_engineering import detect_liquidity_events
    from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
    from backend.analysis.regime import detect_market_regime
    from backend.analysis.swing_detector import detect_swings
    from backend.analysis.market_structure import detect_structure
    import uuid
    import math

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
            peak_ts = current.timestamp
        dd = peak - balance
        dd_pct = dd / peak * 100 if peak > 0 else 0

        if i % 5 == 0 or i == len(candles) - 1:
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
        "max_hold_bars": max_hold_bars,
        "breakeven_threshold": breakeven_threshold,
    }


def print_results(result: dict) -> None:
    """Print backtest results in a readable format."""
    print("\n" + "=" * 60)
    print("  NEXUS BACKTEST RESULTS")
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


async def optimize_strategy(candles: list[Candle]) -> list[dict]:
    """Optimize strategy parameters."""
    print("\nRunning strategy optimization...")
    
    configs = []
    for rr in [1.5, 2.0, 3.0]:
        for conf in [0.45, 0.55]:
            for hold in [12, 25]:
                for be in [0.5, 1.0]:
                    configs.append({
                        "reward_multiple": rr,
                        "min_confidence": conf,
                        "max_hold_bars": hold,
                        "breakeven_threshold": be,
                    })

    results = []
    for i, cfg in enumerate(configs):
        if i % 10 == 0:
            print(f"  Config {i+1}/{len(configs)}: RR={cfg['reward_multiple']}, Conf={cfg['min_confidence']}, Hold={cfg['max_hold_bars']}, BE={cfg['breakeven_threshold']}")
        result = run_backtest_with_rr(
            candles,
            reward_multiple=cfg["reward_multiple"],
            min_confidence=cfg["min_confidence"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
        )
        results.append({
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
    
    print("\n" + "=" * 100)
    print("  OPTIMIZATION RESULTS (sorted by Profit Factor)")
    print("=" * 100)
    print(f"  {'#':<3} {'RR':<5} {'Conf':<6} {'Hold':<6} {'BE':<5} {'P&L%':<8} {'Win%':<7} {'PF':<7} {'DD%':<7} {'Sharpe':<7} {'Trades':<7}")
    print("-" * 100)
    
    for i, r in enumerate(results[:20]):  # Show top 20
        cfg = r["config"]
        print(
            f"  {i+1:<3} "
            f"{cfg['reward_multiple']:<5.1f} "
            f"{cfg['min_confidence']:<6.2f} "
            f"{cfg['max_hold_bars']:<6} "
            f"{cfg['breakeven_threshold']:<5.1f} "
            f"{r['total_pnl_pct']:<8.2f} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['max_drawdown_pct']:<7.2f} "
            f"{r['sharpe_ratio']:<7.2f} "
            f"{r['total_trades']:<7}"
        )
    
    print("=" * 100)
    
    # Best config
    best = results[0]
    print(f"\n  BEST CONFIG: RR={best['config']['reward_multiple']}, "
          f"Conf={best['config']['min_confidence']}, "
          f"Hold={best['config']['max_hold_bars']}, "
          f"BE={best['config']['breakeven_threshold']}")
    print(f"  P&L: {best['total_pnl_pct']:.2f}%, PF: {best['profit_factor']:.2f}, "
          f"Win Rate: {best['win_rate']*100:.1f}%, Sharpe: {best['sharpe_ratio']:.2f}")
    
    return results[:20]


async def main():
    print("Fetching historical data from Binance...")
    
    # Fetch 5m candles (1000 candles = ~3.5 days)
    candles_5m = await fetch_binance_candles(symbol="BTCUSDT", interval="5m", limit=1000)
    print(f"Fetched {len(candles_5m)} 5m candles")
    
    if len(candles_5m) < 100:
        print("Not enough candles for backtest")
        return
    
    # Run optimization
    top_configs = await optimize_strategy(candles_5m)
    
    # Run best config
    if top_configs:
        best = top_configs[0]
        cfg = best["config"]
        print(f"\n\nRunning BEST config backtest...")
        result = run_backtest_with_rr(
            candles_5m,
            reward_multiple=cfg["reward_multiple"],
            min_confidence=cfg["min_confidence"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
        )
        print_results(result)
    
    # Save results
    output = {
        "optimization_results": top_configs,
        "timestamp": time.time(),
    }
    
    output_path = Path(__file__).parent.parent / "optimization_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
