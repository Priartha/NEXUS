"""
Delta Exchange BTC Futures Context Builder.

Provides futures-specific market data context:
- Funding rate (current, annualized, predicted 8h)
- Open interest (value, change %, trend)
- Liquidation clusters (estimated levels)
- Contract info (mark price, product ID)
"""

from __future__ import annotations

import math
import time
from typing import Any

from backend.models.types import FuturesContext, FuturesContract


def build_futures_context(
    payload: dict[str, Any],
    funding_rate: float = 0.0,
    open_interest: float = 0.0,
    open_interest_change_pct: float = 0.0,
    mark_price: float | None = None,
    product_id: int = 0,
    next_funding_ts: int | None = None,
    volume_24h: float = 0.0,
    liquidation_data: list[dict] | None = None,
    source_error: str | None = None,
) -> FuturesContext:
    now_ms = int(time.time() * 1000)
    candle = _dict(payload.get("candle"))
    timestamp = int(candle.get("timestamp") or now_ms)

    # Funding rate analysis
    funding_annualized = funding_rate * 365 * 3
    is_extreme = abs(funding_rate) > 0.001
    contrarian_bias = (
        "bullish" if funding_rate < -0.0005
        else "bearish" if funding_rate > 0.0005
        else "neutral"
    )

    # OI trend determination
    oi_trend = "neutral"
    oi_momentum = False
    if open_interest_change_pct > 2.0:
        oi_trend = "increasing"
        oi_momentum = True
    elif open_interest_change_pct < -2.0:
        oi_trend = "decreasing"

    liquidation_clusters = _build_liquidation_clusters(liquidation_data, mark_price)

    contract = FuturesContract(
        symbol=str(candle.get("symbol", "BTCUSD")),
        product_id=product_id,
        mark_price=mark_price,
        mark_price_timestamp=now_ms,
        funding_rate=funding_rate,
        funding_rate_timestamp=now_ms,
        next_funding_timestamp=next_funding_ts,
        open_interest=open_interest,
        open_interest_change_pct=open_interest_change_pct,
        volume_24h=volume_24h,
    )

    estimated_funding_cost = funding_rate * 3  # 3 funding periods in 8h for perpetuals

    blockers: list[str] = []
    if is_extreme:
        blockers.append(f"Funding extreme: {funding_rate * 100:.3f}%")
    if funding_annualized > 0.5:
        blockers.append(f"High funding cost: {funding_annualized * 100:.1f}% APR")
    if source_error:
        blockers.append(f"Futures data error: {source_error}")

    return FuturesContext(
        timestamp=timestamp,
        contract=contract,
        funding_rate=round(funding_rate, 6),
        funding_annualized=round(funding_annualized, 4),
        funding_contrarian_bias=contrarian_bias,
        is_funding_extreme=is_extreme,
        oi_value=round(open_interest, 2),
        oi_change_pct=round(open_interest_change_pct, 4),
        oi_trend=oi_trend,
        oi_momentum_confirmation=oi_momentum,
        liquidation_clusters=liquidation_clusters,
        estimated_funding_pnl_pct=round(estimated_funding_cost, 6),
        blockers=blockers[:6],
        error=source_error,
    )


def _build_liquidation_clusters(
    liq_data: list[dict] | None,
    mark_price: float | None,
) -> list[dict]:
    if liq_data:
        return [
            {
                "price": float(e.get("price", 0)),
                "size": float(e.get("size", 0)),
                "side": str(e.get("side", "long")),
                "distance_pct": round(abs(float(e.get("price", 0)) - (mark_price or 0)) / max(mark_price or 1, 0.01) * 100, 3),
                "strength": _clamp(float(e.get("size", 0)) / 1_000_000, 0, 1),
            }
            for e in liq_data[:10]
        ]
    return []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
