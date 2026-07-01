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

futures_btc = [r for r in rows if r['Contract/Fund'] == 'BTCUSD']

cashflows = [r for r in futures_btc if r['Transaction type'] == 'cashflow']
fees = [r for r in futures_btc if r['Transaction type'] == 'trading fees']
fundings = [r for r in futures_btc if r['Transaction type'] == 'funding']

print('=== OVERALL STATS ===')
print(f'Total rows: {len(rows)}')
print(f'BTCUSD rows: {len(futures_btc)}')
print(f'  Cashflows (trade PnL): {len(cashflows)}')
print(f'  Trading fees: {len(fees)}')
print(f'  Funding payments: {len(fundings)}')

pnls = [float(r['Amount with GST']) for r in cashflows if r['Amount with GST']]
wins = sum(1 for p in pnls if p > 0)
losses = sum(1 for p in pnls if p < 0)
total_pnl = sum(pnls)
gross_win = sum(p for p in pnls if p > 0)
gross_loss = abs(sum(p for p in pnls if p < 0))
total_fees = sum(float(r['Amount with GST']) for r in fees if r['Amount with GST'])
total_funding = sum(float(r['Amount with GST']) for r in fundings if r['Amount with GST'])

print('\n=== P&L ANALYSIS ===')
print(f'Total trades (cashflows): {len(pnls)}')
print(f'Winners: {wins} ({wins/max(len(pnls),1)*100:.1f}%)')
print(f'Losers: {losses} ({losses/max(len(pnls),1)*100:.1f}%)')
print(f'Total PnL: ${total_pnl:.2f}')
print(f'Gross win: ${gross_win:.2f}')
print(f'Gross loss: ${gross_loss:.2f}')
if gross_loss > 0:
    print(f'Profit factor: {gross_win/gross_loss:.2f}')
print(f'Total fees: ${total_fees:.2f}')
print(f'Total funding: ${total_funding:.2f}')
net = total_pnl + total_fees + total_funding
print(f'Net PnL (before fees/funding): ${net:.2f}')

dates = [r['_dt'] for r in futures_btc if r['_dt']]
if dates:
    print(f'\nDate range: {min(dates)} to {max(dates)}')
    days = (max(dates)-min(dates)).days
    print(f'Days: {days}')
    print(f'Trades/day: {len(pnls)/max(days,1):.2f}')

print(f'\n=== FEE ANALYSIS ===')
avg_fee_per_trade = total_fees / max(len(fees), 1)
print(f'Avg fee per trade: ${avg_fee_per_trade:.4f}')
if abs(total_pnl) > 0.01:
    fee_pct_of_pnl = abs(total_fees) / abs(total_pnl) * 100
    print(f'Fees as % of gross PnL: {fee_pct_of_pnl:.1f}%')

print(f'\n=== TRADE SIZE ANALYSIS ===')
pos_pnls = [abs(p) for p in pnls]
if pos_pnls:
    import statistics
    print(f'Avg |PnL|: ${statistics.mean(pos_pnls):.2f}')
    print(f'Median |PnL|: ${statistics.median(pos_pnls):.2f}')
    print(f'Max |PnL|: ${max(pos_pnls):.2f}')
    print(f'Min |PnL|: ${min(pos_pnls):.2f}')

options = [r for r in rows if r['Contract/Fund'] and r['Contract/Fund'] not in ('BTCUSD', '')]
print(f'\n=== OPTIONS TRADES ===')
print(f'Total option rows: {len(options)}')
opt_contracts = set(r['Contract/Fund'] for r in options)
for c in sorted(opt_contracts):
    c_rows = [r for r in options if r['Contract/Fund'] == c]
    c_cf = [float(r['Amount with GST']) for r in c_rows if r['Transaction type'] == 'cashflow' and r['Amount with GST']]
    c_f = [float(r['Amount with GST']) for r in c_rows if r['Transaction type'] == 'trading fees' and r['Amount with GST']]
    if c_cf:
        print(f'  {c}: {len(c_rows)} entries, PnL=${sum(c_cf):.2f} ({len(c_cf)} trades, {len(c_f)} fees)')

print(f'\n=== PNL DISTRIBUTION ===')
buckets = {  '<-5':0,  '-5 to -2':0,  '-2 to -1':0,  '-1 to 0':0,  '0 to 1':0,  '1 to 2':0,  '2 to 5':0,  '>5':0}
for p in pnls:
    if p < -5: buckets['<-5'] += 1
    elif p < -2: buckets['-5 to -2'] += 1
    elif p < -1: buckets['-2 to -1'] += 1
    elif p < 0: buckets['-1 to 0'] += 1
    elif p < 1: buckets['0 to 1'] += 1
    elif p < 2: buckets['1 to 2'] += 1
    elif p < 5: buckets['2 to 5'] += 1
    else: buckets['>5'] += 1
for k,v in buckets.items():
    print(f'  {k}: {v} trades')

# Sequence of PnLs to analyze patterns
print(f'\n=== TRADE SEQUENCE ===')
for i, p in enumerate(pnls[-20:], max(0, len(pnls)-19)):
    sign = '+' if p > 0 else ''
    print(f'  {i}. ${sign}{p:.2f}')
