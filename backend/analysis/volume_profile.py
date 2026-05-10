from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.analysis.ids import stable_id
from backend.models.types import Candle


def compute_volume_profile(
    candles: list[Candle],
    num_bins: int = 24,
) -> dict[str, Any]:
    """Build a volume profile histogram across fixed price bins."""
    if not candles:
        return {"bins": [], "poc": None, "value_area_low": None, "value_area_high": None}

    price_min = min(c.low for c in candles)
    price_max = max(c.high for c in candles)
    if price_max <= price_min:
        return {"bins": [], "poc": None, "value_area_low": None, "value_area_high": None}

    bin_size = (price_max - price_min) / num_bins
    bins: dict[int, float] = defaultdict(float)
    bin_prices: dict[int, float] = {}

    for c in candles:
        vol = c.volume
        c_min = min(c.low, c.high)
        c_max = max(c.low, c.high)
        if c_max <= c_min:
            continue
        step = (c_max - c_min) / 10
        for p in [c_min + step * i for i in range(11)]:
            idx = int((p - price_min) / bin_size) if bin_size > 0 else 0
            idx = min(idx, num_bins - 1)
            bins[idx] += vol / 11
            bin_prices[idx] = price_min + idx * bin_size + bin_size / 2

    sorted_bins = sorted(bins.items(), key=lambda x: -x[1])
    poc_idx = sorted_bins[0][0] if sorted_bins else None
    poc_price = bin_prices.get(poc_idx) if poc_idx is not None else None
    poc_volume = bins.get(poc_idx, 0) if poc_idx is not None else 0

    total_volume = sum(bins.values())
    value_area_idx = set()
    cum_vol = 0.0
    for idx, _ in sorted_bins:
        value_area_idx.add(idx)
        cum_vol += bins[idx]
        if cum_vol / total_volume >= 0.70:
            break

    va_low = min(bin_prices[i] for i in value_area_idx) if value_area_idx else price_min
    va_high = max(bin_prices[i] for i in value_area_idx) if value_area_idx else price_max

    return {
        "bins": [
            {
                "price": round(bin_prices[idx], 2),
                "volume": round(vol, 2),
                "is_poc": idx == poc_idx,
                "is_value_area": idx in value_area_idx,
            }
            for idx, vol in sorted(bins.items(), key=lambda x: x[0])
        ],
        "poc": round(poc_price, 2) if poc_price is not None else None,
        "poc_volume": round(poc_volume, 2),
        "value_area_low": round(va_low, 2),
        "value_area_high": round(va_high, 2),
        "total_volume": round(total_volume, 2),
    }


def compute_market_profile(
    candles: list[Candle],
) -> dict[str, Any]:
    """Compute Market Profile TPO (Time Price Opportunity) structure."""
    if not candles:
        return {}

    tpo: dict[str, set[str]] = {}
    for c in candles:
        price_key = f"{int(c.low)}-{int(c.high) + 1}"
        letter = chr(65 + (len(tpo) % 26))
        if price_key not in tpo:
            tpo[price_key] = set()
        tpo[price_key].add(letter)

    tpo_list = [
        {"price_range": k, "tpo_count": len(v), "letters": "".join(sorted(v))[:6]}
        for k, v in tpo.items()
    ]
    tpo_list.sort(key=lambda x: int(x["price_range"].split("-")[0]))

    return {
        "tpo_count": len(tpo),
        "tpo_letters": len(set().union(*tpo.values())) if tpo else 0,
        "structure": tpo_list,
    }
