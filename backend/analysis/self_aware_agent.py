"""
NEXUS Self-Aware Trading Agent - Industry Grade AI Brain

A complete autonomous trading intelligence that:
- Uses only price action (OHLCV) - no external dependencies
- Has persistent memory of all market behavior
- Learns from every trade outcome
- Makes decisions based on pattern recognition
- Adapts to BTC's unique characteristics
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from backend.config import settings
from backend.models.types import Candle


# ──────────────────────────────────────────────────────────────
# MARKET MEMORY - Persistent Knowledge Base
# ──────────────────────────────────────────────────────────────

@dataclass
class MarketPattern:
    """A learned market pattern with outcome."""
    pattern_id: str
    pattern_type: str  # 'bullish_engulfing', 'double_bottom', 'trend_continuation', etc.
    features: dict  # Numerical representation of the pattern
    context: dict  # Market conditions when pattern formed
    outcome: float  # % profit or loss
    confidence: float  # How reliable this pattern is
    sample_count: int  # How many times we've seen this
    timestamp: int
    
    def update_outcome(self, new_outcome: float) -> None:
        """Bayesian update of pattern reliability."""
        self.sample_count += 1
        # Running average with decay for recent samples
        decay = 0.9
        self.outcome = (self.outcome * decay * (self.sample_count - 1) + new_outcome) / self.sample_count
        # Update confidence based on sample count
        self.confidence = min(1.0, self.sample_count / 50)


@dataclass
class TradeMemory:
    """Complete memory of a trade decision."""
    trade_id: str
    timestamp: int
    entry_price: float
    exit_price: float | None
    side: str  # 'long' or 'short'
    
    # Market context at entry
    price_level: float
    volatility: float
    volume_ratio: float
    trend_strength: float
    regime: str
    
    # Pattern that triggered entry
    pattern_features: dict
    pattern_type: str
    
    # Reasoning
    entry_reason: str
    exit_reason: str | None
    
    # Outcome
    pnl_pct: float | None = None
    won: bool | None = None
    
    # Learning
    was_correct: bool | None = None
    lessons: list[str] = field(default_factory=list)


class MarketMemory:
    """Persistent memory that learns from market behavior."""
    
    def __init__(self, db_path: str = "data/market_memory.db"):
        self.patterns: dict[str, MarketPattern] = {}
        self.trade_history: list[TradeMemory] = []
        self.price_levels: deque = deque(maxlen=10000)
        self.volume_profile: deque = deque(maxlen=5000)
        self.regime_history: deque = deque(maxlen=1000)
        
        # Statistics
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        
        # BTC-specific knowledge
        self.cycles_learned: dict[int, dict] = {}  # Hour -> behavior patterns
        self.day_of_week_behavior: dict[int, dict] = {}  # 0-6 -> behavior
        self.volatility_states: dict[str, float] = {}
        
    def add_price_snapshot(self, candle: Candle) -> None:
        """Add price data to memory."""
        self.price_levels.append({
            'timestamp': candle.timestamp,
            'open': candle.open,
            'high': candle.high,
            'low': candle.low,
            'close': candle.close,
            'volume': candle.volume,
        })
        
        # Learn hourly patterns
        hour = datetime.fromtimestamp(candle.timestamp / 1000, tz=timezone.utc).hour
        if hour not in self.cycles_learned:
            self.cycles_learned[hour] = {'bullish': 0, 'bearish': 0, 'range': 0, 'samples': 0}
        
        change_pct = (candle.close - candle.open) / candle.open * 100
        if change_pct > 0.5:
            self.cycles_learned[hour]['bullish'] += 1
        elif change_pct < -0.5:
            self.cycles_learned[hour]['bearish'] += 1
        else:
            self.cycles_learned[hour]['range'] += 1
        self.cycles_learned[hour]['samples'] += 1
        
        # Learn day of week
        dow = datetime.fromtimestamp(candle.timestamp / 1000, tz=timezone.utc).weekday()
        if dow not in self.day_of_week_behavior:
            self.day_of_week_behavior[dow] = {'avg_range': 0, 'avg_volume': 0, 'samples': 0}
        
        range_pct = (candle.high - candle.low) / candle.close * 100
        self.day_of_week_behavior[dow]['avg_range'] = (
            (self.day_of_week_behavior[dow]['avg_range'] * self.day_of_week_behavior[dow]['samples'] + range_pct) 
            / (self.day_of_week_behavior[dow]['samples'] + 1)
        )
        self.day_of_week_behavior[dow]['samples'] += 1
        
    def add_trade(self, trade: TradeMemory) -> None:
        """Add trade to memory and learn."""
        self.trade_history.append(trade)
        self.total_trades += 1
        
        if trade.pnl_pct is not None:
            self.total_pnl += trade.pnl_pct
            if trade.pnl_pct > 0:
                self.winning_trades += 1
        
        # Update pattern knowledge
        pattern_key = f"{trade.pattern_type}_{hash(str(trade.pattern_features))}"
        if pattern_key in self.patterns:
            self.patterns[pattern_key].update_outcome(trade.pnl_pct or 0)
        else:
            self.patterns[pattern_key] = MarketPattern(
                pattern_id=pattern_key,
                pattern_type=trade.pattern_type,
                features=trade.pattern_features,
                context={'regime': trade.regime},
                outcome=trade.pnl_pct or 0,
                confidence=0.5,
                sample_count=1,
                timestamp=trade.timestamp
            )
    
    def get_pattern_reliability(self, pattern_type: str, features: dict) -> float:
        """Get reliability score for a pattern."""
        matching_patterns = [
            p for p in self.patterns.values()
            if p.pattern_type == pattern_type
        ]
        
        if not matching_patterns:
            return 0.5  # Neutral if no history
        
        # Weighted average based on feature similarity
        scores = []
        for p in matching_patterns:
            similarity = self._calculate_feature_similarity(features, p.features)
            if similarity > 0.5:
                weighted_score = p.outcome * p.confidence * similarity
                scores.append(weighted_score)
        
        return sum(scores) / len(scores) if scores else 0.5
    
    def _calculate_feature_similarity(self, features1: dict, features2: dict) -> float:
        """Calculate similarity between two feature sets."""
        if not features1 or not features2:
            return 0.5
        
        similarities = []
        for key in features1:
            if key in features2:
                v1, v2 = features1[key], features2[key]
                if max(v1, v2) != 0:
                    similarity = 1 - abs(v1 - v2) / max(abs(v1), abs(v2))
                    similarities.append(similarity)
        
        return sum(similarities) / len(similarities) if similarities else 0.5
    
    def get_market_intelligence(self, hour: int, regime: str) -> dict:
        """Get intelligent insights for current market conditions."""
        intelligence = {
            'hour_bias': 'neutral',
            'confidence': 0.5,
            'regime_preference': regime,
        }
        
        # Get hourly behavior
        if hour in self.cycles_learned:
            h = self.cycles_learned[hour]
            total = h['bullish'] + h['bearish'] + h['range']
            if total > 10:
                bullish_pct = h['bullish'] / total
                bearish_pct = h['bearish'] / total
                
                if bullish_pct > 0.4:
                    intelligence['hour_bias'] = 'bullish'
                    intelligence['confidence'] = min(0.9, bullish_pct)
                elif bearish_pct > 0.4:
                    intelligence['hour_bias'] = 'bearish'
                    intelligence['confidence'] = min(0.9, bearish_pct)
        
        # Get pattern success rate
        pattern_success = self._get_pattern_success_rate(regime)
        intelligence['pattern_reliability'] = pattern_success
        
        return intelligence
    
    def _get_pattern_success_rate(self, regime: str) -> float:
        """Calculate pattern success rate for a regime."""
        regime_trades = [t for t in self.trade_history if t.regime == regime]
        if len(regime_trades) < 5:
            return 0.5
        
        wins = sum(1 for t in regime_trades if t.won)
        return wins / len(regime_trades)
    
    def get_statistics(self) -> dict:
        """Get trading statistics."""
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        avg_pnl = self.total_pnl / self.total_trades if self.total_trades > 0 else 0
        
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': win_rate,
            'total_pnl': self.total_pnl,
            'avg_pnl_per_trade': avg_pnl,
            'patterns_learned': len(self.patterns),
            'market_hours_learned': len(self.cycles_learned),
        }


# ──────────────────────────────────────────────────────────────
# FEATURE EXTRACTOR - Extract Trading Features from Price Action
# ──────────────────────────────────────────────────────────────

class FeatureExtractor:
    """Extract meaningful features from price data."""
    
    def __init__(self):
        self.price_cache = deque(maxlen=500)
        
    def extract_features(self, candles: list[Candle]) -> dict:
        """Extract comprehensive features from candles."""
        if len(candles) < 20:
            return {}
        
        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])
        volumes = np.array([c.volume for c in candles])
        
        # Price features
        returns = np.diff(closes) / closes[:-1]
        
        # Trend features
        ema_fast = self._ema(closes, 8)
        ema_medium = self._ema(closes, 21)
        ema_slow = self._ema(closes, 55)
        
        # Volatility features
        atr = self._atr(highs, lows, closes, 14)
        atr_pct = atr / closes[-1] if closes[-1] > 0 else 0
        
        # Volume features
        vol_mean = np.mean(volumes[-20:])
        vol_std = np.std(volumes[-20:])
        volume_ratio = volumes[-1] / vol_mean if vol_mean > 0 else 1
        
        # Momentum features
        rsi_3 = self._rsi(closes, 3)
        rsi_14 = self._rsi(closes, 14)
        macd = self._macd(closes)
        
        # Pattern features
        candle_strength = (closes[-1] - lows[-1]) / (highs[-1] - lows[-1]) if (highs[-1] - lows[-1]) > 0 else 0.5
        body_size = abs(closes[-1] - candles[-1].open) / (highs[-1] - lows[-1]) if (highs[-1] - lows[-1]) > 0 else 0
        
        # Support/Resistance proximity
        swing_highs = self._find_swing_highs(highs, 10)
        swing_lows = self._find_swing_lows(lows, 10)
        
        current_price = closes[-1]
        nearest_resistance = min(swing_highs) if swing_highs else current_price * 1.02
        nearest_support = max(swing_lows) if swing_lows else current_price * 0.98
        
        # Structure features
        hh_count = len([h for h in swing_highs if h > np.mean(swing_highs)]) if len(swing_highs) > 1 else 0
        hl_count = len([l for l in swing_lows if l < np.mean(swing_lows)]) if len(swing_lows) > 1 else 0
        
        return {
            # Trend
            'trend_direction': 1 if ema_fast > ema_medium else -1,
            'trend_strength': abs(ema_fast - ema_slow) / current_price if current_price > 0 else 0,
            'ema_alignment': self._ema_alignment(ema_fast, ema_medium, ema_slow),
            
            # Momentum
            'rsi_3': rsi_3,
            'rsi_14': rsi_14,
            'macd': macd,
            'momentum': np.mean(returns[-5:]) * 100 if len(returns) >= 5 else 0,
            
            # Volatility
            'atr_pct': atr_pct,
            'volatility_state': 'high' if atr_pct > 0.03 else 'low' if atr_pct < 0.015 else 'normal',
            
            # Volume
            'volume_ratio': volume_ratio,
            'volume_trend': np.mean(volumes[-5:]) / np.mean(volumes[-20:-5]) if len(volumes) >= 20 else 1,
            
            # Structure
            'candle_strength': candle_strength,
            'body_size': body_size,
            'resistance_distance': (nearest_resistance - current_price) / current_price if current_price > 0 else 0,
            'support_distance': (current_price - nearest_support) / current_price if current_price > 0 else 0,
            
            # Market structure
            'higher_highs': hh_count,
            'higher_lows': hl_count,
            
            # Price action
            'recent_return_1': returns[-1] * 100 if len(returns) >= 1 else 0,
            'recent_return_3': np.mean(returns[-3:]) * 100 if len(returns) >= 3 else 0,
            'recent_return_10': np.mean(returns[-10:]) * 100 if len(returns) >= 10 else 0,
            
            # Range position
            'range_position': self._calculate_range_position(highs[-20:], lows[-20:], closes[-1]),
        }
    
    def _ema(self, data: np.ndarray, period: int) -> float:
        if len(data) < period:
            return data[-1] if len(data) > 0 else 0
        k = 2 / (period + 1)
        ema = data[0]
        for v in data[1:]:
            ema = v * k + ema * (1 - k)
        return ema
    
    def _atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
        if len(closes) < period + 1:
            return 0
        ranges = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            ranges.append(tr)
        return np.mean(ranges[-period:])
    
    def _rsi(self, data: np.ndarray, period: int) -> float:
        if len(data) < period + 1:
            return 50
        deltas = np.diff(data)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _macd(self, data: np.ndarray, fast: int = 12, slow: int = 26) -> float:
        if len(data) < slow:
            return 0
        ema_fast = self._ema(data, fast)
        ema_slow = self._ema(data, slow)
        return ema_fast - ema_slow
    
    def _ema_alignment(self, fast: float, medium: float, slow: float) -> int:
        """Returns: 1 = bullish alignment, -1 = bearish, 0 = mixed."""
        if fast > medium > slow:
            return 1
        elif fast < medium < slow:
            return -1
        return 0
    
    def _find_swing_highs(self, highs: np.ndarray, lookback: int) -> list:
        """Find swing high points."""
        swing_highs = []
        for i in range(lookback, len(highs) - lookback):
            if highs[i] == max(highs[i-lookback:i+lookback+1]):
                swing_highs.append(highs[i])
        return swing_highs
    
    def _find_swing_lows(self, lows: np.ndarray, lookback: int) -> list:
        """Find swing low points."""
        swing_lows = []
        for i in range(lookback, len(lows) - lookback):
            if lows[i] == min(lows[i-lookback:i+lookback+1]):
                swing_lows.append(lows[i])
        return swing_lows
    
    def _calculate_range_position(self, highs: np.ndarray, lows: np.ndarray, current: float) -> float:
        """Calculate where current price is within recent range (0-1)."""
        if len(highs) == 0 or len(lows) == 0:
            return 0.5
        range_high = max(highs)
        range_low = min(lows)
        range_size = range_high - range_low
        if range_size == 0:
            return 0.5
        return (current - range_low) / range_size


# ──────────────────────────────────────────────────────────────
# SELF-AWARE TRADING AGENT - The Brain
# ──────────────────────────────────────────────────────────────

class SelfAwareTradingAgent:
    """
    Industry-grade autonomous trading agent with memory.
    Makes decisions purely based on price action analysis.
    """
    
    def __init__(self):
        self.memory = MarketMemory()
        self.feature_extractor = FeatureExtractor()
        
        # Signal state
        self.last_signal_time = 0
        self.signal_cooldown_ms = 3 * 60 * 1000  # 3 minutes
        
        # Decision thresholds
        self.min_confidence = 0.55
        self.min_risk_reward = 1.5
        
        # Learning state
        self.total_decisions = 0
        self.correct_decisions = 0
        
    def analyze_market(self, candles: list[Candle]) -> dict:
        """Primary analysis method - extracts all intelligence from price."""
        if len(candles) < 50:
            return {'signal': 'WAIT', 'reason': 'Insufficient data', 'confidence': 0}
        
        # Extract features
        features = self.feature_extractor.extract_features(candles)
        
        if not features:
            return {'signal': 'WAIT', 'reason': 'Feature extraction failed', 'confidence': 0}
        
        # Update memory with new price data
        for c in candles[-5:]:
            self.memory.add_price_snapshot(c)
        
        # Get market intelligence
        now = datetime.now(timezone.utc)
        hour = now.hour
        regime = self._detect_regime(candles)
        
        market_intel = self.memory.get_market_intelligence(hour, regime)
        
        # Calculate signal scores
        long_score = self._calculate_long_score(features, market_intel, regime)
        short_score = self._calculate_short_score(features, market_intel, regime)
        
        # Determine signal
        edge = abs(long_score - short_score)
        
        if edge < 0.1:
            return {
                'signal': 'WAIT',
                'reason': 'No clear directional edge',
                'confidence': 0.5,
                'long_score': long_score,
                'short_score': short_score,
                'features': features,
                'market_intel': market_intel,
            }
        
        winning_side = 'LONG' if long_score > short_score else 'SHORT'
        winning_score = max(long_score, short_score)
        
        if winning_score < self.min_confidence:
            return {
                'signal': 'WAIT',
                'reason': f'Confidence {winning_score:.2f} below threshold {self.min_confidence}',
                'confidence': winning_score,
                'long_score': long_score,
                'short_score': short_score,
                'features': features,
            }
        
        # Calculate entry parameters
        current_price = candles[-1].close
        atr = features.get('atr_pct', 0.02) * current_price
        
        if winning_side == 'LONG':
            entry = current_price
            stop_loss = current_price - atr * 2.5
            target = current_price + atr * 5  # 2:1 R:R
            risk_reward = 2.0
        else:
            entry = current_price
            stop_loss = current_price + atr * 2.5
            target = current_price - atr * 5
            risk_reward = 2.0
        
        # Generate signal
        signal = {
            'signal': winning_side,
            'confidence': winning_score,
            'entry': entry,
            'stop_loss': stop_loss,
            'target': target,
            'risk_reward': risk_reward,
            'reason': self._build_reason(features, market_intel, regime),
            'pattern_type': self._identify_pattern(features),
            'features': features,
            'market_intel': market_intel,
            'regime': regime,
        }
        
        return signal
    
    def _detect_regime(self, candles: list[Candle]) -> str:
        """Detect current market regime from price action."""
        if len(candles) < 50:
            return 'unknown'
        
        closes = np.array([c.close for c in candles])
        
        # Calculate trend
        ema_20 = self.feature_extractor._ema(closes, 20)
        ema_50 = self.feature_extractor._ema(closes, 50)
        
        # Calculate volatility safely - handle array edge cases
        try:
            if len(closes) >= 22:
                diff_arr = np.diff(closes[-21:])
                prev_arr = closes[-21:-1]
                if len(diff_arr) > 0 and len(prev_arr) > 0:
                    recent_returns = diff_arr / prev_arr
                    volatility = float(np.std(recent_returns))
                else:
                    volatility = 0.01
            else:
                volatility = 0.01
        except Exception:
            volatility = 0.01
        
        # Trend detection
        if ema_20 > ema_50 * 1.01:
            if volatility > 0.02:
                return 'trending_volatile'
            return 'trending'
        elif ema_20 < ema_50 * 0.99:
            if volatility > 0.02:
                return 'trending_volatile'
            return 'trending'
        else:
            if volatility < 0.01:
                return 'consolidation'
            return 'range_bound'
    
    def _calculate_long_score(self, features: dict, market_intel: dict, regime: str) -> float:
        """Calculate probability of successful long trade."""
        score = 0.5  # Base probability
        
        # Trend alignment
        if features.get('trend_direction') > 0:
            score += 0.15
        if features.get('ema_alignment') > 0:
            score += 0.10
        
        # Momentum
        if features.get('rsi_3') < 30:
            score += 0.15  # Oversold bounce
        if features.get('rsi_3') < 50 and features.get('momentum') > 0:
            score += 0.10
        
        # RSI confirmation
        if 30 < features.get('rsi_14', 50) < 60:
            score += 0.05
        
        # Volume confirmation
        if features.get('volume_ratio', 1) > 1.2:
            score += 0.10
        
        # Range position (buying near support)
        if features.get('support_distance', 0) < 0.02:
            score += 0.10
        
        # Market intelligence
        if market_intel.get('hour_bias') == 'bullish':
            score += 0.10 * market_intel.get('confidence', 0.5)
        
        # Pattern reliability from memory
        pattern_type = self._identify_pattern(features)
        pattern_score = self.memory.get_pattern_reliability(pattern_type, features)
        score += pattern_score * 0.15
        
        # Regime modifier
        if regime in ['trending', 'trending_volatile']:
            score += 0.05
        elif regime == 'consolidation':
            score -= 0.05
        
        return min(0.95, max(0.1, score))
    
    def _calculate_short_score(self, features: dict, market_intel: dict, regime: str) -> float:
        """Calculate probability of successful short trade."""
        score = 0.5  # Base probability
        
        # Trend alignment (opposite of long)
        if features.get('trend_direction') < 0:
            score += 0.15
        if features.get('ema_alignment') < 0:
            score += 0.10
        
        # Momentum
        if features.get('rsi_3') > 70:
            score += 0.15  # Overbought rejection
        if features.get('rsi_3') > 50 and features.get('momentum') < 0:
            score += 0.10
        
        # RSI confirmation
        if 40 < features.get('rsi_14', 50) < 70:
            score += 0.05
        
        # Volume confirmation
        if features.get('volume_ratio', 1) > 1.2:
            score += 0.10
        
        # Range position (selling near resistance)
        if features.get('resistance_distance', 0) < 0.02:
            score += 0.10
        
        # Market intelligence
        if market_intel.get('hour_bias') == 'bearish':
            score += 0.10 * market_intel.get('confidence', 0.5)
        
        # Pattern reliability from memory
        pattern_type = self._identify_pattern(features)
        pattern_score = self.memory.get_pattern_reliability(pattern_type, features)
        score += pattern_score * 0.15
        
        # Regime modifier
        if regime in ['trending', 'trending_volatile']:
            score += 0.05
        elif regime == 'consolidation':
            score -= 0.05
        
        return min(0.95, max(0.1, score))
    
    def _identify_pattern(self, features: dict) -> str:
        """Identify current price pattern."""
        rsi = features.get('rsi_3', 50)
        candle_strength = features.get('candle_strength', 0.5)
        ema_align = features.get('ema_alignment', 0)
        momentum = features.get('momentum', 0)
        
        # Pattern detection
        if rsi < 30 and candle_strength > 0.7 and momentum > 0:
            return 'oversold_bounce'
        elif rsi > 70 and candle_strength < 0.3 and momentum < 0:
            return 'overbought_rejection'
        elif ema_align > 0 and features.get('volume_ratio', 1) > 1.3:
            return 'trend_continuation_bull'
        elif ema_align < 0 and features.get('volume_ratio', 1) > 1.3:
            return 'trend_continuation_bear'
        elif features.get('higher_lows', 0) > 2 and rsi < 50:
            return 'higher_lows_formation'
        elif features.get('higher_highs', 0) > 2 and rsi > 50:
            return 'higher_highs_formation'
        else:
            return 'range_action'
    
    def _build_reason(self, features: dict, market_intel: dict, regime: str) -> str:
        """Build human-readable reason for signal."""
        reasons = []
        
        pattern = self._identify_pattern(features)
        reasons.append(f"Pattern: {pattern}")
        
        if features.get('trend_direction', 0) > 0:
            reasons.append("Trend: Bullish")
        elif features.get('trend_direction', 0) < 0:
            reasons.append("Trend: Bearish")
        
        rsi = features.get('rsi_3', 50)
        if rsi < 30:
            reasons.append(f"RSI(3): Oversold ({rsi:.0f})")
        elif rsi > 70:
            reasons.append(f"RSI(3): Overbought ({rsi:.0f})")
        
        vol_ratio = features.get('volume_ratio', 1)
        if vol_ratio > 1.3:
            reasons.append(f"Volume surge: {vol_ratio:.1f}x")
        
        if market_intel.get('hour_bias') != 'neutral':
            reasons.append(f"Hour bias: {market_intel['hour_bias']}")
        
        reasons.append(f"Regime: {regime}")
        
        return " | ".join(reasons)
    
    def record_trade_outcome(self, signal: dict, exit_price: float, won: bool, pnl_pct: float) -> None:
        """Record trade outcome to memory for learning."""
        trade = TradeMemory(
            trade_id=f"{signal.get('pattern_type', 'unknown')}_{int(time.time())}",
            timestamp=int(time.time() * 1000),
            entry_price=signal.get('entry', 0),
            exit_price=exit_price,
            side=signal.get('signal', 'UNKNOWN'),
            price_level=signal.get('entry', 0),
            volatility=signal.get('features', {}).get('atr_pct', 0),
            volume_ratio=signal.get('features', {}).get('volume_ratio', 1),
            trend_strength=signal.get('features', {}).get('trend_strength', 0),
            regime=signal.get('regime', 'unknown'),
            pattern_features=signal.get('features', {}),
            pattern_type=signal.get('pattern_type', 'unknown'),
            entry_reason=signal.get('reason', ''),
            pnl_pct=pnl_pct,
            won=won,
            was_correct=won,
            lessons=[f"Outcome: {'WIN' if won else 'LOSS'} ({pnl_pct:.2f}%)"]
        )
        
        self.memory.add_trade(trade)
        
        # Update decision accuracy
        self.total_decisions += 1
        if won:
            self.correct_decisions += 1
    
    def get_agent_status(self) -> dict:
        """Get agent learning status."""
        return {
            'decisions': self.total_decisions,
            'accuracy': self.correct_decisions / self.total_decisions if self.total_decisions > 0 else 0,
            'memory_stats': self.memory.get_statistics(),
            'patterns_learned': len(self.memory.patterns),
            'market_hours_knowledge': len(self.memory.cycles_learned),
        }


# ──────────────────────────────────────────────────────────────
# Singleton instance
# ──────────────────────────────────────────────────────────────

agent = SelfAwareTradingAgent()