"""
Fast Focused Optimizer - Tests key parameter combinations efficiently.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import math
import uuid
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_structure import detect_structure
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime import detect_market_regime
from backend.analysis.swing_detector import detect_swings


async def fetch_candles(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in data]


# ── Helpers ──
def _sma(data, period):
    return [sum(data[i-period+1:i+1])/period if i >= period-1 else 0.0 for i in range(len(data))]

def _atr(candles, period=14):
    if len(candles) < 2: return 0.0
    ranges = [max(c.high-c.low, abs(c.high-p.close), abs(c.low-p.close)) for p, c in zip(candles[-(period+1):], candles[-(period+1):][1:])]
    return sum(ranges)/len(ranges) if ranges else 0.0

def _rsi(closes, period=14):
    if len(closes) < period+1: return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag, al = sum(gains[:period])/period, sum(losses[:period])/period
    for i in range(period, len(closes)-1):
        ag = (ag*(period-1)+gains[i])/period; al = (al*(period-1)+losses[i])/period
    rs = ag/al if al > 0 else 100.0
    return 100.0 - 100.0/(1.0+rs)

def _is_killzone(ts):
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
    tv = dt.hour + dt.minute/60.0
    if 2.0 <= tv < 5.0: return True, "london"
    if 8.5 <= tv < 11.0: return True, "ny_am"
    if 13.5 <= tv < 16.0: return True, "ny_pm"
    return False, "off_hours"

def _nearest_fvg(fvgs, price, direction):
    active = [f for f in fvgs if not f.is_filled]
    if not active: return None
    if direction == "buy":
        below = [f for f in active if f.bottom < price]
        return max(below, key=lambda f: f.bottom) if below else None
    else:
        above = [f for f in active if f.top > price]
        return min(above, key=lambda f: f.top) if above else None

def _nearest_ob(obs, price, direction):
    active = [o for o in obs if not o.is_breaker]
    if not active: return None
    if direction == "buy":
        below = [o for o in active if o.bottom < price and o.direction == "bullish"]
        return max(below, key=lambda o: o.bottom) if below else None
    else:
        above = [o for o in active if o.top > price and o.direction == "bearish"]
        return min(above, key=lambda o: o.top) if above else None

def _has_sweep(events, direction, lookback_ms=3600000):
    from datetime import datetime, timezone
    now = int(datetime.now(timezone.utc).timestamp()*1000)
    recent = [e for e in events if (now-e.timestamp) < lookback_ms]
    if direction == "buy": return any(e.side=="sell_side" and e.reclaimed for e in recent)
    return any(e.side=="buy_side" and e.reclaimed for e in recent)

def _check_structure(swings, candles, direction):
    if len(swings) < 4: return False, "insufficient"
    recent = swings[-8:]
    if direction == "buy":
        hh = max((s.price for s in recent if s.kind=="high"), default=0)
        if candles[-1].close > hh and hh > 0: return True, "BOS"
        lows = [s.price for s in recent if s.kind=="low"]
        if len(lows)>=2 and lows[-1]>lows[-2]: return True, "HL"
    else:
        ll = min((s.price for s in recent if s.kind=="low"), default=float("inf"))
        if candles[-1].close < ll and ll < float("inf"): return True, "BOS"
        highs = [s.price for s in recent if s.kind=="high"]
        if len(highs)>=2 and highs[-1]<highs[-2]: return True, "LH"
    return False, "none"

def _vol_confirm(candles, direction):
    if len(candles)<20: return 1.0
    avg_v = sum(c.volume for c in candles[-20:-1])/19
    if avg_v==0: return 1.0
    vr = candles[-1].volume/avg_v
    if direction=="buy" and candles[-1].close>candles[-2].close: return min(vr/1.5, 2.0)
    if direction=="sell" and candles[-1].close<candles[-2].close: return min(vr/1.5, 2.0)
    return 0.5


# ── Signal Generation ──
def gen_signals(candles, metrics, fvgs, obs, liq_events, swings, cfg, regime=None):
    if len(candles)<100: return []
    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    latest = ordered[-1]
    atr14 = _atr(ordered, 14)
    rsi_i = _rsi(closes, 14)
    sma20 = _sma(closes, 20); sma50 = _sma(closes, 50)
    i = len(ordered)-1
    s20, s50 = sma20[i], sma50[i]
    trend = (s20-s50)/s50*100 if s50>0 else 0
    in_kz, session = _is_killzone(latest.timestamp)
    signals = []

    for direction in ["buy", "sell"]:
        is_up = direction=="buy" and trend > cfg["min_trend"]
        is_down = direction=="sell" and trend < -cfg["min_trend"]

        # Regime-aware
        if cfg["use_regime"] and regime:
            if regime.phase in ("consolidation", "range_bound"):
                is_up = direction=="buy" and latest.close < regime.range_mid
                is_down = direction=="sell" and latest.close > regime.range_mid

        if not (is_up or is_down): continue

        score = 0.0; reasons = []
        pb = (latest.close-s20)/s20*100
        pb_lo, pb_hi = cfg["pb_buy"] if is_up else cfg["pb_sell"]
        rsi_lo, rsi_hi = cfg["rsi_buy"] if is_up else cfg["rsi_sell"]
        if not (pb_lo < pb < pb_hi): continue
        if not (rsi_lo < rsi_i < rsi_hi): continue

        score += 0.20; reasons.append(f"Trend {trend:+.1f}%")
        fvg = _nearest_fvg(fvgs, latest.close, direction)
        if fvg: score += 0.15; reasons.append("FVG")
        ob = _nearest_ob(obs, latest.close, direction)
        if ob: score += 0.15; reasons.append("OB")
        sweep = _has_sweep(liq_events, direction)
        if sweep: score += 0.15; reasons.append("Sweep")
        struct_ok, struct_type = _check_structure(swings, ordered, direction)
        if struct_ok: score += 0.10; reasons.append(f"Struct:{struct_type}")
        vc = _vol_confirm(ordered, direction)
        if vc >= 1.0: score += 0.10*vc; reasons.append(f"Vol {vc:.1f}x")
        if in_kz: score += 0.10; reasons.append(f"KZ:{session}")

        if cfg["need_fvg_ob"] and not (fvg or ob): continue
        if cfg["need_struct"] and not struct_ok: continue
        if score < cfg["min_confluence"]: continue

        entry = latest.close
        if is_up:
            stop = s50
            if ob: stop = min(stop, ob.bottom-atr14*cfg["atr_buf"])
            if fvg: stop = min(stop, fvg.bottom-atr14*cfg["atr_buf"])
            if stop >= entry: stop = entry-atr14*cfg["atr_mult"]
        else:
            stop = s50
            if ob: stop = max(stop, ob.top+atr14*cfg["atr_buf"])
            if fvg: stop = max(stop, fvg.top+atr14*cfg["atr_buf"])
            if stop <= entry: stop = entry+atr14*cfg["atr_mult"]

        risk = abs(entry-stop)
        if risk < atr14*0.5: continue
        target = entry + risk*cfg["rr"]*(1 if is_up else -1)
        conf = max(0.40, min(0.92, 0.40+score*0.55))
        if conf < cfg["min_conf"]: continue

        from backend.analysis.ids import stable_id
        rr = abs(target-entry)/risk if risk>0 else 0
        sig = type('S', (), {'id': stable_id("s", direction, latest.timestamp, int(entry*10)),
            'timestamp': latest.timestamp, 'side': direction, 'entry': round(entry,2),
            'stop_loss': round(stop,2), 'exit_price': round(target,2),
            'risk_reward': round(rr,2), 'confidence': round(conf,3),
            'reason': "; ".join(reasons)})()
        signals.append(sig)

    if not signals: return []
    return [max(signals, key=lambda s: s.confidence)]


# ── Backtest Engine ──
def run_bt(candles, sig_cfg, bt_cfg, symbol="BTC", tf="5m"):
    candles = sorted(candles, key=lambda c: c.timestamp)
    results, equity = [], []
    balance = bt_cfg["balance"]; peak = balance; open_trades = []
    swings, fvgs, obs, liq, liq_events, metrics, regime = [], [], [], [], [], None, None
    lookback, min_c, last_ts = 80, 80, 0

    for i in range(min_c, len(candles)):
        window = candles[:i+1]; recent = window[-lookback:]; current = candles[i]
        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        obs = detect_order_blocks(recent, swings)
        liq = detect_equal_levels(swings)
        for c in recent:
            fvgs = update_fvg_fills(fvgs, c); obs = update_order_block_breakers(obs, c)
            liq = check_liquidity_sweeps(liq, c)
        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0.0
        liq_events = detect_liquidity_events(recent, liq, atr)[-80:]
        regime = detect_market_regime(window, metrics, liq_events)

        signals = gen_signals(window, metrics, fvgs, obs, liq_events, swings, sig_cfg, regime)
        new_sigs = [s for s in signals if s.timestamp > last_ts]
        last_ts = max((s.timestamp for s in signals), default=last_ts)

        for sig in new_sigs:
            if len([t for t in open_trades if t["status"]=="open"]) >= bt_cfg["max_conc"]: continue
            risk_amt = balance*bt_cfg["risk_pct"]
            rpu = abs(sig.entry-sig.stop_loss)
            qty = risk_amt/rpu if rpu>0 else 0
            slip = sig.entry*bt_cfg["slip"]
            e_price = sig.entry+slip if sig.side=="buy" else sig.entry-slip
            comm = e_price*qty*bt_cfg["comm"]
            open_trades.append({"id": str(uuid.uuid4()), "timestamp": sig.timestamp, "side": sig.side,
                "entry_price": round(e_price,2), "stop_loss": sig.stop_loss, "initial_sl": sig.stop_loss,
                "take_profit": sig.exit_price, "quantity": qty, "status": "open",
                "confidence": sig.confidence, "commission": round(comm,2), "bars_held": 0,
                "partial_done": False})

        for trade in list(open_trades):
            if trade["status"]!="open": continue
            side, entry, sl, tp, qty = trade["side"], trade["entry_price"], trade["stop_loss"], trade["take_profit"], trade["quantity"]
            bh = trade.get("bars_held",0)+1; trade["bars_held"] = bh
            risk = abs(entry-trade["initial_sl"])

            # Trailing
            if bt_cfg["trailing"] and risk>0:
                if side=="buy":
                    trail = current.high-atr*bt_cfg["trail_atr"]
                    trade["stop_loss"] = max(trade["stop_loss"], trail); sl = trade["stop_loss"]
                    if (current.high-entry)/risk >= bt_cfg["be_thresh"]:
                        trade["stop_loss"] = max(trade["stop_loss"], entry); sl = trade["stop_loss"]
                else:
                    trail = current.low+atr*bt_cfg["trail_atr"]
                    trade["stop_loss"] = min(trade["stop_loss"], trail); sl = trade["stop_loss"]
                    if (entry-current.low)/risk >= bt_cfg["be_thresh"]:
                        trade["stop_loss"] = min(trade["stop_loss"], entry); sl = trade["stop_loss"]

            # Partial exit
            if bt_cfg["partial_pct"]>0 and not trade["partial_done"]:
                p_rr = bt_cfg["partial_rr"]
                p_tp = entry+risk*p_rr if side=="buy" else entry-risk*p_rr
                hit = (current.high>=p_tp) if side=="buy" else (current.low<=p_tp)
                if hit:
                    p_qty = qty*bt_cfg["partial_pct"]
                    p_pnl = (p_tp-entry)*p_qty if side=="buy" else (entry-p_tp)*p_qty
                    balance += p_pnl; qty *= (1-bt_cfg["partial_pct"])
                    trade["quantity"] = qty; trade["partial_done"] = True

            # Time exit
            if bh >= bt_cfg["max_hold"]:
                ep = current.close
                pnl = (ep-entry)*qty if side=="buy" else (entry-ep)*qty
                pnl -= trade["commission"]
                trade.update({"status":"closed","exit_price":ep,"exit_timestamp":current.timestamp,
                    "pnl":round(pnl,2),"pnl_pct":round(pnl/(entry*qty)*100 if entry*qty>0 else 0,4),
                    "close_reason":"time_exit"}); balance += pnl; results.append(dict(trade)); continue

            # SL/TP check
            if side=="buy":
                hs, ht = current.low<=sl, current.high>=tp
            else:
                hs, ht = current.high>=sl, current.low<=tp

            if hs:
                pnl = (sl-entry)*qty if side=="buy" else (entry-sl)*qty
                pnl -= trade["commission"]
                trade.update({"status":"closed","exit_price":sl,"exit_timestamp":current.timestamp,
                    "pnl":round(pnl,2),"pnl_pct":round(pnl/(entry*qty)*100 if entry*qty>0 else 0,4),
                    "close_reason":"stop_loss"}); balance += pnl; results.append(dict(trade))
            elif ht:
                pnl = (tp-entry)*qty if side=="buy" else (entry-tp)*qty
                pnl -= trade["commission"]
                trade.update({"status":"closed","exit_price":tp,"exit_timestamp":current.timestamp,
                    "pnl":round(pnl,2),"pnl_pct":round(pnl/(entry*qty)*100 if entry*qty>0 else 0,4),
                    "close_reason":"target_hit"}); balance += pnl; results.append(dict(trade))

        if balance > peak: peak = balance
        dd = peak-balance; dd_pct = dd/peak*100 if peak>0 else 0
        if i%5==0 or i==len(candles)-1:
            equity.append({"timestamp":current.timestamp,"balance":round(balance,2),"dd_pct":round(dd_pct,4)})

    closed = [r for r in results if r.get("exit_price")]
    wins = [r for r in closed if r.get("pnl",0)>0]; losses = [r for r in closed if r.get("pnl",0)<=0]
    max_dd = max((e["dd_pct"] for e in equity), default=0)
    avg_w = sum(r["pnl"] for r in wins)/len(wins) if wins else 0
    avg_l = abs(sum(r["pnl"] for r in losses)/len(losses)) if losses else 0
    gp = sum(r["pnl"] for r in wins); gl = abs(sum(r["pnl"] for r in losses))
    pf = gp/gl if gl>0 else (999.99 if wins else 0.0)
    rets = [e["balance"]/bt_cfg["balance"]-1 for e in equity]
    avg_r = sum(rets)/len(rets) if rets else 0
    std_r = (sum((r-avg_r)**2 for r in rets)/len(rets))**0.5 if len(rets)>1 else 0
    sharpe = (avg_r/std_r*math.sqrt(365)) if std_r>0 else 0

    # Consecutive losses
    max_cl, cl = 0, 0
    for r in closed:
        if r.get("pnl",0)<=0: cl+=1; max_cl=max(max_cl,cl)
        else: cl=0

    return {"total_trades":len(closed),"win_rate":len(wins)/len(closed) if closed else 0,
        "profit_factor":round(pf,4),"max_drawdown_pct":round(max_dd,4),
        "sharpe_ratio":round(sharpe,4),"total_pnl_pct":round((balance-bt_cfg["balance"])/bt_cfg["balance"]*100,4),
        "avg_win":round(avg_w,2),"avg_loss":round(avg_l,2),"final_balance":round(balance,2),
        "max_consecutive_losses":max_cl,"trades":results}


def score(r):
    t = r["total_trades"]
    if t < 10: return -1000
    return r["win_rate"]*50 + min(r["profit_factor"],5.0)*10 - max(0,(r["max_drawdown_pct"]-5.0))*3 + max(r["sharpe_ratio"],-5.0)*3 + min(r["total_pnl_pct"],50.0)*0.5 + min(t/100.0,1.0)*10


# ── Parameter Grids (focused, not exhaustive) ──
SIG_PRESETS = [
    {"name":"relaxed", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":2.5, "need_fvg_ob":True, "need_struct":False, "use_regime":True, "atr_mult":1.5, "atr_buf":0.3},
    {"name":"very_relaxed", "min_trend":0.10, "pb_buy":(-5.0,1.5), "pb_sell":(-1.5,5.0), "rsi_buy":(15,70), "rsi_sell":(30,85), "min_confluence":0.25, "min_conf":0.35, "rr":2.0, "need_fvg_ob":False, "need_struct":False, "use_regime":True, "atr_mult":2.0, "atr_buf":0.2},
    {"name":"moderate", "min_trend":0.20, "pb_buy":(-3.0,0.5), "pb_sell":(-0.5,3.0), "rsi_buy":(25,60), "rsi_sell":(40,75), "min_confluence":0.35, "min_conf":0.45, "rr":3.0, "need_fvg_ob":True, "need_struct":True, "use_regime":True, "atr_mult":1.5, "atr_buf":0.3},
    {"name":"no_regime", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":2.5, "need_fvg_ob":True, "need_struct":False, "use_regime":False, "atr_mult":1.5, "atr_buf":0.3},
    {"name":"tight_rr", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":2.0, "need_fvg_ob":True, "need_struct":False, "use_regime":True, "atr_mult":1.0, "atr_buf":0.3},
    {"name":"high_rr", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":3.5, "need_fvg_ob":True, "need_struct":False, "use_regime":True, "atr_mult":1.5, "atr_buf":0.3},
    {"name":"no_fvg_ob_req", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":2.5, "need_fvg_ob":False, "need_struct":False, "use_regime":True, "atr_mult":1.5, "atr_buf":0.3},
    {"name":"structure_only", "min_trend":0.15, "pb_buy":(-4.0,1.0), "pb_sell":(-1.0,4.0), "rsi_buy":(20,65), "rsi_sell":(35,80), "min_confluence":0.30, "min_conf":0.40, "rr":2.5, "need_fvg_ob":False, "need_struct":True, "use_regime":True, "atr_mult":1.5, "atr_buf":0.3},
]

BT_PRESETS = [
    {"name":"default", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":True, "trail_atr":1.0, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"tight_trail", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":0.8, "trailing":True, "trail_atr":0.8, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"loose_trail", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":35, "be_thresh":1.5, "trailing":True, "trail_atr":1.5, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"no_trail", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":False, "trail_atr":1.0, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"partial_50", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":True, "trail_atr":1.0, "partial_pct":0.5, "partial_rr":1.5},
    {"name":"partial_30", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":True, "trail_atr":1.0, "partial_pct":0.3, "partial_rr":2.0},
    {"name":"short_hold", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":12, "be_thresh":0.5, "trailing":True, "trail_atr":0.8, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"long_hold", "balance":10000, "risk_pct":0.02, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":50, "be_thresh":1.0, "trailing":True, "trail_atr":1.5, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"low_risk", "balance":10000, "risk_pct":0.01, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":True, "trail_atr":1.0, "partial_pct":0.0, "partial_rr":1.5},
    {"name":"high_risk", "balance":10000, "risk_pct":0.025, "max_conc":1, "slip":0.0002, "comm":0.0004, "max_hold":25, "be_thresh":1.0, "trailing":True, "trail_atr":1.0, "partial_pct":0.0, "partial_rr":1.5},
]


async def main():
    print("="*80)
    print("  NEXUS FAST FOCUSED OPTIMIZER")
    print("="*80)

    # Fetch data
    print("\nFetching data...")
    async with httpx.AsyncClient(timeout=30) as client:
        data = {}
        for tf in ["5m", "15m", "1h"]:
            try:
                url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={tf}&limit=1000"
                resp = await client.get(url); resp.raise_for_status()
                klines = resp.json()
                data[tf] = [Candle(timestamp=k[0],open=float(k[1]),high=float(k[2]),low=float(k[3]),close=float(k[4]),volume=float(k[5])) for k in klines]
                print(f"  {tf}: {len(data[tf])} candles")
            except Exception as e:
                print(f"  {tf}: FAILED - {e}")

    all_results = []
    total = len(SIG_PRESETS) * len(BT_PRESETS) * len(data)
    idx = 0

    print(f"\nTesting {len(SIG_PRESETS)} signal × {len(BT_PRESETS)} engine × {len(data)} timeframes = {total} combos\n")

    for tf, candles in data.items():
        if len(candles) < 100: continue
        print(f"\n{'='*60}")
        print(f"  {tf} TIMEFRAME ({len(candles)} candles)")
        print(f"{'='*60}")

        for sp in SIG_PRESETS:
            for bp in BT_PRESETS:
                idx += 1
                try:
                    result = run_bt(candles, sp, bp, symbol="BTCUSDT", tf=tf)
                    s = score(result)
                    all_results.append({"score":s, "timeframe":tf, "signal":sp["name"], "backtest":bp["name"],
                        "signal_cfg":sp, "bt_cfg":bp, "results":result})
                except Exception as e:
                    pass

                if idx % 20 == 0:
                    print(f"  Progress: {idx}/{total} | Tested so far: {len(all_results)}")

    # Sort and display
    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*80}")
    print(f"  TOP 15 CONFIGURATIONS (sorted by composite score)")
    print(f"{'='*80}")
    print(f"  {'#':<3} {'TF':<5} {'Signal':<16} {'Engine':<14} {'Score':<7} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8}")
    print(f"  {'-'*85}")

    for rank, r in enumerate(all_results[:15], 1):
        res = r["results"]
        print(f"  {rank:<3} {r['timeframe']:<5} {r['signal']:<16} {r['backtest']:<14} {r['score']:<7.1f} {res['total_trades']:<7} {res['win_rate']*100:<6.1f} {res['profit_factor']:<6.2f} {res['max_drawdown_pct']:<6.2f} {res['sharpe_ratio']:<7.2f} {res['total_pnl_pct']:<8.2f}")

    if all_results:
        best = all_results[0]
        res = best["results"]
        print(f"\n{'='*80}")
        print(f"  WINNER: {best['signal']} + {best['backtest']} on {best['timeframe']}")
        print(f"  Score: {best['score']:.1f} | Trades: {res['total_trades']} | WR: {res['win_rate']*100:.1f}% | PF: {res['profit_factor']:.2f} | DD: {res['max_drawdown_pct']:.2f}% | Sharpe: {res['sharpe_ratio']:.2f} | PnL: {res['total_pnl_pct']:.2f}%")
        print(f"{'='*80}")

        # Save
        output = {"best": {"signal": best["signal"], "backtest": best["backtest"], "timeframe": best["timeframe"],
            "signal_cfg": best["signal_cfg"], "bt_cfg": best["bt_cfg"], "results": res, "score": best["score"]},
            "top_15": [{"rank":i+1, "timeframe":r["timeframe"], "signal":r["signal"], "backtest":r["backtest"],
                "score":r["score"], "results":r["results"]} for i,r in enumerate(all_results[:15])],
            "total_tested": len(all_results), "timestamp": time.time()}
        with open(Path(__file__).parent.parent/"optimization_results.json", "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nSaved to optimization_results.json")


if __name__ == "__main__":
    asyncio.run(main())
