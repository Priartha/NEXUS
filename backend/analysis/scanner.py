"""
NEXUS Market Scanner — Research & Analytics Tool
Provides real-time market condition analysis for manual trade decisions.
"""

import json
from datetime import datetime, timezone
from typing import Any

from backend.analysis.events_calendar import scan_for_events as _scan_events


def load_candles(path: str) -> list[dict]:
    with open(path) as f:
        raw = json.load(f)
    raw.sort(key=lambda c: c["t"])
    return raw


def calc_atr(clist: list, period: int = 14) -> float:
    if len(clist) < 2:
        return 0.0
    rngs = []
    for j in range(1, min(period + 1, len(clist))):
        a = clist[-(j + 1)]
        b = clist[-j]
        rngs.append(max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"])))
    return sum(rngs) / len(rngs) if rngs else 0.0


def compute_velocity(closes: list[float]) -> dict:
    """Compute weighted velocity from ROC1/ROC3/ROC5."""
    if len(closes) < 2 or closes[-2] <= 0:
        return {"roc1": 0.0, "roc3": 0.0, "roc5": 0.0, "velocity": 0.0}
    roc1 = (closes[-1] - closes[-2]) / closes[-2] * 100
    roc3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 5 and closes[-4] > 0 else roc1
    roc5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 7 and closes[-6] > 0 else roc3
    velocity = roc1 * 0.5 + roc3 * 0.3 + roc5 * 0.2
    return {"roc1": roc1, "roc3": roc3, "roc5": roc5, "velocity": velocity}


def compute_vol_ratio(vols: list[float]) -> float:
    recent = sum(vols[-3:]) / 3
    base = sum(vols[-20:-3]) / 17 if len(vols) >= 20 else recent
    return recent / base if base > 0 else 1.0


def get_hourly_trend(candles: list[dict], ts: int, trend_period: int = 50) -> tuple[bool, float]:
    """Compute trend from hourly-aggregated candles."""
    hs = (ts // 3600000) * 3600000
    hourly = {}
    for c in candles:
        hk = (c["t"] // 3600000) * 3600000
        if hk not in hourly:
            hourly[hk] = []
        hourly[hk].append(c["c"])

    sorted_hours = sorted(hourly.keys())
    if hs not in hourly:
        return True, 0.0

    idx = sorted_hours.index(hs)
    if idx < trend_period:
        return True, 0.0

    recent = sorted_hours[idx - trend_period + 1 : idx + 1]
    h_closes = [hourly[h][-1] for h in recent]
    sma = sum(h_closes) / len(h_closes)
    price = hourly[hs][-1]
    return price > sma, sma


def scan_candle_data(
    candles: list[dict],
    lookback: int = 300,
    atr_period: int = 14,
    vol_period: int = 20,
    trend_period: int = 50,
) -> dict[str, Any]:
    """Analyze the latest candle in the dataset and return market conditions."""
    if len(candles) < max(lookback, vol_period + 10):
        return {"error": "insufficient data"}

    window = candles[-lookback:]
    current = window[-1]
    closes = [c["c"] for c in window]
    vols = [c["v"] for c in window]
    price = closes[-1]

    atr = calc_atr(window, atr_period)
    atr_pct = atr / price * 100 if price > 0 else 0

    vel = compute_velocity(closes)
    vol_ratio = compute_vol_ratio(vols[-max(vol_period + 10, len(vols)) :])

    is_uptrend, h_sma = get_hourly_trend(candles, current["t"], trend_period)

    # Momentum score (simplified v2)
    min_vel = 0.03 * max(atr_pct, 0.01)
    vel_mag = min(abs(vel["velocity"]) / max(atr_pct * 3, 0.01), 1.0)

    # Patterns from research
    patterns = detect_patterns(vel, vol_ratio, atr_pct, is_uptrend, price, atr)

    utc_dt = datetime.fromtimestamp(current["t"] / 1000, tz=timezone.utc)
    ist_hour = (utc_dt.hour + 5) % 24
    good_hours = {0, 2, 3, 4, 7, 8, 9, 11, 14, 16, 20, 22, 23}

    return {
        "timestamp": utc_dt.isoformat(),
        "price": round(price, 2),
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 3),
        "velocity": {
            "roc1": round(vel["roc1"], 3),
            "roc3": round(vel["roc3"], 3),
            "roc5": round(vel["roc5"], 3),
            "weighted": round(vel["velocity"], 3),
        },
        "vol_ratio": round(vol_ratio, 2),
        "trend": "uptrend" if is_uptrend else "downtrend",
        "hourly_sma50": round(h_sma, 2),
        "momentum_strength": round(vel_mag, 2),
        "ist_hour": ist_hour,
        "ist_hour_good": ist_hour in good_hours,
        "patterns": patterns,
        "events": _scan_events(window, lookback),
    }


def detect_patterns(
    vel: dict, vol_ratio: float, atr_pct: float, uptrend: bool, price: float, atr: float
) -> list[dict]:
    """Detect known trade patterns from CSV research."""
    matches = []

    # Momentum breakout (original v2)
    if abs(vel["velocity"]) > atr_pct * 3 and vol_ratio > 1.5:
        direction = "bullish" if vel["velocity"] > 0 else "bearish"
        matches.append(
            {
                "name": "momentum_breakout",
                "direction": direction,
                "strength": round(min(abs(vel["velocity"]) / max(atr_pct * 3, 0.01), 1.0), 2),
            }
        )

    # Dip buy pattern (counter-trend, user's CSV pattern)
    if not uptrend and vel["velocity"] < -0.05 and vol_ratio > 1.2 and atr_pct > 0.08:
        matches.append(
            {
                "name": "dip_buy_downtrend",
                "direction": "long",
                "note": "Counter-trend dip in downtrend — user's CSV pattern",
            }
        )

    # Rally sell pattern
    if uptrend and vel["velocity"] > 0.05 and vol_ratio > 1.2 and atr_pct > 0.08:
        matches.append(
            {
                "name": "rally_sell_uptrend",
                "direction": "short",
                "note": "Counter-trend rally in uptrend",
            }
        )

    # With-trend momentum
    if uptrend and vel["velocity"] > 0.08 and vol_ratio > 1.3:
        matches.append(
            {
                "name": "trend_momentum_buy",
                "direction": "long",
                "note": "Momentum with uptrend",
            }
        )

    if not uptrend and vel["velocity"] < -0.08 and vol_ratio > 1.3:
        matches.append(
            {
                "name": "trend_momentum_sell",
                "direction": "short",
                "note": "Momentum with downtrend",
            }
        )

    # High velocity (any direction)
    if abs(vel["velocity"]) > 0.15 and vol_ratio > 1.5:
        matches.append(
            {
                "name": "high_velocity",
                "direction": "up" if vel["velocity"] > 0 else "down",
                "strength": round(abs(vel["velocity"]), 3),
            }
        )

    return matches


def print_scan(result: dict):
    """Pretty-print scanner result."""
    print(f"\n{'='*60}")
    print(f"  NEXUS Market Scanner - {result.get('timestamp', 'N/A')}")
    print(f"{'='*60}")

    # Market snapshot
    p = result
    print(f"\n  Price:      ${p['price']:>8,.2f}")
    print(f"  ATR(14):    {p['atr']:>8.2f}  ({p['atr_pct']:.3f}%)")
    print(
        f"  Velocity:   {p['velocity']['roc1']:>+7.3f}% (1bar)  "
        f"{p['velocity']['roc3']:>+7.3f}% (3bar)  "
        f"{p['velocity']['roc5']:>+7.3f}% (5bar)"
    )
    print(f"  Weighted:   {p['velocity']['weighted']:>+8.3f}%")
    print(f"  Vol Ratio:  {p['vol_ratio']:>8.2f}x")
    print(f"  Trend:      {p['trend']:>8s}  (SMA50=${p['hourly_sma50']:,.2f})")
    print(f"  Mom.Stren:  {p['momentum_strength']:>8.2f}")
    print(f"  IST Hour:   {p['ist_hour']:>2d} {'OK' if p['ist_hour_good'] else 'BLOCKED'}")

    # Patterns
    if p.get("patterns"):
        print(f"\n  -- Detected Patterns --")
        for pat in p["patterns"]:
            d = "^" if pat.get("direction") in ("long", "bullish", "up") else "v"
            strength = pat.get("strength", "")
            strength_str = f" [{strength}]" if strength else ""
            print(f"    {d} {pat['name']}{strength_str}")
            if "note" in pat:
                print(f"       {pat['note']}")
    else:
        print(f"\n  No known patterns detected.")

    # Events
    ev = p.get("events", {})
    has_events = ev.get("events_in_48h", 0) > 0 or ev.get("anomalies") or ev.get("is_event_day", False)

    if has_events:
        print(f"\n  -- Events / News --")
        if ev.get("is_event_day"):
            for ae in ev.get("active_events_24h", []):
                print(f"  NEWS TODAY: {ae['name']} ({ae['impact']})")
        if ev.get("next_event"):
            ne = ev["next_event"]
            if ne.get("hours_until", 0) > 0:
                label = "NEXT" if ne.get("hours_until", 0) > 0 else "RECENT"
                print(f"  {label}: {ne['name']} in {ne['hours_until']:.0f}h [{ne['impact']}]")
        for ca in ev.get("calendar", [])[:3]:
            hrs = ca["hours_until"]
            label = f"in {hrs:.0f}h" if hrs > 0 else f"{abs(hrs):.0f}h ago"
            print(f"  - {ca['name']:45s} {label:>10s} [{ca['impact']}]")
        for an in ev.get("anomalies", []):
            print(f"  ! {an['signal']}: {an['detail']}")

    # Quick assessment
    print(f"\n   -- Assessment --")
    if ev.get("is_event_day"):
        print(f"  NEWS DAY -- expect expanded range, avoid tight stops")
    elif ev.get("events_in_48h", 0) > 0:
        print(f"  EVENT WINDOW -- macro event within 48h, be cautious")
    if p["vol_ratio"] > 1.5 and abs(p["velocity"]["weighted"]) > 0.10:
        print(f"  HIGH: strong velocity + volume")
    elif p["vol_ratio"] > 1.2 and abs(p["velocity"]["weighted"]) > 0.05:
        print(f"  MODERATE: monitor for confirmation")
    else:
        print(f"  LOW activity -- no clear signal")
    print()


if __name__ == "__main__":
    # Demo with June candles
    data = load_candles(r"C:\Users\priar\Downloads\NEXUS\fetched_candles.json")
    result = scan_candle_data(data)
    print_scan(result)
