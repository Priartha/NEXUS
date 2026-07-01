"""Diagnose exit breakdown for best configs."""
import sys, asyncio, time
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


def analyze(r):
    trades = r.get("trades", [])
    if not trades:
        return {}
    reasons = {}
    for t in trades:
        rsn = t.get("close_reason","?")
        pnl = t.get("pnl", 0)
        if rsn not in reasons:
            reasons[rsn] = {"count": 0, "pnl": 0, "wins": 0, "losses": 0}
        reasons[rsn]["count"] += 1
        reasons[rsn]["pnl"] += pnl
        if pnl > 0:
            reasons[rsn]["wins"] += 1
        else:
            reasons[rsn]["losses"] += 1
    return reasons


async def main():
    print("Fetching both timeframes...")
    c5 = await fetch(limit=1000)
    c15 = await fetch(interval="15m", limit=1000)

    configs = [
        ("5m_h40_nt", c5, "5m", 40, False),
        ("15m_h40_nt", c15, "15m", 40, False),
        ("15m_h20_nt", c15, "15m", 20, False),
    ]

    for name, candles, tf, hold, trail in configs:
        print("\n%s" % ("=" * 60))
        print("  %s (TF=%s, Hold=%d, Trail=%s)" % (name, tf, hold, str(trail)))
        print("=" * 60)

        engine = BacktestEngine(initial_balance=10000, position_size_pct=0.02,
                                max_hold_bars=hold, trailing_stop=trail,
                                breakeven_threshold=1.0)
        r = engine.run(candles, symbol="BTCUSDT", timeframe=tf)

        print("  Trades: %d  WR: %.1f%%  PF: %.2f  PnL: %.2f%%  DD: %.2f%%" % (
            r['total_trades'], r['win_rate']*100, r['profit_factor'],
            r['total_pnl_pct'], r['max_drawdown_pct']))

        reasons = analyze(r)
        print("\n  Exit Breakdown:")
        for rsn, data in sorted(reasons.items(), key=lambda x: -x[1]["count"]):
            avg = data["pnl"] / data["count"] if data["count"] > 0 else 0
            pct = data["count"] / r['total_trades'] * 100
            print("    %-12s: %3d (%5.1f%%)  PnL=$%+.0f  Avg=$%+.0f  %dW/%dL" % (
                rsn, data["count"], pct, data["pnl"], avg,
                data["wins"], data["losses"]))

        # Show trade list
        trades = r.get("trades", [])
        if trades:
            print("\n  Trade List (first 15):")
            print("    %-22s %-5s %8s %8s %8s %8s" % ("Reason","Side","Entry","Exit","PnL","Bars"))
            trades_sorted = sorted(trades, key=lambda t: t.get("bars_held", 0))
            for t in trades_sorted[:15]:
                print("    %-22s %-5s %8.0f %8.0f %+8.2f %4d" % (
                    t.get("close_reason","?"), t.get("side","?"),
                    t.get("entry_price",0), t.get("exit_price",0),
                    t.get("pnl",0), t.get("bars_held",0)))


if __name__ == "__main__":
    asyncio.run(main())
