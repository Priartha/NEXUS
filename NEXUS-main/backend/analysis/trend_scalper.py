import sys; sys.path.insert(0, r'C:\Users\priar\Downloads\NEXUS')
import json
from datetime import datetime, timezone
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle, ScalpContext

# Load June candles
with open(r'C:\Users\priar\Downloads\NEXUS\fetched_candles.json') as f:
    raw = json.load(f)
candles = [Candle(timestamp=c['t'],open=c['o'],high=c['h'],low=c['l'],close=c['c'],volume=c['v']) for c in raw]
candles.sort(key=lambda c: c.timestamp)
days = len(candles)*5/60/24

# Build 1h candles from 5m candles: group by hour
def build_hourly(five_min_candles):
    hourly = []
    current_hour = None
    for c in five_min_candles:
        ts = c.timestamp / 1000
        hour_start = int(ts // 3600 * 3600 * 1000)
        if hour_start != current_hour:
            if current_hour is not None and buf:
                opens.append(buf[0].open)
                closes.append(buf[-1].close)
                highs.append(max(c.high for c in buf))
                lows.append(min(c.low for c in buf))
                vols.append(sum(c.volume for c in buf))
            current_hour = hour_start
            buf = [c]
            opens = [c.open]
            closes = [c.close]
            highs = [c.high]
            lows = [c.low]
            vols = [c.volume]
        else:
            buf.append(c)
            closes[-1] = c.close
            highs[-1] = max(highs[-1], c.high)
            lows[-1] = min(lows[-1], c.low)
            vols[-1] += c.volume
    # flush
    if buf:
        hourly.append(Candle(timestamp=current_hour, open=opens[0], high=max(highs), low=min(lows), close=closes[-1], volume=sum(vols), symbol='BTCUSDT'))
    return hourly

try:
    hourly = build_hourly(candles)
    print(f"Built {len(hourly)} hourly candles")
    
    # Print first/last
    from datetime import datetime as dt2, timezone as tz2
    print(f"  Range: {dt2.fromtimestamp(hourly[0].timestamp/1000, tz=tz2.utc)} to {dt2.fromtimestamp(hourly[-1].timestamp/1000, tz=tz2.utc)}")
    
    # Quick check: hourly SMA50 trend
    h_closes = [c.close for c in hourly]
    h_price = h_closes[-1]
    h_sma50 = sum(h_closes[-50:]) / 50 if len(h_closes) >= 50 else h_price
    print(f"  Hourly price: ${h_price:.0f}, SMA50: ${h_sma50:.0f}, {'ABOVE (uptrend)' if h_price > h_sma50 else 'BELOW (downtrend)'}")
except Exception as e:
    print(f"Error building hourly: {e}")
    import traceback; traceback.print_exc()
