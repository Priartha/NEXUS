"""
Bitcoin Macro Events Calendar
Detects high-impact news/macro events and special Bitcoin occasions.
"""

from datetime import datetime, timezone, timedelta
from typing import Any


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    """Get the nth occurrence of a weekday (0=Mon) in a month."""
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    day = first
    count = 0
    while day.month == month:
        if day.weekday() == weekday:
            count += 1
            if count == n:
                return day
        day += timedelta(days=1)
    return first


def _last_weekday_of_month(year: int, month: int, weekday: int) -> datetime:
    """Get the last occurrence of a weekday in a month."""
    last = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1) if month < 12 else datetime(year, 12, 31, tzinfo=timezone.utc)
    while last.weekday() != weekday:
        last -= timedelta(days=1)
    return last


_EVENT_CACHE: dict[int, list[dict]] = {}


def get_macro_events(year: int) -> list[dict]:
    """Return all known macro events for a given year."""
    if year in _EVENT_CACHE:
        return _EVENT_CACHE[year]

    events = []

    # FOMC meetings (typically Jan, Mar, May, Jun, Jul, Sep, Nov, Dec)
    # Exact dates announced ~6 months ahead; these are reasonable estimates
    fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
    for m in fomc_months:
        # FOMC is typically Tue-Wed, ~3rd week
        meeting = _nth_weekday_of_month(year, m, 1, 3)  # 3rd Tuesday
        events.append({
            "event": "FOMC Meeting",
            "date": meeting.strftime("%Y-%m-%d"),
            "timestamp_ms": int(meeting.timestamp() * 1000),
            "impact": "high",
            "detail": "Federal Reserve interest rate decision. Major BTC volatility event.",
        })

    # CPI - monthly, usually 2nd week (Tue-Thu)
    for m in range(1, 13):
        cpi = _nth_weekday_of_month(year, m, 1, 2)  # 2nd Tuesday
        cpi += timedelta(days=1) if cpi.weekday() != 1 else timedelta(days=0)
        events.append({
            "event": "CPI Release",
            "date": cpi.strftime("%Y-%m-%d"),
            "timestamp_ms": int(cpi.timestamp() * 1000),
            "impact": "high",
            "detail": "Consumer Price Index. Inflation data affects rate expectations.",
        })

    # PPI - monthly, day after CPI
    for m in range(1, 13):
        ppi = _nth_weekday_of_month(year, m, 1, 2)  # 2nd Tuesday
        ppi += timedelta(days=1)
        events.append({
            "event": "PPI Release",
            "date": ppi.strftime("%Y-%m-%d"),
            "timestamp_ms": int(ppi.timestamp() * 1000),
            "impact": "medium",
            "detail": "Producer Price Index. Wholesale inflation indicator.",
        })

    # NFP - 1st Friday each month
    for m in range(1, 13):
        nfp = _nth_weekday_of_month(year, m, 4, 1)  # 1st Friday
        events.append({
            "event": "NFP",
            "date": nfp.strftime("%Y-%m-%d"),
            "timestamp_ms": int(nfp.timestamp() * 1000),
            "impact": "high",
            "detail": "Non-Farm Payrolls. Key employment data.",
        })

    # BTC Monthly Options Expiry - last Friday
    for m in range(1, 13):
        expiry = _last_weekday_of_month(year, m, 4)  # Last Friday
        events.append({
            "event": "BTC Options Expiry (Monthly)",
            "date": expiry.strftime("%Y-%m-%d"),
            "timestamp_ms": int(expiry.timestamp() * 1000),
            "impact": "medium",
            "detail": "Monthly BTC options expiry. Often causes pinning/volatility.",
        })

    # BTC Quarterly Options Expiry - last Friday of Mar/Jun/Sep/Dec
    for m in [3, 6, 9, 12]:
        expiry = _last_weekday_of_month(year, m, 4)
        events.append({
            "event": "BTC Quarterly Options Expiry",
            "date": expiry.strftime("%Y-%m-%d"),
            "timestamp_ms": int(expiry.timestamp() * 1000),
            "impact": "high",
            "detail": "Quarterly BTC options expiry. Large open interest, major volatility.",
        })

    # CBOE Bitcoin Futures Expiry - last Friday
    for m in range(1, 13):
        expiry = _last_weekday_of_month(year, m, 4)
        events.append({
            "event": "CBOE BTC Futures Expiry",
            "date": expiry.strftime("%Y-%m-%d"),
            "timestamp_ms": int(expiry.timestamp() * 1000),
            "impact": "medium",
            "detail": "CBOE Bitcoin futures expiry. Settlement-related price action.",
        })

    # Known SEC deadlines and crypto-specific dates for 2026
    crypto_dates = [
        ("SEC BTC/ETH ETF Decision Deadline", "2026-03-15", "medium"),
        ("Tax Day (US)", "2026-04-15", "medium"),
        ("Bitcoin Whitepaper Anniversary", "2026-10-31", "low"),
    ]
    for name, date_str, impact in crypto_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        events.append({
            "event": name,
            "date": date_str,
            "timestamp_ms": int(dt.timestamp() * 1000),
            "impact": impact,
            "detail": "",
        })

    # Major crypto conferences
    conf_dates = [
        ("Bitcoin 2026 Conference", "2026-05-27", "medium"),
        ("Consensus 2026", "2026-06-10", "medium"),
        ("Token2049 Singapore", "2026-09-16", "low"),
    ]
    for name, date_str, impact in conf_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        events.append({
            "event": name,
            "date": date_str,
            "timestamp_ms": int(dt.timestamp() * 1000),
            "impact": impact,
            "detail": "",
        })

    # Halving cycle status
    events.append({
        "event": "BTC Halving Cycle",
        "date": "2026-01-01",
        "timestamp_ms": int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
        "impact": "ongoing",
        "detail": "Next halving estimated ~2028. Currently in post-halving reaccumulation phase.",
    })

    events.sort(key=lambda e: e["date"])
    _EVENT_CACHE[year] = events
    return events


