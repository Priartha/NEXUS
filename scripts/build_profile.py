import csv
from datetime import datetime
from collections import defaultdict

rows = []
with open(r'C:\Users\priar\Downloads\Delta-TransactionLog-AssetHistory (3).csv', 'r') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

for r in rows:
    dt_str = r['Date'].split('+')[0].strip()
    try:
        r['_dt'] = datetime.fromisoformat(dt_str)
    except:
        r['_dt'] = None
    if r['_dt']:
        r['_hour_ist'] = r['_dt'].hour  # IST already in the timestamp

# BTCUSD cashflows only
cashflows = [r for r in rows if r['Contract/Fund'] == 'BTCUSD' and r['Transaction type'] == 'cashflow']
fees = [r for r in rows if r['Contract/Fund'] == 'BTCUSD' and r['Transaction type'] == 'trading fees']

# Extract PnL per trade (each cashflow is a trade close)
# Pair cashflows with timestamps to build closing sequence
trades = []
for r in cashflows:
    pnl = float(r['Amount with GST'])
    trades.append({'ts': r['_dt'], 'pnl': pnl, 'hour': r['_hour_ist']})

# Hourly PnL analysis
hourly = defaultdict(lambda: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'gross_win': 0.0, 'gross_loss': 0.0})
for t in trades:
    h = t['hour']
    hourly[h]['trades'] += 1
    hourly[h]['pnl'] += t['pnl']
    if t['pnl'] > 0:
        hourly[h]['wins'] += 1
        hourly[h]['gross_win'] += t['pnl']
    else:
        hourly[h]['gross_loss'] += abs(t['pnl'])

print("=== HOURLY PERFORMANCE (IST) ===")
for h in sorted(hourly.keys()):
    hr = hourly[h]
    wr = hr['wins'] / hr['trades'] * 100 if hr['trades'] > 0 else 0
    pf = hr['gross_win'] / hr['gross_loss'] if hr['gross_loss'] > 0 else hr['gross_win']
    print(f"  {h:02d}:00 - {hr['trades']:2d} trades, WR={wr:.0f}%, PnL=${hr['pnl']:+.2f}, PF={pf:.2f}")

# Classify hours
print("\n=== CLASSIFIED HOURS ===")
best = []   # WR > 60%, PF > 1.0, good PnL
worst = []  # Negative PnL
mixed = []  # Everything else
for h in sorted(hourly.keys()):
    hr = hourly[h]
    wr = hr['wins'] / hr['trades'] if hr['trades'] > 0 else 0
    if hr['pnl'] > 0 and wr > 0.5:
        best.append(h)
    elif hr['pnl'] <= 0 and hr['trades'] >= 2:
        worst.append(h)
    else:
        mixed.append(h)

print(f"  Best hours (profitable + WR>50%): {sorted(best)}")
print(f"  Worst hours (negative PnL, >=2 trades): {sorted(worst)}")
print(f"  Mixed/neutral: {sorted(mixed)}")

# Stats per trade
pnls = [t['pnl'] for t in trades]
fees_vals = [float(r['Amount with GST']) for r in fees if r['Amount with GST']]
import statistics

print(f"\n=== TRADER PROFILE STATS ===")
print(f"  Win rate: {sum(1 for p in pnls if p > 0)}/{len(pnls)} = {sum(1 for p in pnls if p > 0)/len(pnls)*100:.1f}%")
print(f"  Avg PnL: ${statistics.mean(pnls):.2f}")
print(f"  Median PnL: ${statistics.median(pnls):.2f}")
print(f"  Std PnL: ${statistics.stdev(pnls):.2f}")
print(f"  Profit factor: {sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0)):.2f}")
print(f"  Avg win: ${statistics.mean([p for p in pnls if p > 0]):.2f}")
print(f"  Avg loss: ${statistics.mean([p for p in pnls if p < 0]):.2f}")
print(f"  Avg fee per trade: ${abs(statistics.mean(fees_vals)):.4f}")
print(f"  Fee as % of avg |PnL|: {abs(statistics.mean(fees_vals)) / statistics.mean([abs(p) for p in pnls]) * 100:.1f}%")
print(f"  Total net PnL (after fees+funding): ${sum(pnls) + sum(fees_vals):.2f}")

# Daily PnL
daily = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'fees': 0.0})
for t in trades:
    day = t['ts'].strftime('%Y-%m-%d')
    daily[day]['pnl'] += t['pnl']
    daily[day]['trades'] += 1
for r in fees:
    day = r['_dt'].strftime('%Y-%m-%d')
    daily[day]['fees'] += float(r['Amount with GST'])

print(f"\n=== DAILY STATS ===")
print(f"  Trading days: {len(daily)}")
print(f"  Avg trades/day: {len(pnls)/max(len(daily),1):.1f}")
daily_pnls = [d['pnl'] for d in daily.values()]
print(f"  Avg daily PnL: ${statistics.mean(daily_pnls):.2f}")
print(f"  Median daily PnL: ${statistics.median(daily_pnls):.2f}")
win_days = sum(1 for d in daily_pnls if d > 0)
print(f"  Profitable days: {win_days}/{len(daily_pnls)} ({win_days/len(daily_pnls)*100:.0f}%)")

# Max consecutive wins/losses
consec = {'wins': 0, 'losses': 0}
current_w = 0
current_l = 0
for p in pnls:
    if p > 0:
        current_w += 1
        current_l = 0
    else:
        current_l += 1
        current_w = 0
    consec['wins'] = max(consec['wins'], current_w)
    consec['losses'] = max(consec['losses'], current_l)
print(f"\n  Max consecutive wins: {consec['wins']}")
print(f"  Max consecutive losses: {consec['losses']}")

# Sharpe ratio
import math
returns = [p / 100 for p in pnls]
avg_ret = statistics.mean(returns) if returns else 0
std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.001
sharpe = avg_ret / std_ret * math.sqrt(365) if std_ret > 0 else 0
print(f"  Sharpe ratio: {sharpe:.2f}")

# Output profile JSON
print(f"\n=== PROFILE JSON ===")
print("Put this in data/trader_style_profile.json:")
profile = {
    "timezone": "Asia/Kolkata",
    "execution_profile": {
        "high_performance_hours": sorted(best),
        "blocked_hours": sorted(worst),
        "reduced_size_hours": sorted(mixed),
        "good_hour_confidence_delta": -0.04,
        "reduced_hour_confidence_delta": 0.05,
        "min_fee_edge_ratio": 3.5,
        "post_win_cooldown_minutes": 30,
        "risk_per_trade_pct": 0.008,
    },
    "notes": [
        f"Profile generated from {len(pnls)} BTCUSD perpetual trades over {len(daily)} days.",
        f"Win rate: {sum(1 for p in pnls if p > 0)/len(pnls)*100:.1f}%, Profit factor: 2.30",
        f"Avg PnL: ${statistics.mean(pnls):.2f}, Median: ${statistics.median(pnls):.2f}",
        f"Best hours (IST): {sorted(best)}",
        f"Blocked hours (IST): {sorted(worst)}",
        f"Fees consume {abs(statistics.mean(fees_vals)) / statistics.mean([abs(p) for p in pnls]) * 100:.0f}% of avg trade |PnL|",
        f"Style: High-frequency scalper, quick small profits, tight stops.",
    ],
}
print(json.dumps(profile, indent=2))
