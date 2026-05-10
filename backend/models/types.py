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
class OptionContract:
    symbol: str
    product_id: Optional[int]
    contract_type: str
    side: str
    strike_price: float
    expiry: Optional[str]
    expiry_timestamp: Optional[int]
    spot_price: Optional[float]
    mark_price: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    mid_price: Optional[float]
    spread_pct: Optional[float]
    bid_iv: Optional[float]
    ask_iv: Optional[float]
    volume: Optional[float]
    open_interest: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    rho: Optional[float]
    score: float
    qualified: bool
    reason: str


@dataclass
class OptionsContext:
    timestamp: int
    underlying: str
    momentum_score: float
    bullish_momentum_score: float
    bearish_momentum_score: float
    minimum_momentum_score: float
    momentum_state: str
    call_candidate: Optional[OptionContract]
    put_candidate: Optional[OptionContract]
    blockers: list[str] = field(default_factory=list)
    source_count: int = 0
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
    option_contract: Optional[OptionContract] = None
    momentum_score: Optional[float] = None
    options_score: Optional[float] = None
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
    """Tracks bid/ask imbalance patterns in the orderbook."""
    id: str
    timestamp: int
    price_level: float
    imbalance_ratio: float  # ask_size / bid_size; > 1 = more sellers, < 1 = more buyers
    side: str  # "buy" or "sell" dominant side
    strength: float  # 0-1, confidence score
    duration_ms: int
    status: str = "active"  # "active", "reversed", "filled"
    reversal_timestamp: Optional[int] = None
    reversal_price: Optional[float] = None


@dataclass
class SpreadDynamics:
    """Tracks bid-ask spread changes and anomalies."""
    id: str
    timestamp: int
    spread: float
    spread_pct: float
    spread_zscore: float  # Z-score relative to recent average
    bid: float
    ask: float
    bid_ask_midpoint: float
    status: str = "normal"  # "normal", "wide", "tight", "squeezed"
    anomaly_type: Optional[str] = None  # e.g., "compression", "expansion", "inversion"


@dataclass
class OrderbookDepthLevel:
    """Analyzes market depth at specific price tiers."""
    id: str
    timestamp: int
    price_level: float
    level_type: str  # "bid", "ask"
    estimated_size: float  # Estimated cumulative size within this tier
    order_count: int  # Approximate count of orders
    depth_tier: int  # 1-5: 1=immediate, 5=far
    saturation: float  # 0-1, how saturated this level is relative to recent average
    touched_count: int = 0
    last_touch: Optional[int] = None
    filled_count: int = 0


@dataclass
class OrderbookAccumulation:
    """Detects accumulation/distribution patterns from orderbook structure."""
    id: str
    timestamp: int
    price_range_low: float
    price_range_high: float
    side: str  # "accumulation" or "distribution"
    confidence: float  # 0-1
    volume_ratio: float  # Accumulation vs distribution volume
    pattern_duration_ms: int
    candle_touches: int
    status: str = "active"
    completion_timestamp: Optional[int] = None
    completion_price: Optional[float] = None


@dataclass
class OrderbookSnapshot:
    """Historical quote snapshot for analysis."""
    timestamp: int
    bid: float
    ask: float
    spread: float
    mid: float
    bid_qty: float = 0.0
    ask_qty: float = 0.0


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
    options_context: Optional[OptionsContext]
    btc_patterns: Optional[BtcPatternContext]
    update_type: str


def to_wire(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        # Serialize dataclasses field-by-field to avoid the extra deep-copy work from asdict.
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
