"""Step 1: Fetch data only, save to file."""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle


async def main():
    print("Fetching 5m candles (3 batches = ~10.5 days)...")
    all_candles = []
    end_time = None
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(3):
            url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=1000"
            if end_time:
                url += f"&endTime={end_time}"
            resp = await client.get(url); resp.raise_for_status()
            data = resp.json()
            if not data: break
            for k in data:
                all_candles.append({"t":k[0],"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])})
            if len(data) < 1000: break
            end_time = data[0][0] - 1
            days = (all_candles[-1]["t"] - all_candles[0]["t"]) / (1000*86400)
            print(f"  Batch {i+1}: {len(all_candles)} candles ({days:.1f} days)")
            await asyncio.sleep(0.3)

    days = (all_candles[-1]["t"] - all_candles[0]["t"]) / (1000*86400)
    print(f"\nTotal: {len(all_candles)} candles ({days:.1f} days)")

    with open(Path(__file__).parent.parent/"fetched_candles.json","w") as f:
        json.dump(all_candles, f)
    print("Saved to fetched_candles.json")


if __name__ == "__main__":
    asyncio.run(main())
