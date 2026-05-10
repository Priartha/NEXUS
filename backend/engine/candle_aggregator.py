from __future__ import annotations

from datetime import datetime, timezone


TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


def timeframe_to_ms(timeframe: str) -> int:
    try:
        return TIMEFRAME_MS[timeframe]
    except KeyError as exc:
        supported = ", ".join(sorted(TIMEFRAME_MS))
        raise ValueError(f"Unsupported timeframe {timeframe!r}. Supported: {supported}") from exc


def floor_timestamp(ts_ms: int, timeframe: str) -> int:
    period_ms = timeframe_to_ms(timeframe)
    return (ts_ms // period_ms) * period_ms


def normalize_timestamp_ms(value: int | float | str) -> int:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.endswith("Z") or "T" in stripped:
            dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            return int(dt.astimezone(timezone.utc).timestamp() * 1000)
        value = float(stripped)

    numeric = int(value)
    if numeric > 10_000_000_000_000:
        return numeric // 1000
    if numeric > 10_000_000_000:
        return numeric
    return numeric * 1000