def get_events_near(timestamp_ms: int, window_hours: int = 48) -> list[dict]:
    """Get macro events within a time window of the given timestamp."""
    ts = timestamp_ms / 1000
    window_ms = window_hours * 3600 * 1000
    year = datetime.fromtimestamp(ts, tz=timezone.utc).year
    events = []
    # Check current and adjacent years
    for y in [year - 1, year, year + 1]:
        for e in get_macro_events(y):
            diff = abs(e["timestamp_ms"] - timestamp_ms)
            if diff <= window_ms:
                events.append({
                    **e,
                    "hours_until": round((e["timestamp_ms"] - timestamp_ms) / 3600000, 1),
                    "diff_ms": diff,
                })
    events.sort(key=lambda e: e["diff_ms"])
    return events


def detect_event_volatility(candles: list[dict], lookback: int = 100) -> list[dict]:
    """Detect volatility anomalies that suggest an event-driven market."""
    if len(candles) < lookback:
        return []

    window = candles[-lookback:]
    closes = [c["c"] for c in window]
    price = closes[-1]

    # Compute rolling ATR
    def atr_slice(clist):
        if len(clist) < 2:
            return 0
        rngs = []
        for j in range(1, min(15, len(clist))):
            a = clist[-(j + 1)]
            b = clist[-j]
            rngs.append(max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])))
        return sum(rngs) / len(rngs) if rngs else 0

    # ATR expansion detection
    atr_now = atr_slice(window[-15:])
    atr_median = atr_slice(window[-60:-15]) if len(window) > 60 else atr_now
    atr_ratio = atr_now / max(atr_median, 1)
    atr_pct = atr_now / price * 100 if price > 0 else 0

    signals = []
    if atr_ratio > 2.0 and atr_pct > 0.15:
        signals.append({
            "signal": "atr_spike",
            "ratio": round(atr_ratio, 2),
            "atr_pct": round(atr_pct, 3),
            "detail": f"ATR spike {atr_ratio:.1f}x median — possible event-driven volatility",
        })

    # Volume anomaly
    def vol_slice(vlist):
        if len(vlist) < 3:
            return 0
        return sum(vlist[-3:]) / 3

    vols = [c["v"] for c in window]
    recent_vol = vol_slice(vols)
    base_vol = vol_slice(vols[:-15]) if len(vols) > 15 else recent_vol
    vol_ratio = recent_vol / max(base_vol, 1)

    if vol_ratio > 2.5:
        signals.append({
            "signal": "volume_surge",
            "ratio": round(vol_ratio, 2),
            "detail": f"Volume {vol_ratio:.1f}x normal — unusual participation",
        })

    # Intraday range expansion
    recent_high = max(c["h"] for c in window[-24:])
    recent_low = min(c["l"] for c in window[-24:])
    range_pct = (recent_high - recent_low) / price * 100 if price > 0 else 0

    if range_pct > 2.0:
        signals.append({
            "signal": "wide_range",
            "range_pct": round(range_pct, 2),
            "detail": f"24-bar range {range_pct:.1f}% — wide price action",
        })

    return signals


def scan_for_events(candles: list[dict], lookback: int = 100) -> dict[str, Any]:
    """Full events scan: known calendar events + volatility anomaly detection."""
    if not candles:
        return {"events_near": [], "anomalies": [], "is_event_day": False}

    latest = candles[-1]
    ts = latest["t"]

    # Calendar events within 7 days
    calendar = get_events_near(ts, window_hours=168)

    # Volatility anomalies
    anomalies = detect_event_volatility(candles, lookback)

    # Is today (within 24h) an event day?
    nearby = [e for e in calendar if -24 <= e["hours_until"] <= 0]
    is_event_day = len(nearby) > 0

    # Event-free until (next event)
    future = [e for e in calendar if e["hours_until"] > 0]
    next_event = min(future, key=lambda e: e["hours_until"]) if future else None

    return {
        "is_event_day": is_event_day,
        "events_in_48h": len(calendar),
        "next_event": {
            "name": next_event["event"],
            "date": next_event["date"],
            "hours_until": next_event["hours_until"],
            "impact": next_event.get("impact", "unknown"),
            "detail": next_event.get("detail", ""),
        } if next_event else None,
        "active_events_24h": [
            {"name": e["event"], "impact": e.get("impact", "unknown"), "detail": e.get("detail", "")}
            for e in nearby
        ],
        "calendar": [
            {
                "name": e["event"],
                "hours_until": e["hours_until"],
                "impact": e.get("impact", "unknown"),
                "date": e.get("date", ""),
            }
            for e in calendar[:10]  # Limit to 10 nearest
        ],
        "anomalies": anomalies,
    }


if __name__ == "__main__":
    # Demo
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = scan_for_events([{"t": now, "h": 65000, "l": 64000, "c": 64500, "v": 1000}])
    for k, v in result.items():
        print(f"{k}: {v}")
