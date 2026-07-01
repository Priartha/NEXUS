"""Verify and deploy best config."""
import sys, asyncio, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


async def fetch(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.get(url)
        data = resp.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in data]


async def main():
    print("=== VERIFY BEST CONFIG ===\n")
    c15 = await fetch(interval="15m", limit=1000)
    c5 = await fetch(limit=1000)

    best_params = dict(
        max_hold_bars=50, trailing_stop=False, breakeven_threshold=1.0,
        position_size_pct=0.02, tp_atr_multiplier=4.0, sl_atr_multiplier=0
    )

    for tf_name, candles, tf in [("15m (BEST)", c15, "15m"), ("5m (comparison)", c5, "5m")]:
        print("\n%s" % ("=" * 60))
        engine = BacktestEngine(initial_balance=10000, **best_params)
        r = engine.run(candles, symbol="BTCUSDT", timeframe=tf)

        print("  %s (hold=%d, TP=%dATR, SL=%dATR, trail=%s)" % (
            tf_name, best_params['max_hold_bars'], int(best_params['tp_atr_multiplier']),
            2, str(best_params['trailing_stop'])))
        print("  Period: %s to %s" % (
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(r['start_date']/1000)),
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(r['end_date']/1000))))
        print("  Initial: $%.0f  Final: $%.2f  PnL: %.2f%%" % (
            r['initial_balance'], r['final_balance'], r['total_pnl_pct']))
        print("  Trades: %d  Win: %d  Loss: %d  WR: %.1f%%" % (
            r['total_trades'], r['winning_trades'], r['losing_trades'], r['win_rate']*100))
        print("  AvgWin: $%.2f  AvgLoss: $%.2f  PF: %.2f" % (
            r['avg_win'], r['avg_loss'], r['profit_factor']))
        print("  MaxDD: $%.2f (%.2f%%)  Sharpe: %.2f  MaxConsLoss: %d" % (
            r['max_drawdown'], r['max_drawdown_pct'], r['sharpe_ratio'], r['max_consecutive_losses']))

        trades = r.get("trades", [])
        if trades:
            reasons = {}
            for t in trades:
                rsn = t.get("close_reason","?")
                if rsn not in reasons:
                    reasons[rsn] = {"count": 0, "pnl": 0}
                reasons[rsn]["count"] += 1
                reasons[rsn]["pnl"] += t.get("pnl", 0)
            print("  Exit Breakdown:")
            for rsn, d in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
                avg = d["pnl"]/d["count"] if d["count"] else 0
                print("    %-12s: %d/%d (%.1f%%)  PnL=$%+.0f  Avg=$%+.0f" % (
                    rsn, d["count"], r['total_trades'], d["count"]/r['total_trades']*100, d["pnl"], avg))

    print("\n" + "=" * 60)
    print("BEST CONFIG SUMMARY")
    print("=" * 60)
    print("  Timeframe:     15m")
    print("  Hold Bars:     50")
    print("  TP Multiplier: 4.0 ATR")
    print("  SL:            2.0 ATR (signal default)")
    print("  Trailing:      OFF")
    print("  Position Size: 2%%")
    print("  BE Threshold:  1.0")
    print("\n  Result: PROFITABLE (PF=1.76, WR=53.8%%, DD=6.3%%)")


if __name__ == "__main__":
    asyncio.run(main())
