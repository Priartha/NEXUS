"""Diagnose momentum vs confluence trade split."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle

with open(Path(__file__).parent.parent / "fetched_candles.json") as f:
    raw = json.load(f)
candles = [Candle(timestamp=c["t"],open=c["o"],high=c["h"],low=c["l"],close=c["c"],volume=c["v"]) for c in raw]
candles.sort(key=lambda c: c.timestamp)

engine = BacktestEngine(initial_balance=10000, position_size_pct=0.02,
    max_hold_bars=10, breakeven_threshold=1.0, trailing_stop=False,
    slippage_pct=0.0001, commission_pct=0.0002)
result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
trades = result.get("trades", [])

momentum_ct = sum(1 for t in trades if "momentum" in t.get("model","").lower())
confluence_ct = sum(1 for t in trades if "momentum" not in t.get("model","").lower())
print(f"Momentum trades: {momentum_ct}")
print(f"Confluence trades: {confluence_ct}")
print(f"Total: {len(trades)}")

mom_trades = [t for t in trades if "momentum" in t.get("model","").lower()]
if mom_trades:
    mom_wins = sum(1 for t in mom_trades if t.get("pnl",0) > 0)
    mom_pnl = sum(t.get("pnl",0) for t in mom_trades)
    print(f"Momentum WR: {mom_wins}/{len(mom_trades)} = {mom_wins/len(mom_trades)*100:.1f}%, Total PnL: ${mom_pnl:.2f}")
else:
    print("No momentum trades to analyze")

conf_trades = [t for t in trades if "momentum" not in t.get("model","").lower()]
if conf_trades:
    conf_wins = sum(1 for t in conf_trades if t.get("pnl",0) > 0)
    conf_pnl = sum(t.get("pnl",0) for t in conf_trades)
    print(f"Confluence WR: {conf_wins}/{len(conf_trades)} = {conf_wins/len(conf_trades)*100:.1f}%, Total PnL: ${conf_pnl:.2f}")

if trades:
    print(f"\nTrade types:")
    models = {}
    for t in trades:
        m = t.get("model","unknown")
        models[m] = models.get(m, 0) + 1
    for m, c in sorted(models.items(), key=lambda x: -x[1]):
        print(f"  {m}: {c}")
