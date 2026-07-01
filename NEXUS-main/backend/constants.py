from dataclasses import dataclass

@dataclass(frozen=True)
class TechnicalIndicators:
    ATR_PERIOD: int = 14
    EMA_FAST: int = 20
    EMA_SLOW: int = 50
    RSI_PERIOD: int = 14
    VWAP_LOOKBACK: int = 20
    REGIME_LOOKBACK: int = 48
    SWING_WINDOW: int = 2

@dataclass(frozen=True)
class SentimentThresholds:
    BULLISH_THRESHOLD: float = 0.18
    BEARISH_THRESHOLD: float = -0.18
    CONFIDENCE_WEIGHT: float = 0.65
    RECENCY_WEIGHT_BASE: float = 0.45

@dataclass(frozen=True)
class LiquidityScoring:
    TOUCH_SCORE_CAP: float = 0.3
    TOUCH_SCORE_WEIGHT: float = 0.075
    DEPTH_SCORE_CAP: float = 0.24
    DEPTH_SCORE_WEIGHT: float = 0.16
    WICK_SCORE_CAP: float = 0.18
    DISPLACEMENT_SCORE_CAP: float = 0.16
    DISPLACEMENT_SCORE_WEIGHT: float = 0.08
    BASE_SCORE: float = 0.22
    MAX_SCORE: float = 0.95

@dataclass(frozen=True)
class AiIctThresholds:
    MIN_CONFIDENCE: float = 0.49
    HIGH_CONFIDENCE_MIN: float = 0.68
    MAX_CONFIDENCE: float = 0.95
    DEFAULT_RISK_REWARD: float = 3.0

@dataclass(frozen=True)
class MarketRegimeThresholds:
    TRENDING_THRESHOLD: float = 0.28
    RANGE_BOUND_THRESHOLD: float = 0.24
    CONSOLIDATION_THRESHOLD: float = 0.42
    ACCUMULATION_THRESHOLD: float = 0.92

@dataclass(frozen=True)
class RiskManagement:
    DEFAULT_STOP_LOSS_ATR_MULTIPLIER: float = 1.5
    DEFAULT_TARGET_RISK_REWARD: float = 3.0
    MAX_POSITION_SIZE_PCT: float = 0.02
