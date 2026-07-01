import asyncio, time, sys
sys.path.insert(0, 'D:\\Trading Setup\\NEXUS')

from scripts.production_backtest_optimizer import fetch_binance_candles, ProductionBacktest, BacktestConfig

async def main():
    print('Fetching 2000 candles...')
    candles = await fetch_binance_candles('BTCUSDT', '5m', 2000)
    print(f'Got {len(candles)} candles')
    
    config = BacktestConfig()
    bt = ProductionBacktest(config)
    
    t0 = time.time()
    result = bt.run(candles)
    elapsed = time.time() - t0
    
    print(f'Backtest done in {elapsed:.1f}s')
    trades = result['total_trades']
    pnl = result['total_pnl_pct']
    wr = result['win_rate'] * 100
    print(f'Trades: {trades}, PnL: {pnl}%, WR: {wr:.1f}%')
    
    # Estimate total time for 64 configs
    total_time = elapsed * 64
    print(f'Estimated total for 64 configs: {total_time/60:.1f} minutes')

asyncio.run(main())
