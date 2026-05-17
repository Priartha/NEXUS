from __future__ import annotations

from datetime import datetime, timezone
import math
import re
import time
from typing import Any

from backend.models.types import OptionContract, OptionsContext


_OPTION_SYMBOL_RE = re.compile(r"^(?P<kind>[CP])-(?P<underlying>[A-Z]+)-(?P<strike>\d+(?:\.\d+)?)-(?P<expiry>\d{6})$")


def build_options_context(
    payload: dict[str, Any],
    option_tickers: list[dict[str, Any]],
    underlying: str,
    min_momentum_score: float = 0.40,
    max_spread_pct: float = 0.18,
    min_delta_abs: float = 0.35,
    max_delta_abs: float = 0.75,
    max_moneyness_pct: float = 0.08,
    source_error: str | None = None,
) -> OptionsContext:
    metrics = _dict(payload.get("metrics"))
    projection = _dict(payload.get("projection"))
    regime = _dict(payload.get("regime"))
    candle = _dict(payload.get("candle"))
    now_ms = int(time.time() * 1000)

    bullish_momentum = _momentum_score("bullish", metrics, projection, regime, candle)
    bearish_momentum = _momentum_score("bearish", metrics, projection, regime, candle)
    momentum_score = max(bullish_momentum, bearish_momentum)
    momentum_state = "high" if momentum_score >= min_momentum_score else "low"

    call_candidate = _select_contract(
        tickers=option_tickers,
        underlying=underlying,
        side="call",
        max_spread_pct=max_spread_pct,
        min_delta_abs=min_delta_abs,
        max_delta_abs=max_delta_abs,
        max_moneyness_pct=max_moneyness_pct,
    )
    put_candidate = _select_contract(
        tickers=option_tickers,
        underlying=underlying,
        side="put",
        max_spread_pct=max_spread_pct,
        min_delta_abs=min_delta_abs,
        max_delta_abs=max_delta_abs,
        max_moneyness_pct=max_moneyness_pct,
    )

    blockers: list[str] = []
    if momentum_score < min_momentum_score:
        blockers.append(
            f"Options momentum {momentum_score:.0%} is below options threshold {min_momentum_score:.0%}"
        )
    if not call_candidate:
        blockers.append("No liquid BTC call contract passed Greek and spread filters")
    if not put_candidate:
        blockers.append("No liquid BTC put contract passed Greek and spread filters")
    if source_error:
        blockers.append(f"Delta options chain unavailable: {source_error}")

    return OptionsContext(
        timestamp=int(candle.get("timestamp") or metrics.get("timestamp") or now_ms),
        underlying=underlying,
        momentum_score=round(momentum_score, 3),
        bullish_momentum_score=round(bullish_momentum, 3),
        bearish_momentum_score=round(bearish_momentum, 3),
        minimum_momentum_score=round(min_momentum_score, 3),
        momentum_state=momentum_state,
        call_candidate=call_candidate,
        put_candidate=put_candidate,
        blockers=blockers[:6],
        source_count=len(option_tickers),
        error=source_error,
    )


def _select_contract(
    tickers: list[dict[str, Any]],
    underlying: str,
    side: str,
    max_spread_pct: float,
    min_delta_abs: float,
    max_delta_abs: float,
    max_moneyness_pct: float,
) -> OptionContract | None:
    contracts = [
        _parse_option_ticker(item, underlying, side, max_spread_pct, min_delta_abs, max_delta_abs, max_moneyness_pct)
        for item in tickers
    ]
    candidates = [contract for contract in contracts if contract is not None]
    if not candidates:
        return None
    qualified = [contract for contract in candidates if contract.qualified]
    return max(qualified or candidates, key=lambda contract: contract.score)


