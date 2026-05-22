from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Optional


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = False


@dataclass
class Swing:
    timestamp: int
    price: float
    kind: str
    index: int


class StructureType(Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    BOS = "BOS"
    CHOCH = "CHoCH"


@dataclass
class StructureLabel:
    timestamp: int
    price: float
    kind: StructureType
    broken_swing_price: float
    direction: Optional[str] = None


@dataclass
class FVG:
    id: str
    top: float
    bottom: float
    timestamp: int
    direction: str
    is_filled: bool = False
    fill_timestamp: Optional[int] = None


@dataclass
class OrderBlock:
    id: str
    top: float
    bottom: float
    timestamp: int
    direction: str
    is_breaker: bool = False
    breaker_timestamp: Optional[int] = None


@dataclass
class LiquidityLevel:
    id: str
    price: float
    kind: str
    touch_count: int
    first_touch_timestamp: Optional[int] = None
    last_touch_timestamp: Optional[int] = None
    swept: bool = False
    sweep_timestamp: Optional[int] = None


@dataclass
class LiquidityEvent:
    id: str
    timestamp: int
    side: str
    swept_level: float
    sweep_price: float
    close_price: float
    sweep_depth: float
    displacement: float
    reclaimed: bool
    engineered_score: float
    reason: str


@dataclass
class MarketMetrics:
    timestamp: int
    atr14: float
    ema20: float
    ema50: float
    rsi14: float
    vwap: float
    vwap_distance_pct: float
    volume_zscore: float
    realized_volatility: float
    parkinson_volatility: float
    garman_klass_volatility: float
    displacement_ratio: float
    premium_discount: float
    equilibrium: float
    range_high: float
    range_low: float
    trend_score: float
    volatility_score: float
    institutional_bias: str
    bias_score: float
    expected_move: float
    expected_move_pct: float


@dataclass
class PriceProjection:
    timestamp: int
    direction: str
    probability: float
    expected_move: float
    expected_high: float
    expected_low: float
    invalidation: float
    score: float
    reason: str


@dataclass
class MarketQuote:
    symbol: str
    timestamp: int
    source: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last_trade: Optional[float] = None
    mark_price: Optional[float] = None
    spot_price: Optional[float] = None
    latency_ms: Optional[int] = None
    bid_qty: Optional[float] = None
    ask_qty: Optional[float] = None


@dataclass
class MarketRegime:
    timestamp: int
    phase: str
    confidence: float
    range_high: float
    range_low: float
    range_mid: float
    width_pct: float
    atr_compression: float
    efficiency_ratio: float
    volume_state: str
    bias: str
    reason: str


@dataclass
class FuturesContract:
    symbol: str
    product_id: int
    mark_price: Optional[float] = None
    mark_price_timestamp: Optional[int] = None
    funding_rate: float = 0.0
    funding_rate_timestamp: Optional[int] = None
    next_funding_timestamp: Optional[int] = None
    open_interest: float = 0.0
    open_interest_change_pct: float = 0.0
    volume_24h: float = 0.0


@dataclass
class FuturesContext:
    timestamp: int
    contract: Optional[FuturesContract] = None
    funding_rate: float = 0.0
    funding_annualized: float = 0.0
    funding_contrarian_bias: str = "neutral"
    is_funding_extreme: bool = False
    oi_value: float = 0.0
    oi_change_pct: float = 0.0
    oi_trend: str = "neutral"
    oi_momentum_confirmation: bool = False
    liquidation_clusters: list[dict] = field(default_factory=list)
    estimated_funding_pnl_pct: float = 0.0
    blockers: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SentimentHeadline:
    title: str
    source: str
    url: str
    published_at: Optional[int]
    score: float


@dataclass
class SentimentSnapshot:
    label: str
    score: float
    confidence: float
    source_count: int
    updated_at: Optional[int]
    headlines: list[SentimentHeadline] = field(default_factory=list)
    provider: str = "local_keyword"
    model: Optional[str] = None
    summary: str = ""
    drivers: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class AiIctDecision:
    timestamp: int
    timeframe: str
    provider: str
    model: Optional[str]
    direction: str
    grade: str
    readiness: str
    confidence: float
    setup_score: float
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    invalidation: Optional[float]
    primary_signal_id: Optional[str]
    summary: str
    futures_score: Optional[float] = None
    futures_funding_bias: Optional[str] = None
    confirmations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    calculations: list[str] = field(default_factory=list)
    guarantee: str = "No price direction is guaranteed; this is a probabilistic confluence model."
    updated_at: Optional[int] = None
    error: Optional[str] = None


@dataclass
class BtcPattern:
    id: str
    timestamp: int
    name: str
    direction: str
    confidence: float
    score: float
    description: str
    candle_count: int
    completed: bool = False
    completion_timestamp: Optional[int] = None
    completion_price: Optional[float] = None


@dataclass
class BtcInvestorBehavior:
    id: str
    timestamp: int
    behavior_type: str
    side: str
    confidence: float
    intensity: float
    description: str
    price_level: float
    volume_ratio: float
    is_active: bool = True


@dataclass
class BtcPatternContext:
    timestamp: int
    killzone: Optional[str]
    session: str
    weekday: int
    hour: int
    is_weekend: bool
    halving_phase: str
    volatility_regime: str
    fractal_clusters: list[str]
    patterns: list[BtcPattern] = field(default_factory=list)
    investor_behaviors: list[BtcInvestorBehavior] = field(default_factory=list)
    bullish_pattern_score: float = 0.0
    bearish_pattern_score: float = 0.0
    pattern_signal: str = "neutral"


@dataclass
class TradeSignal:
    id: str
    timestamp: int
    side: str
    entry: float
    stop_loss: float
    exit_price: float
    risk_reward: float
    confidence: float
    reason: str
    status: str = "open"
    exit_timestamp: Optional[int] = None
    institutional_score: float = 0.0
    liquidity_score: float = 0.0
    bias_score: float = 0.0
    expected_move: float = 0.0
    win_probability: float = 0.0
    kelly_fraction: float = 0.0
    suggested_risk_fraction: float = 0.0
    cvar95_loss: float = 0.0
    risk_of_ruin: float = 1.0
    trailing_stop: Optional[float] = None
    trailing_mode: str = "atr_chandelier"
    model: str = "institutional-v2"


@dataclass
class OrderbookImbalance:
    id: str
    timestamp: int
    price_level: float
    imbalance_ratio: float
    side: str
    strength: float
    duration_ms: int
    status: str = "active"
    reversal_timestamp: Optional[int] = None
    reversal_price: Optional[float] = None


@dataclass
class SpreadDynamics:
    id: str
    timestamp: int
    spread: float
    spread_pct: float
    spread_zscore: float
    bid: float
    ask: float
    bid_ask_midpoint: float
    status: str = "normal"
    anomaly_type: Optional[str] = None


@dataclass
class OrderbookDepthLevel:
    id: str
    timestamp: int
    price_level: float
    level_type: str
    estimated_size: float
    order_count: int
    depth_tier: int
    saturation: float
    touched_count: int = 0
    last_touch: Optional[int] = None
    filled_count: int = 0


@dataclass
class OrderbookAccumulation:
    id: str
    timestamp: int
    price_range_low: float
    price_range_high: float
    side: str
    confidence: float
    volume_ratio: float
    pattern_duration_ms: int
    candle_touches: int
    status: str = "active"
    completion_timestamp: Optional[int] = None
    completion_price: Optional[float] = None


@dataclass
class OrderbookSnapshot:
    timestamp: int
    bid: float
    ask: float
    spread: float
    mid: float
    bid_qty: float = 0.0
    ask_qty: float = 0.0


@dataclass
class ScalpOrderFlow:
    timestamp: int
    delta: float = 0.0
    cvd: float = 0.0
    cvd_slope: float = 0.0
    volume_delta_ratio: float = 0.0
    absorption_ratio: float = 0.0
    aggressive_buy_volume: float = 0.0
    aggressive_sell_volume: float = 0.0
    footprint_imbalance: float = 0.0


@dataclass
class ScalpFunding:
    timestamp: int
    current_rate: float = 0.0
    projected_8h: float = 0.0
    annualized_rate: float = 0.0
    next_reset_ms: int = 0
    is_extreme: bool = False
    contrarian_bias: str = "neutral"


@dataclass
class ScalpOpenInterest:
    timestamp: int
    current_oi: float = 0.0
    oi_change_pct: float = 0.0
    oi_delta: float = 0.0
    oi_trend: str = "neutral"
    momentum_confirmation: bool = False


@dataclass
class ScalpLiquidationLevel:
    price: float
    size: float
    side: str
    distance_pct: float
    cluster_strength: float


@dataclass
class ScalpVWAP:
    timestamp: int
    vwap: float = 0.0
    upper_band_1sd: float = 0.0
    lower_band_1sd: float = 0.0
    upper_band_2sd: float = 0.0
    lower_band_2sd: float = 0.0
    price_deviation_pct: float = 0.0
    is_compressed: bool = False


@dataclass
class ScalpVolumeProfile:
    timestamp: int
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    value_area_width_pct: float = 0.0


@dataclass
class ScalpFundingRate:
    timestamp: int
    current_rate: float = 0.0
    annualized: float = 0.0
    funding_apr: float = 0.0
    predicted_8h: float = 0.0
    time_to_next: int = 0
    is_extreme: bool = False
    bias: str = "neutral"


@dataclass
class ScalpLiquiditySweep:
    timestamp: int
    level: float
    side: str
    sweep_type: str
    reclaimed: bool
    strength: float
    entry_trigger: bool = False


@dataclass
class ScalpSignal:
    id: str
    timestamp: int
    signal_type: str
    entry_zone_low: float
    entry_zone_high: float
    sl_level: float
    target_1: float
    target_2: float
    leverage: int = 0
    reason: str = ""
    score: float = 0.0
    risk_reward: float = 0.0
    confidence: str = "MEDIUM"
    time_limit_ms: int = 0
    max_hold_minutes: int = 15
    status: str = "active"
    entry_triggered: bool = False
    partial_exit_pct: float = 0.0
    funding_impact_pct: float = 0.0


@dataclass
class ScalpWickRejection:
    """Long-wick rejection analysis for the last N candles.
    A long upper wick means price was rejected at the high → bearish signal.
    A long lower wick means price was rejected at the low → bullish signal.
    """
    active_upper_wick_candles: int = 0
    active_lower_wick_candles: int = 0
    max_upper_wick_ratio: float = 0.0
    max_lower_wick_ratio: float = 0.0
    avg_upper_wick_ratio: float = 0.0
    avg_lower_wick_ratio: float = 0.0
    bearish_rejection_active: bool = False
    bullish_rejection_active: bool = False
    rejection_strength: float = 0.0  # -1 (bearish) to +1 (bullish)
    description: str = ""


@dataclass
class ScalpContext:
    """Complete scalping context - futures only."""
    timestamp: int
    order_flow: Optional[ScalpOrderFlow] = None
    funding: Optional[ScalpFunding] = None
    funding_rate: Optional[ScalpFundingRate] = None
    open_interest: Optional[ScalpOpenInterest] = None
    liquidation_levels: list[ScalpLiquidationLevel] = field(default_factory=list)
    vwap: Optional[ScalpVWAP] = None
    volume_profile: Optional[ScalpVolumeProfile] = None
    liquidity_sweeps: list[ScalpLiquiditySweep] = field(default_factory=list)
    signals: list[ScalpSignal] = field(default_factory=list)
    trade_blocked_reasons: list[str] = field(default_factory=list)
    rsi_3: float = 50.0
    spot_volume_ok: bool = True
    macro_event_block: bool = False
    futures_leverage: int = 10
    estimated_funding_cost_8h: float = 0.0
    wick_rejection: Optional[ScalpWickRejection] = None
    
    # AI Brain properties
    ai_brain_active: bool = False
    ai_intelligence: Optional[dict] = None


@dataclass
class ChartUpdate:
    candle: Candle
    swings: list[Swing]
    structure: list[StructureLabel]
    fvgs: list[FVG]
    order_blocks: list[OrderBlock]
    liquidity: list[LiquidityLevel]
    liquidity_events: list[LiquidityEvent]
    signals: list[TradeSignal]
    metrics: Optional[MarketMetrics]
    projection: Optional[PriceProjection]
    regime: Optional[MarketRegime]
    futures_context: Optional[FuturesContext]
    btc_patterns: Optional[BtcPatternContext]
    update_type: str


def to_wire(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: to_wire(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, list):
        return [to_wire(item) for item in value]
    if isinstance(value, tuple):
        return [to_wire(item) for item in value]
    if isinstance(value, set):
        return [to_wire(item) for item in value]
    if isinstance(value, dict):
        return {key: to_wire(item) for key, item in value.items()}
    return value
