from dataclasses import dataclass

@dataclass(frozen=True)
class TechnicalIndicators:
    ATR_PERIOD = 14
    EMA_FAST = 20
    EMA_SLOW = 50
    RSI_PERIOD = 14
    VWAP_LOOKBACK = 20
    REGIME_LOOKBACK = 48
    SWING_WINDOW = 2

@dataclass(frozen=True)
class SentimentThresholds:
    BULLISH_THRESHOLD = 0.18
    BEARISH_THRESHOLD = -0.18
    CONFIDENCE_WEIGHT = 0.65
    RECENCY_WEIGHT_BASE = 0.45

@dataclass(frozen=True)
class LiquidityScoring:
    TOUCH_SCORE_CAP = 0.3
    TOUCH_SCORE_WEIGHT = 0.075
    DEPTH_SCORE_CAP = 0.24
    DEPTH_SCORE_WEIGHT = 0.16
    WICK_SCORE_CAP = 0.18
    DISPLACEMENT_SCORE_CAP = 0.16
    DISPLACEMENT_SCORE_WEIGHT = 0.08
    BASE_SCORE = 0.22
    MAX_SCORE = 0.95

@dataclass(frozen=True)
class AiIctThresholds:
    MIN_CONFIDENCE = 0.49
    HIGH_CONFIDENCE_MIN = 0.68
    MAX_CONFIDENCE = 0.95
    DEFAULT_RISK_REWARD = 3.0

@dataclass(frozen=True)
class MarketRegimeThresholds:
    TRENDING_THRESHOLD = 0.28
    RANGE_BOUND_THRESHOLD = 0.24
    CONSOLIDATION_THRESHOLD = 0.42
    ACCUMULATION_THRESHOLD = 0.92

@dataclass(frozen=True)
class RiskManagement:
    DEFAULT_STOP_LOSS_ATR_MULTIPLIER = 1.5
    DEFAULT_TARGET_RISK_REWARD = 3.0
    MAX_POSITION_SIZE_PCT = 0.02