def _parse_option_ticker(
    ticker: dict[str, Any],
    underlying: str,
    side: str,
    max_spread_pct: float,
    min_delta_abs: float,
    max_delta_abs: float,
    max_moneyness_pct: float,
) -> OptionContract | None:
    symbol = str(ticker.get("symbol") or "")
    match = _OPTION_SYMBOL_RE.match(symbol)
    if not match or match.group("underlying") != underlying:
        return None

    expected_kind = "C" if side == "call" else "P"
    if match.group("kind") != expected_kind:
        return None

    contract_type = str(ticker.get("contract_type") or ticker.get("product_type") or "")
    if side == "call" and contract_type not in {"", "call_options"}:
        return None
    if side == "put" and contract_type not in {"", "put_options"}:
        return None

    strike = _as_float(ticker.get("strike_price"), _as_float(match.group("strike"), 0.0))
    spot = _as_float(ticker.get("spot_price"), 0.0)
    mark = _as_float(ticker.get("mark_price") or ticker.get("mark"), 0.0)
    quotes = _dict(ticker.get("quotes"))
    bid = _as_float(quotes.get("best_bid") or ticker.get("best_bid") or ticker.get("bid"), 0.0)
    ask = _as_float(quotes.get("best_ask") or ticker.get("best_ask") or ticker.get("ask"), 0.0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 and ask >= bid else mark
    if strike <= 0 or spot <= 0 or mid <= 0:
        return None

    spread_pct = ((ask - bid) / mid) if bid > 0 and ask > bid else None
    greeks = _dict(ticker.get("greeks"))
    delta = _optional_float(greeks.get("delta") or ticker.get("delta"))
    gamma = _optional_float(greeks.get("gamma") or ticker.get("gamma"))
    theta = _optional_float(greeks.get("theta") or ticker.get("theta"))
    vega = _optional_float(greeks.get("vega") or ticker.get("vega"))
    rho = _optional_float(greeks.get("rho") or ticker.get("rho"))

    delta_abs = abs(delta) if delta is not None else 0.0
    moneyness_pct = abs(strike - spot) / spot
    volume = _optional_float(ticker.get("volume"))
    open_interest = _optional_float(ticker.get("oi") or ticker.get("open_interest"))
    bid_iv = _optional_float(quotes.get("bid_iv") or ticker.get("bid_iv"))
    ask_iv = _optional_float(quotes.get("ask_iv") or ticker.get("ask_iv"))

    spread_score = 0.0 if spread_pct is None else _clamp(1 - (spread_pct / max_spread_pct), 0.0, 1.0)
    delta_score = _clamp(1 - (abs(delta_abs - 0.55) / 0.28), 0.0, 1.0)
    moneyness_score = _clamp(1 - (moneyness_pct / max_moneyness_pct), 0.0, 1.0)
    gamma_score = _clamp(abs(gamma or 0.0) * 2500, 0.0, 1.0)
    liquidity_score = _clamp(math.log10(max((volume or 0.0) + 1, 1.0)) / 4, 0.0, 1.0)
    oi_score = _clamp(math.log10(max((open_interest or 0.0) + 1, 1.0)) / 4, 0.0, 1.0)
    iv_score = 0.55 if bid_iv is not None or ask_iv is not None else 0.25
    score = (
        spread_score * 0.24
        + delta_score * 0.24
        + moneyness_score * 0.18
        + gamma_score * 0.13
        + liquidity_score * 0.09
        + oi_score * 0.07
        + iv_score * 0.05
    )

    blockers: list[str] = []
    if spread_pct is None or spread_pct > max_spread_pct:
        blockers.append("wide spread")
    if delta_abs < min_delta_abs or delta_abs > max_delta_abs:
        blockers.append("delta outside momentum band")
    if moneyness_pct > max_moneyness_pct:
        blockers.append("strike too far from spot")
    if bid <= 0 or ask <= 0:
        blockers.append("missing executable quote")
    expiry, expiry_timestamp = _parse_expiry(match.group("expiry"))
    if expiry_timestamp and expiry_timestamp < int(time.time() * 1000):
        blockers.append("expired contract")

    qualified = not blockers and score >= 0.55
    reason = (
        f"delta {delta_abs:.2f}, gamma {abs(gamma or 0.0):.6f}, "
        f"spread {(spread_pct or 0.0) * 100:.1f}%, moneyness {moneyness_pct * 100:.1f}%"
    )
    if blockers:
        reason = f"{reason}; blocked: {', '.join(blockers)}"

    return OptionContract(
        symbol=symbol,
        product_id=_optional_int(ticker.get("product_id") or ticker.get("id")),
        contract_type=contract_type or ("call_options" if side == "call" else "put_options"),
        side=side,
        strike_price=round(strike, 2),
        expiry=expiry,
        expiry_timestamp=expiry_timestamp,
        spot_price=_round_optional(spot),
        mark_price=_round_optional(mark),
        best_bid=_round_optional(bid),
        best_ask=_round_optional(ask),
        mid_price=_round_optional(mid),
        spread_pct=round(spread_pct, 4) if spread_pct is not None else None,
        bid_iv=bid_iv,
        ask_iv=ask_iv,
        volume=volume,
        open_interest=open_interest,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        rho=rho,
        score=round(score, 3),
        qualified=qualified,
        reason=reason,
    )


def _momentum_score(
    direction: str,
    metrics: dict[str, Any],
    projection: dict[str, Any],
    regime: dict[str, Any],
    candle: dict[str, Any],
) -> float:
    displacement = _as_float(metrics.get("displacement_ratio"), 0.0)
    volume_z = _as_float(metrics.get("volume_zscore"), 0.0)
    trend_score = _as_float(metrics.get("trend_score"), 0.0)
    bias_score = _as_float(metrics.get("bias_score"), 0.0)
    volatility_score = _as_float(metrics.get("volatility_score"), 0.0)
    projection_direction = str(projection.get("direction") or "neutral")
    projection_probability = _as_float(projection.get("probability"), 0.5)
    regime_phase = str(regime.get("phase") or "")
    open_price = _as_float(candle.get("open"), 0.0)
    close_price = _as_float(candle.get("close"), 0.0)
    body_direction = "bullish" if close_price >= open_price else "bearish"

    sign = 1 if direction == "bullish" else -1
    aligned_trend = max(trend_score * sign, 0.0)
    aligned_bias = max(bias_score * sign, 0.0)
    score = 0.0
    score += _clamp((displacement - 0.9) / 0.9, 0.0, 1.0) * 0.28
    score += _clamp(volume_z / 2.2, 0.0, 1.0) * 0.18
    score += _clamp(aligned_trend, 0.0, 1.0) * 0.2
    score += _clamp(aligned_bias, 0.0, 1.0) * 0.14
    score += _clamp(volatility_score, 0.0, 1.0) * 0.1

    if projection_direction == direction:
        score += _clamp((projection_probability - 0.5) / 0.35, 0.0, 1.0) * 0.07
    elif projection_direction in {"bullish", "bearish"}:
        score -= 0.07

    if body_direction == direction and displacement >= 1.05:
        score += 0.03
    if regime_phase in {"consolidation", "range_bound"}:
        score -= 0.08
    if regime_phase == "accumulation":
        score += 0.07 if direction == "bullish" else -0.08
    if regime_phase == "distribution":
        score += 0.07 if direction == "bearish" else -0.08

    return _clamp(score, 0.0, 1.0)


def _parse_expiry(raw: str) -> tuple[str | None, int | None]:
    try:
        expiry = datetime.strptime(raw, "%d%m%y").replace(tzinfo=timezone.utc)
        return expiry.date().isoformat(), int(expiry.timestamp() * 1000)
    except ValueError:
        return None, None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _round_optional(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return round(value, 2)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
