"""
BTC/USDT Options Scalping Analysis

Options-specific logic for scalping:
- IV Rank / IV Percentile calculation
- Delta targeting: 0.30-0.50 for directional scalps
- Gamma sensitivity for fast moves
- DTE selection: 0-3 DTE for pure scalping, 7 DTE max
- Premium exit: +40% to +80% gain OR delta drops below 0.20
- Breakeven SL after +20% premium gain
- Avoid entries within 30 mins of major news/macro events
- Bid/ask spread check: avoid wide spread strikes (> 0.5% of premium)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OptionsStrikeInfo:
    strike: float
    call_bid: float = 0.0
    call_ask: float = 0.0
    put_bid: float = 0.0
    put_ask: float = 0.0
    call_delta: float = 0.0
    put_delta: float = 0.0
    call_gamma: float = 0.0
    put_gamma: float = 0.0
    call_theta: float = 0.0
    put_theta: float = 0.0
    call_iv: float = 0.0
    put_iv: float = 0.0
    call_volume: float = 0.0
    put_volume: float = 0.0
    call_oi: float = 0.0
    put_oi: float = 0.0
    dte: int = 0


@dataclass
class OptionsScalpRecommendation:
    timestamp: int
    action: str
    strike: float
    dte: int
    direction: str
    entry_premium: float = 0.0
    target_premium: float = 0.0
    stop_premium: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta_per_hour: float = 0.0
    spread_pct: float = 0.0
    reason: str = ""
    confidence: str = "MEDIUM"
    blockers: list[str] = field(default_factory=list)


class OptionsScalpAnalyzer:
    """Options-specific analysis for BTC/USDT scalping."""

    def __init__(self) -> None:
        self._chain: list[OptionsStrikeInfo] = []
        self._iv_history: list[float] = []
        self._current_iv: float = 0.0
        self._spot_price: float = 0.0

    def update_chain(self, chain: list[OptionsStrikeInfo]) -> None:
        self._chain = chain

    def update_iv(self, iv: float) -> None:
        self._current_iv = iv
        self._iv_history.append(iv)
        if len(self._iv_history) > 252:
            self._iv_history = self._iv_history[-252:]

    def update_spot(self, price: float) -> None:
        self._spot_price = price

    def compute_iv_rank(self) -> float:
        if len(self._iv_history) < 2:
            return 0.0
        low = min(self._iv_history)
        high = max(self._iv_history)
        if high == low:
            return 50.0
        return (self._current_iv - low) / (high - low) * 100

    def compute_iv_percentile(self) -> float:
        if len(self._iv_history) < 2:
            return 0.0
        below = sum(1 for v in self._iv_history if v <= self._current_iv)
        return below / len(self._iv_history) * 100

    def find_best_call(
        self,
        target_delta_min: float = 0.30,
        target_delta_max: float = 0.50,
        max_dte: int = 3,
    ) -> OptionsStrikeInfo | None:
        candidates = [
            s for s in self._chain
            if s.dte <= max_dte
            and target_delta_min <= s.call_delta <= target_delta_max
            and s.call_ask > 0
            and s.call_bid > 0
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda s: s.call_gamma, reverse=True)

        for c in candidates:
            spread_pct = (c.call_ask - c.call_bid) / c.call_ask
            if spread_pct <= 0.005:
                return c

        return candidates[0] if candidates else None

    def find_best_put(
        self,
        target_delta_min: float = 0.30,
        target_delta_max: float = 0.50,
        max_dte: int = 3,
    ) -> OptionsStrikeInfo | None:
        candidates = [
            s for s in self._chain
            if s.dte <= max_dte
            and target_delta_min <= abs(s.put_delta) <= target_delta_max
            and s.put_ask > 0
            and s.put_bid > 0
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda s: s.put_gamma, reverse=True)

        for c in candidates:
            spread_pct = (c.put_ask - c.put_bid) / c.put_ask
            if spread_pct <= 0.005:
                return c

        return candidates[0] if candidates else None

    def evaluate_buy_option(
        self,
        strike: OptionsStrikeInfo,
        direction: str,
        ivr: float,
    ) -> OptionsScalpRecommendation:
        import time
        blockers: list[str] = []

        if direction == "call":
            premium = strike.call_ask
            delta = strike.call_delta
            gamma = strike.call_gamma
            theta = strike.call_theta
            spread = (strike.call_ask - strike.call_bid) / strike.call_ask if strike.call_ask > 0 else 1.0
        else:
            premium = strike.put_ask
            delta = abs(strike.put_delta)
            gamma = strike.put_gamma
            theta = strike.put_theta
            spread = (strike.put_ask - strike.put_bid) / strike.put_ask if strike.put_ask > 0 else 1.0

        if spread > 0.005:
            blockers.append(f"Spread too wide: {spread * 100:.2f}% > 0.5%")

        if delta < 0.20 or delta > 0.60:
            blockers.append(f"Delta {delta:.2f} outside 0.20-0.60 range")

        if ivr > 50:
            blockers.append(f"IVR {ivr:.0f} too high for buying — consider selling premium")

        if strike.dte > 7:
            blockers.append(f"DTE {strike.dte} too long for scalping (max 7)")

        target_premium = premium * 1.60
        stop_premium = premium * 0.70

        theta_per_hour = abs(theta) / 24.0

        confidence = "MEDIUM"
        if gamma > 0.001 and delta >= 0.30 and delta <= 0.50:
            confidence = "HIGH"

        return OptionsScalpRecommendation(
            timestamp=int(time.time() * 1000),
            action=f"BUY {direction.upper()}",
            strike=strike.strike,
            dte=strike.dte,
            direction=direction,
            entry_premium=round(premium, 4),
            target_premium=round(target_premium, 4),
            stop_premium=round(stop_premium, 4),
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta_per_hour=round(theta_per_hour, 6),
            spread_pct=round(spread * 100, 3),
            reason=f"Delta {delta:.2f}, Gamma {gamma:.4f}, IVR {ivr:.0f}, DTE {strike.dte}",
            confidence=confidence,
            blockers=blockers,
        )

    def evaluate_sell_spread(
        self,
        short_strike: OptionsStrikeInfo,
        long_strike: OptionsStrikeInfo | None,
        direction: str,
        ivr: float,
    ) -> OptionsScalpRecommendation:
        import time
        blockers: list[str] = []

        if direction == "call":
            short_premium = short_strike.call_bid
            short_delta = short_strike.call_delta
            short_theta = short_strike.call_theta
            spread = (short_strike.call_ask - short_strike.call_bid) / short_strike.call_ask if short_strike.call_ask > 0 else 1.0
        else:
            short_premium = short_strike.put_bid
            short_delta = abs(short_strike.put_delta)
            short_theta = short_strike.put_theta
            spread = (short_strike.put_ask - short_strike.put_bid) / short_strike.put_ask if short_strike.put_ask > 0 else 1.0

        if spread > 0.005:
            blockers.append(f"Spread too wide: {spread * 100:.2f}% > 0.5%")

        if ivr < 60:
            blockers.append(f"IVR {ivr:.0f} too low for selling premium (need > 60)")

        if short_strike.dte > 7:
            blockers.append(f"DTE {short_strike.dte} too long for scalping")

        net_premium = short_premium
        if long_strike:
            if direction == "call":
                net_premium -= long_strike.call_ask
            else:
                net_premium -= long_strike.put_ask

        target_premium = net_premium * 0.30
        stop_premium = net_premium * 2.0

        theta_per_hour = abs(short_theta) / 24.0

        return OptionsScalpRecommendation(
            timestamp=int(time.time() * 1000),
            action=f"SELL {direction.upper()} SPREAD",
            strike=short_strike.strike,
            dte=short_strike.dte,
            direction=direction,
            entry_premium=round(net_premium, 4),
            target_premium=round(target_premium, 4),
            stop_premium=round(stop_premium, 4),
            delta=round(short_delta, 4),
            gamma=0.0,
            theta_per_hour=round(theta_per_hour, 6),
            spread_pct=round(spread * 100, 3),
            reason=f"IVR {ivr:.0f} > 60 — sell premium; net credit {net_premium:.2f}",
            confidence="MEDIUM",
            blockers=blockers,
        )

    def should_exit_premium(
        self,
        entry_premium: float,
        current_premium: float,
        current_delta: float,
    ) -> tuple[bool, str]:
        if entry_premium <= 0:
            return False, ""

        pnl_pct = (current_premium - entry_premium) / entry_premium

        if pnl_pct >= 0.80:
            return True, f"Target hit: +{pnl_pct * 100:.0f}% premium gain"

        if pnl_pct >= 0.40 and current_delta < 0.20:
            return True, f"+{pnl_pct * 100:.0f}% gain + delta {current_delta:.2f} < 0.20"

        if current_delta < 0.20 and pnl_pct > 0:
            return True, f"Delta decayed to {current_delta:.2f} — exit"

        return False, ""

    def should_move_to_breakeven(
        self,
        entry_premium: float,
        current_premium: float,
    ) -> bool:
        if entry_premium <= 0:
            return False
        pnl_pct = (current_premium - entry_premium) / entry_premium
        return pnl_pct >= 0.20

    def get_summary(self) -> dict[str, Any]:
        ivr = self.compute_iv_rank()
        ivp = self.compute_iv_percentile()

        if ivr < 30:
            regime = "BUY OPTIONS — long gamma"
        elif ivr > 70:
            regime = "SELL PREMIUM — spreads only"
        elif 30 <= ivr <= 50:
            regime = "NO TRADE — IVR in no-edge zone"
        else:
            regime = "NEUTRAL — evaluate case by case"

        return {
            "current_iv": round(self._current_iv, 4),
            "iv_rank": round(ivr, 2),
            "iv_percentile": round(ivp, 2),
            "iv_regime": regime,
            "spot_price": round(self._spot_price, 2),
            "chain_strikes": len(self._chain),
        }
