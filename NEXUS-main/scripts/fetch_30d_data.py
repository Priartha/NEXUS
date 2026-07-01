import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle


async def fetch_binance_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    days: int = 30,
) -> list[Candle]:
    """Fetch 30+ days of historical candles from Binance."""
    # Binance allows max 1000 candles per request
    # 5m: 288 candles/day, so 1000 candles = ~3.5 days
    # Need multiple requests for 30 days
    
    candles_per_request = 1000
    candles_per_day = {"1m": 1440, "3m": 480, "5m": 288, "15m": 96, "1h": 24}
    daily_candles = candles_per_day.get(interval, 288)
    total_needed = days * daily_candles
    
    print(f"Fetching {days} days of {interval} data (~{total_needed} candles)...")
    
    all_candles = []
    end_time = None
    
    # Calculate how many requests needed
    requests_needed = (total_needed + candles_per_request - 1) // candles_per_request
    
    for i in range(requests_needed):
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={candles_per_request}"
        if end_time:
            url += f"&endTime={end_time}"
        
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        
        if not data:
            break
        
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
        
        all_candles.extend(candles)
        end_time = candles[0].timestamp - 1  # Get data before first candle
        
        print(f"  Request {i+1}/{requests_needed}: Fetched {len(candles)} candles")
        
        # Rate limit: wait 100ms between requests
        if i < requests_needed - 1:
            await asyncio.sleep(0.1)
    
    # Sort by timestamp and remove duplicates
    all_candles.sort(key=lambda c: c.timestamp)
    
    # Remove duplicates
    seen = set()
    unique_candles = []
    for c in all_candles:
        if c.timestamp not in seen:
            seen.add(c.timestamp)
            unique_candles.append(c)
    
    print(f"Total unique candles: {len(unique_candles)}")
    return unique_candles


async def main():
    print("=== FETCHING 30 DAYS OF HISTORICAL DATA ===\n")
    
    candles = await fetch_binance_candles(symbol="BTCUSDT", interval="5m", days=30)
    
    if candles:
        start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[0].timestamp / 1000))
        end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1].timestamp / 1000))
        print(f"\nPeriod: {start} to {end}")
        print(f"Total candles: {len(candles)}")
        
        # Save to file
        import json
        output_path = Path(__file__).parent.parent / "historical_data_30d.json"
        data = [{
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        } for c in candles]
        
        with open(output_path, "w") as f:
            json.dump(data, f)
        
        print(f"\nData saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
