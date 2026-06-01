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

import hashlib
import json
import math
import time
import uuid
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
        """Exponential moving average update of pattern reliability."""
        self.sample_count += 1
        # EMA-style update: recent samples have more weight
        alpha = 1.0 / self.sample_count  # Decreasing learning rate
        self.outcome = self.outcome * (1 - alpha) + new_outcome * alpha
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
        
        change_pct = (candle.close - candle.open) / candle.open * 100 if candle.open > 0 else 0
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
        features_str = json.dumps(trade.pattern_features, sort_keys=True, default=str)
        pattern_key = f"{trade.pattern_type}_{hashlib.md5(features_str.encode()).hexdigest()[:12]}"
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
        matching_patterns = []
        for pattern in self.patterns.values():
            if not isinstance(pattern, MarketPattern):
                continue
            if pattern.pattern_type == pattern_type:
                matching_patterns.append(pattern)
        
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
                max_val = max(abs(v1), abs(v2))
                if max_val > 1e-10:
                    similarity = 1 - abs(v1 - v2) / max_val
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
        def _get_regime(t):
            return t.regime if hasattr(t, 'regime') else (t.get('regime', '') if isinstance(t, dict) else '')
        def _get_won(t):
            return t.won if hasattr(t, 'won') else (t.get('won', False) if isinstance(t, dict) else False)
        regime_trades = [t for t in self.trade_history if _get_regime(t) == regime]
        if len(regime_trades) < 5:
            return 0.5
        
        wins = sum(1 for t in regime_trades if _get_won(t))
        return wins / len(regime_trades)
    
    def save(self, path: str = "data/market_memory.pkl") -> None:
        import json, os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "patterns": self.patterns,
            "trade_history": self.trade_history,
            "price_levels": list(self.price_levels),
            "volume_profile": list(self.volume_profile),
            "regime_history": list(self.regime_history),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": self.total_pnl,
            "cycles_learned": {str(k): v for k, v in self.cycles_learned.items()},
            "day_of_week_behavior": {str(k): v for k, v in self.day_of_week_behavior.items()},
            "volatility_states": self.volatility_states,
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, default=str)
        os.replace(tmp_path, path)

    @classmethod
    def load(cls, path: str = "data/market_memory.pkl") -> "MarketMemory":
        import json
        mem = cls()
        try:
            with open(path, "r") as f:
                data = json.load(f)
            mem.patterns = data.get("patterns", {})
            mem.trade_history = data.get("trade_history", [])
            mem.price_levels = deque(data.get("price_levels", []), maxlen=10000)
            mem.volume_profile = deque(data.get("volume_profile", []), maxlen=5000)
            mem.regime_history = deque(data.get("regime_history", []), maxlen=1000)
            mem.total_trades = data.get("total_trades", 0)
            mem.winning_trades = data.get("winning_trades", 0)
            mem.total_pnl = data.get("total_pnl", 0.0)
            mem.cycles_learned = {int(k): v for k, v in data.get("cycles_learned", {}).items()}
            mem.day_of_week_behavior = {int(k): v for k, v in data.get("day_of_week_behavior", {}).items()}
            mem.volatility_states = data.get("volatility_states", {})
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass
        return mem

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
        nearest_resistance = min(h for h in swing_highs if h > current_price) if any(h > current_price for h in swing_highs) else (min(swing_highs) if swing_highs else current_price * 1.02)
        nearest_support = max(l for l in swing_lows if l < current_price) if any(l < current_price for l in swing_lows) else (max(swing_lows) if swing_lows else current_price * 0.98)
        
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
        self._decision_ids: set[str] = set()
        self._loaded_trade_ids: set[str] = set()
        
    def analyze_market(self, candles: list[Candle], timeframe: str = "5m") -> dict:
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
        last_candle = candles[-1]
        candle_body = last_candle.close - last_candle.open
        
        if winning_side == 'LONG':
            entry = min(current_price, last_candle.open + candle_body * 0.3)
            stop_loss = entry - atr * 2.5
            target = entry + atr * 5
            risk_reward = 2.0
        else:
            entry = max(current_price, last_candle.close - candle_body * 0.3)
            stop_loss = entry + atr * 2.5
            target = entry - atr * 5
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
        self._record_decision(signal, candles[-1].timestamp, timeframe)
        
        return signal

    def analyze_enriched(
        self,
        candles: list[Candle],
        order_flow=None,
        vwap=None,
        oi=None,
        funding=None,
        sweeps=None,
        vol_profile=None,
        rsi_3: float = 50.0,
        kill_active: bool = False,
        kill_session: str = "",
        metrics=None,
        fvgs=None,
        order_blocks=None,
        regime_obj=None,
        wick=None,
        futures_context=None,
        long_confluence: float = 0.0,
        short_confluence: float = 0.0,
        timeframe: str = "5m",
    ) -> dict:
        """
        Central brain analysis using ALL data sources.
        Merges price-action + all 15 data sources + memory into one decision.
        """
        if len(candles) < 50:
            return {'signal': 'WAIT', 'reason': 'Insufficient data', 'confidence': 0}

        price_features = self.feature_extractor.extract_features(candles)
        if not price_features:
            return {'signal': 'WAIT', 'reason': 'Feature extraction failed', 'confidence': 0}

        for c in candles[-5:]:
            self.memory.add_price_snapshot(c)

        now = datetime.now(timezone.utc)
        hour = now.hour
        regime = self._detect_regime(candles)
        market_intel = self.memory.get_market_intelligence(hour, regime)

        regime_phase = regime_obj.phase if regime_obj else regime
        price = candles[-1].close

        # Extract enriched features from ALL data sources
        ctx = self._extract_context_features(
            price, price_features, order_flow, vwap, oi, funding,
            sweeps, vol_profile, rsi_3, kill_active, metrics,
            fvgs, order_blocks, regime_obj, wick, futures_context,
        )

        # Compute agent's own scores using the full enriched feature set
        long_score, long_reasons = self._compute_enriched_score(
            'long', price_features, ctx, market_intel, regime_phase, price,
        )
        short_score, short_reasons = self._compute_enriched_score(
            'short', price_features, ctx, market_intel, regime_phase, price,
        )

        # Blend with engine's confluence scores (agent is 60% weight)
        final_long = long_score * 0.6 + long_confluence * 0.3 + ctx['memory_bias_long'] * 0.1
        final_short = short_score * 0.6 + short_confluence * 0.3 + ctx['memory_bias_short'] * 0.1

        edge = abs(final_long - final_short)
        if edge < 0.08:
            return {
                'signal': 'WAIT', 'reason': 'No clear directional edge after full context fusion',
                'confidence': max(final_long, final_short), 'long_score': final_long,
                'short_score': final_short, 'features': {**price_features, **ctx},
                'market_intel': market_intel,
            }

        winning_side = 'LONG' if final_long > final_short else 'SHORT'
        winning_score = max(final_long, final_short)
        reasons = long_reasons if winning_side == 'LONG' else short_reasons

        threshold = max(self.min_confidence, 0.45)
        if winning_score < threshold:
            return {
                'signal': 'WAIT',
                'reason': f'Full context confidence {winning_score:.2f} below {threshold:.2f}',
                'confidence': winning_score, 'long_score': final_long, 'short_score': final_short,
                'features': {**price_features, **ctx},
            }

        atr = price_features.get('atr_pct', 0.02) * price
        sl_mult = max(2.0, 4.0 - winning_score * 2)
        tp_mult = 3.0 + winning_score * 3
        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult

        # ── FIX: Enter below close for longs, above close for shorts ───────
        # Root cause: price has already moved within the candle before the
        # signal fires at close. Entering at close buys tops/sells bottoms.
        last_candle = candles[-1]
        if winning_side == 'LONG':
            entry = min(price, last_candle.open + (last_candle.close - last_candle.open) * 0.3)
            stop_loss = entry - sl_dist
            target = entry + tp_dist
        else:
            entry = max(price, last_candle.close - (last_candle.close - last_candle.open) * 0.3)
            stop_loss = entry + sl_dist
            target = entry - tp_dist

        signal = {
            'signal': winning_side,
            'confidence': winning_score,
            'entry': entry,
            'stop_loss': stop_loss,
            'target': target,
            'risk_reward': round(abs(target - entry) / abs(entry - stop_loss), 2) if abs(entry - stop_loss) > 0 else 0,
            'reason': " | ".join(reasons),
            'pattern_type': self._identify_pattern(price_features),
            'features': {**price_features, **ctx},
            'enriched_features': ctx,
            'market_intel': market_intel,
            'regime': regime_phase,
        }
        self._record_decision(signal, candles[-1].timestamp, timeframe)
        return signal

    def _extract_context_features(
        self, price: float, pf: dict, of=None, vwap=None, oi=None,
        funding=None, sweeps=None, vp=None, rsi_3=50.0, kill_active=False,
        metrics=None, fvgs=None, obs=None, regime_obj=None, wick=None, fc=None,
    ) -> dict:
        """Extract numerical features from ALL market data sources."""
        ctx: dict[str, float] = {}

        # 1. Order Flow
        if of:
            ctx['of_delta'] = of.delta if hasattr(of, 'delta') else 0
            ctx['of_cvd_slope'] = of.cvd_slope if hasattr(of, 'cvd_slope') else 0
            ctx['of_bullish'] = 1 if (ctx.get('of_delta', 0) > 0 and ctx.get('of_cvd_slope', 0) > 0) else 0
            ctx['of_bearish'] = 1 if (ctx.get('of_delta', 0) < 0 and ctx.get('of_cvd_slope', 0) < 0) else 0
            ctx['of_footprint_bullish'] = 1 if hasattr(of, 'footprint_imbalance') and of.footprint_imbalance > 0.6 else 0
        else:
            ctx.update(of_delta=0, of_cvd_slope=0, of_bullish=0, of_bearish=0, of_footprint_bullish=0)

        # 2. VWAP
        if vwap:
            vwap_price = vwap.vwap if hasattr(vwap, 'vwap') else 0
            ctx['vwap_deviation'] = vwap.price_deviation_pct if hasattr(vwap, 'price_deviation_pct') else 0
            ctx['vwap_above'] = 1 if price > vwap_price else 0
            ctx['vwap_below'] = 1 if price < vwap_price else 0
            ctx['vwap_compressed'] = 1 if hasattr(vwap, 'is_compressed') and vwap.is_compressed else 0
            lower = vwap.lower_band_1sd if hasattr(vwap, 'lower_band_1sd') else 0
            upper = vwap.upper_band_1sd if hasattr(vwap, 'upper_band_1sd') else 0
            ctx['vwap_near_lower'] = 1 if lower and price <= lower else 0
            ctx['vwap_near_upper'] = 1 if upper and price >= upper else 0
        else:
            ctx.update(vwap_deviation=0, vwap_above=0, vwap_below=0, vwap_compressed=0, vwap_near_lower=0, vwap_near_upper=0)

        # 3. Open Interest
        if oi:
            ctx['oi_change_pct'] = oi.oi_change_pct if hasattr(oi, 'oi_change_pct') else 0
            ctx['oi_increasing'] = 1 if hasattr(oi, 'oi_trend') and oi.oi_trend == 'increasing' else 0
            ctx['oi_decreasing'] = 1 if hasattr(oi, 'oi_trend') and oi.oi_trend == 'decreasing' else 0
            ctx['oi_momentum'] = 1 if hasattr(oi, 'momentum_confirmation') and oi.momentum_confirmation else 0
        else:
            ctx.update(oi_change_pct=0, oi_increasing=0, oi_decreasing=0, oi_momentum=0)

        # 4. Funding Rate
        if funding:
            ctx['funding_rate'] = funding.current_rate if hasattr(funding, 'current_rate') else 0
            ctx['funding_extreme'] = 1 if hasattr(funding, 'is_extreme') and funding.is_extreme else 0
            ctx['funding_bullish'] = 1 if hasattr(funding, 'contrarian_bias') and funding.contrarian_bias == 'bullish' else 0
            ctx['funding_bearish'] = 1 if hasattr(funding, 'contrarian_bias') and funding.contrarian_bias == 'bearish' else 0
        else:
            ctx.update(funding_rate=0, funding_extreme=0, funding_bullish=0, funding_bearish=0)

        # 5. Liquidity Sweeps
        if sweeps:
            long_sweeps = [s for s in sweeps if hasattr(s, 'side') and s.side == 'long' and hasattr(s, 'reclaimed') and s.reclaimed]
            short_sweeps = [s for s in sweeps if hasattr(s, 'side') and s.side == 'short' and hasattr(s, 'reclaimed') and s.reclaimed]
            ctx['sweep_long_reclaimed'] = len(long_sweeps)
            ctx['sweep_short_reclaimed'] = len(short_sweeps)
            ctx['sweep_bullish'] = 1 if any(getattr(s, 'entry_trigger', False) for s in long_sweeps) else 0
            ctx['sweep_bearish'] = 1 if any(getattr(s, 'entry_trigger', False) for s in short_sweeps) else 0
        else:
            ctx.update(sweep_long_reclaimed=0, sweep_short_reclaimed=0, sweep_bullish=0, sweep_bearish=0)

        # 6. Volume Profile
        if vp and hasattr(vp, 'poc') and vp.poc:
            ctx['vp_poc_distance'] = abs(price - vp.poc) / vp.poc
            val = vp.val if hasattr(vp, 'val') else 0
            vah = vp.vah if hasattr(vp, 'vah') else 0
            ctx['vp_in_discount'] = 1 if val and price <= val else 0
            ctx['vp_in_premium'] = 1 if vah and price >= vah else 0
            ctx['vp_at_poc'] = 1 if ctx['vp_poc_distance'] < 0.002 else 0
        else:
            ctx.update(vp_poc_distance=1, vp_in_discount=0, vp_in_premium=0, vp_at_poc=0)

        # 7. RSI(3)
        ctx['rsi_3'] = rsi_3
        ctx['rsi_3_oversold'] = 1 if rsi_3 < 30 else 0
        ctx['rsi_3_overbought'] = 1 if rsi_3 > 70 else 0
        ctx['rsi_3_recovery'] = 1 if 25 <= rsi_3 <= 45 else 0
        ctx['rsi_3_rejection'] = 1 if 55 <= rsi_3 <= 75 else 0

        # 8. Killzone
        ctx['killzone_active'] = 1 if kill_active else 0

        # 9. FVGs
        if fvgs:
            bullish_fvg = [f for f in fvgs if not getattr(f, 'is_filled', False) and getattr(f, 'direction', '') == 'bullish']
            bearish_fvg = [f for f in fvgs if not getattr(f, 'is_filled', False) and getattr(f, 'direction', '') == 'bearish']
            ctx['fvg_bullish_near'] = 1 if any(abs(price - getattr(f, 'bottom', 0)) / price < 0.003 for f in bullish_fvg) else 0
            ctx['fvg_bearish_near'] = 1 if any(abs(price - getattr(f, 'top', 0)) / price < 0.003 for f in bearish_fvg) else 0
        else:
            ctx.update(fvg_bullish_near=0, fvg_bearish_near=0)

        # 10. Order Blocks
        if obs:
            bullish_ob = [o for o in obs if not getattr(o, 'is_breaker', False) and getattr(o, 'direction', '') == 'bullish']
            bearish_ob = [o for o in obs if not getattr(o, 'is_breaker', False) and getattr(o, 'direction', '') == 'bearish']
            ctx['ob_bullish_near'] = 1 if any(abs(price - getattr(o, 'top', 0)) / price < 0.003 for o in bullish_ob) else 0
            ctx['ob_bearish_near'] = 1 if any(abs(price - getattr(o, 'bottom', 0)) / price < 0.003 for o in bearish_ob) else 0
        else:
            ctx.update(ob_bullish_near=0, ob_bearish_near=0)

        # 11. Regime
        if regime_obj:
            ctx['regime_trending'] = 1 if regime_obj.phase in ('trending', 'trending_volatile') else 0
            ctx['regime_range'] = 1 if regime_obj.phase == 'range_bound' else 0
            ctx['regime_consolidation'] = 1 if regime_obj.phase == 'consolidation' else 0
            ctx['regime_accumulation'] = 1 if regime_obj.phase == 'accumulation' else 0
            ctx['regime_distribution'] = 1 if regime_obj.phase == 'distribution' else 0
            ctx['regime_bias_bullish'] = 1 if getattr(regime_obj, 'bias', '') == 'bullish' else 0
            ctx['regime_bias_bearish'] = 1 if getattr(regime_obj, 'bias', '') == 'bearish' else 0
        else:
            ctx.update(regime_trending=0, regime_range=0, regime_consolidation=0, regime_accumulation=0, regime_distribution=0, regime_bias_bullish=0, regime_bias_bearish=0)

        # 12. Market Metrics
        if metrics:
            ctx['trend_score'] = getattr(metrics, 'trend_score', 0) or 0
            ctx['bias_score'] = getattr(metrics, 'bias_score', 0) or 0
        else:
            ctx.update(trend_score=0, bias_score=0)

        # 13. Wick Rejection
        if wick:
            ctx['wick_bullish'] = 1 if getattr(wick, 'bullish_rejection_active', False) else 0
            ctx['wick_bearish'] = 1 if getattr(wick, 'bearish_rejection_active', False) else 0
            ctx['wick_strength'] = getattr(wick, 'rejection_strength', 0) or 0
        else:
            ctx.update(wick_bullish=0, wick_bearish=0, wick_strength=0)

        # 14. Futures Context
        if fc:
            if isinstance(fc, dict):
                ctx['fc_funding_bias_bullish'] = 1 if fc.get('funding_contrarian_bias') == 'bullish' else 0
                ctx['fc_funding_bias_bearish'] = 1 if fc.get('funding_contrarian_bias') == 'bearish' else 0
                ctx['fc_oi_momentum'] = 1 if fc.get('oi_momentum_confirmation') else 0
            else:
                ctx['fc_funding_bias_bullish'] = 1 if getattr(fc, 'funding_contrarian_bias', '') == 'bullish' else 0
                ctx['fc_funding_bias_bearish'] = 1 if getattr(fc, 'funding_contrarian_bias', '') == 'bearish' else 0
                ctx['fc_oi_momentum'] = 1 if getattr(fc, 'oi_momentum_confirmation', False) else 0
        else:
            ctx.update(fc_funding_bias_bullish=0, fc_funding_bias_bearish=0, fc_oi_momentum=0)

        # 15. Memory bias from past similar contexts
        memory_bias = self._get_enriched_memory_bias(ctx)
        ctx['memory_bias_long'] = memory_bias['long']
        ctx['memory_bias_short'] = memory_bias['short']

        return ctx

    def _get_enriched_memory_bias(self, ctx: dict) -> dict:
        """Query memory for bias based on similar enriched contexts."""
        if not self.memory.patterns:
            return {'long': 0.0, 'short': 0.0}

        long_total, short_total, count = 0.0, 0.0, 0
        for pid, pattern in self.memory.patterns.items():
            # Handle both object and dict formats (pickle vs JSON)
            if isinstance(pattern, dict):
                feat = pattern.get('features', {})
                outcome = pattern.get('outcome', 0)
            elif hasattr(pattern, 'features'):
                feat = pattern.features
                outcome = pattern.outcome
            else:
                continue
            if not isinstance(feat, dict):
                continue
            overlap = [k for k in ctx if k in feat and isinstance(feat[k], (int, float))]
            if len(overlap) < 5:
                continue
            sim = sum(1 - abs(ctx[k] - feat[k]) / max(abs(ctx[k]), abs(feat[k]), 0.001) for k in overlap) / len(overlap)
            if sim > 0.6:
                count += 1
                if outcome > 0:
                    long_total += outcome * sim
                else:
                    short_total += abs(outcome) * sim

        if count == 0:
            return {'long': 0.0, 'short': 0.0}
        return {
            'long': min(0.3, long_total / count),
            'short': min(0.3, short_total / count),
        }

    def _compute_enriched_score(
        self, direction: str, pf: dict, ctx: dict, market_intel: dict, regime: str, price: float,
    ) -> tuple[float, list[str]]:
        """Compute score for a direction using ALL enriched features + price action.

        Starts at a neutral 0.5 and pushes decisively toward 0.0 or 1.0 based on
        confluence of evidence. Each factor adds/subtracts 0.03-0.10 so strong
        multi-factor alignment can push the score to 0.7-0.85 quickly.
        """
        score = 0.5
        reasons: list[str] = []
        is_long = direction == 'long'

        # ── Price-action factors (from existing feature extractor) ──
        if is_long:
            if pf.get('trend_direction', 0) > 0:
                score += 0.10; reasons.append("PA trend bullish")
            if pf.get('ema_alignment', 0) > 0:
                score += 0.08; reasons.append("EMA aligned bull")
            if pf.get('rsi_3', 50) < 30:
                score += 0.10; reasons.append("PA RSI oversold")
            elif pf.get('rsi_3', 50) < 40:
                score += 0.05; reasons.append("PA RSI near oversold")
        else:
            if pf.get('trend_direction', 0) < 0:
                score += 0.10; reasons.append("PA trend bearish")
            if pf.get('ema_alignment', 0) < 0:
                score += 0.08; reasons.append("EMA aligned bear")
            if pf.get('rsi_3', 50) > 70:
                score += 0.10; reasons.append("PA RSI overbought")
            elif pf.get('rsi_3', 50) > 60:
                score += 0.05; reasons.append("PA RSI near overbought")

        # ── Order Flow ──
        if is_long and ctx.get('of_bullish'):
            score += 0.07; reasons.append("OF bullish")
        elif not is_long and ctx.get('of_bearish'):
            score += 0.07; reasons.append("OF bearish")

        # ── VWAP ──
        if is_long:
            if ctx.get('vwap_above'):
                score += 0.04; reasons.append("VWAP above")
            if ctx.get('vwap_near_lower'):
                score += 0.04; reasons.append("VWAP at lower band")
        else:
            if ctx.get('vwap_below'):
                score += 0.04; reasons.append("VWAP below")
            if ctx.get('vwap_near_upper'):
                score += 0.04; reasons.append("VWAP at upper band")

        # ── Open Interest ──
        if ctx.get('oi_momentum'):
            if is_long:
                score += 0.05; reasons.append("OI mom bullish")
            else:
                score += 0.05; reasons.append("OI mom bearish")

        # ── Funding ──
        if is_long and ctx.get('funding_bullish'):
            score += 0.05; reasons.append("Funding bull contrarian")
        elif not is_long and ctx.get('funding_bearish'):
            score += 0.05; reasons.append("Funding bear contrarian")

        # ── Sweeps ──
        if is_long and ctx.get('sweep_bullish'):
            score += 0.08; reasons.append("Sweep reclaimed bull")
        elif not is_long and ctx.get('sweep_bearish'):
            score += 0.08; reasons.append("Sweep reclaimed bear")

        # ── Volume Profile ──
        if is_long and ctx.get('vp_in_discount'):
            score += 0.04; reasons.append("VP discount zone")
        elif not is_long and ctx.get('vp_in_premium'):
            score += 0.04; reasons.append("VP premium zone")

        # ── RSI(3) enriched ──
        if is_long and ctx.get('rsi_3_recovery'):
            score += 0.04; reasons.append("RSI recovery zone")
        elif not is_long and ctx.get('rsi_3_rejection'):
            score += 0.04; reasons.append("RSI rejection zone")

        # ── Killzone ──
        if ctx.get('killzone_active'):
            score += 0.03; reasons.append("Killzone active")

        # ── FVGs ──
        if is_long and ctx.get('fvg_bullish_near'):
            score += 0.04; reasons.append("FVG support near")
        elif not is_long and ctx.get('fvg_bearish_near'):
            score += 0.04; reasons.append("FVG resistance near")

        # ── Order Blocks ──
        if is_long and ctx.get('ob_bullish_near'):
            score += 0.04; reasons.append("OB support near")
        elif not is_long and ctx.get('ob_bearish_near'):
            score += 0.04; reasons.append("OB resistance near")

        # ── Regime ──
        if is_long and ctx.get('regime_trending') and ctx.get('regime_bias_bullish'):
            score += 0.04; reasons.append("Trend bull regime")
        elif not is_long and ctx.get('regime_trending') and ctx.get('regime_bias_bearish'):
            score += 0.04; reasons.append("Trend bear regime")

        # ── Wick Rejection ──
        if is_long and ctx.get('wick_bullish'):
            w = abs(ctx.get('wick_strength', 0)) * 0.05
            score += w; reasons.append("Wick rejection bull")
        elif not is_long and ctx.get('wick_bearish'):
            w = abs(ctx.get('wick_strength', 0)) * 0.05
            score += w; reasons.append("Wick rejection bear")

        # ── Memory bias ──
        mem_key = 'memory_bias_long' if is_long else 'memory_bias_short'
        mem_val = ctx.get(mem_key, 0)
        if mem_val > 0:
            score += mem_val * 0.5
            reasons.append(f"Memory bias {direction}")

        # ── Market intelligence ──
        if market_intel:
            hour_bias = market_intel.get('hour_bias', 'neutral')
            if is_long and hour_bias == 'bullish':
                score += 0.05 * market_intel.get('confidence', 0.5)
                reasons.append("Hour bias bull")
            elif not is_long and hour_bias == 'bearish':
                score += 0.05 * market_intel.get('confidence', 0.5)
                reasons.append("Hour bias bear")

        # ── Pattern reliability from memory ──
        pattern_type = self._identify_pattern(pf)
        pattern_score = self.memory.get_pattern_reliability(pattern_type, pf)
        if pattern_score > 0.55:
            score += pattern_score * 0.06
            reasons.append(f"Pattern reliability {pattern_score:.2f}")

        score = min(0.95, max(0.05, score))
        return score, reasons

    def record_trade_outcome(self, signal: dict, exit_price: float, won: bool, pnl_pct: float) -> None:
        """Record trade outcome to memory with full enriched context for learning."""
        enriched = signal.get('enriched_features') or signal.get('features', {})
        trade = TradeMemory(
            trade_id=f"{signal.get('pattern_type', 'unknown')}_{int(time.time())}",
            timestamp=int(time.time() * 1000),
            entry_price=signal.get('entry', 0),
            exit_price=exit_price,
            side=signal.get('signal', 'UNKNOWN'),
            price_level=signal.get('entry', 0),
            volatility=signal.get('features', {}).get('atr_pct', 0) if isinstance(signal.get('features'), dict) else 0,
            volume_ratio=signal.get('features', {}).get('volume_ratio', 1) if isinstance(signal.get('features'), dict) else 1,
            trend_strength=signal.get('features', {}).get('trend_strength', 0) if isinstance(signal.get('features'), dict) else 0,
            regime=signal.get('regime', 'unknown'),
            pattern_features=enriched if isinstance(enriched, dict) else {},
            pattern_type=signal.get('pattern_type', 'unknown'),
            entry_reason=signal.get('reason', ''),
            exit_reason=signal.get('exit_reason', 'trade_closed'),
            pnl_pct=pnl_pct,
            won=won,
            was_correct=won,
            lessons=[f"Outcome: {'WIN' if won else 'LOSS'} ({pnl_pct:.2f}%) | Side: {signal.get('signal', '?')} | Enriched context: {len(enriched)} features"],
        )

        self.memory.add_trade(trade)

        self.total_decisions += 1
        if won:
            self.correct_decisions += 1

    def _record_decision(self, signal: dict, candle_timestamp: int, timeframe: str = "5m") -> None:
        """Deduplicate analysis cycles — no longer increments total_decisions.
        The agent's decisions/accuracy now reflect only actual trade outcomes
        recorded via record_trade_outcome(), not every candle analysis cycle."""
        from backend.analysis.ids import stable_id
        sig = signal.get("signal", "")
        direction = "long" if sig == "LONG" else "short"
        entry = signal.get("entry", 0)
        sl = signal.get("stop_loss", 0)
        decision_id = stable_id("scalp", direction, candle_timestamp, int(entry * 10), int(sl * 10))
        if decision_id in self._decision_ids:
            return
        self._decision_ids.add(decision_id)

        # NOTE: Prediction is recorded in unified_scalp.py compute() using
        # the actual ScalpSignal ID — NOT here — to guarantee ID consistency
        # between prediction and trade outcome lookup.
    
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
        score = 0.5
        
        # Trend alignment (strongest signal)
        if features.get('trend_direction') > 0:
            score += 0.15
        if features.get('ema_alignment') > 0:
            score += 0.12
        
        # Momentum
        if features.get('rsi_3') < 30:
            score += 0.15
        elif features.get('rsi_3') < 40:
            score += 0.08
        if features.get('rsi_3') < 50 and features.get('momentum') > 0:
            score += 0.10
        
        # RSI confirmation
        if 30 < features.get('rsi_14', 50) < 60:
            score += 0.05
        
        # Volume confirmation
        if features.get('volume_ratio', 1) > 1.2:
            score += 0.10
        elif features.get('volume_ratio', 1) > 1.0:
            score += 0.04
        
        # Range position (buying near support)
        if features.get('support_distance', 0) < 0.02:
            score += 0.10
        elif features.get('support_distance', 0) < 0.05:
            score += 0.05
        
        # Market intelligence
        if market_intel.get('hour_bias') == 'bullish':
            score += 0.08 * market_intel.get('confidence', 0.5)
        
        # Pattern reliability from memory
        pattern_type = self._identify_pattern(features)
        pattern_score = self.memory.get_pattern_reliability(pattern_type, features)
        score += pattern_score * 0.12
        
        # Regime modifier - only boost when trend aligns with long direction
        if regime in ['trending', 'trending_volatile']:
            if features.get('trend_direction', 0) > 0:
                score += 0.06
        elif regime == 'consolidation':
            score -= 0.08
        
        # Volatility squeeze bonus
        if features.get('volatility_state') == 'low':
            score += 0.04
        
        return min(0.95, max(0.1, score))
    
    def _calculate_short_score(self, features: dict, market_intel: dict, regime: str) -> float:
        """Calculate probability of successful short trade."""
        score = 0.5
        
        # Trend alignment (opposite of long)
        if features.get('trend_direction') < 0:
            score += 0.15
        if features.get('ema_alignment') < 0:
            score += 0.12
        
        # Momentum
        if features.get('rsi_3') > 70:
            score += 0.15
        elif features.get('rsi_3') > 60:
            score += 0.08
        if features.get('rsi_3') > 50 and features.get('momentum') < 0:
            score += 0.10
        
        # RSI confirmation
        if 40 < features.get('rsi_14', 50) < 70:
            score += 0.05
        
        # Volume confirmation
        if features.get('volume_ratio', 1) > 1.2:
            score += 0.10
        elif features.get('volume_ratio', 1) > 1.0:
            score += 0.04
        
        # Range position (selling near resistance)
        if features.get('resistance_distance', 0) < 0.02:
            score += 0.10
        elif features.get('resistance_distance', 0) < 0.05:
            score += 0.05
        
        # Market intelligence
        if market_intel.get('hour_bias') == 'bearish':
            score += 0.08 * market_intel.get('confidence', 0.5)
        
        # Pattern reliability from memory
        pattern_type = self._identify_pattern(features)
        pattern_score = self.memory.get_pattern_reliability(pattern_type, features)
        score += pattern_score * 0.12
        
        # Regime modifier - only boost the direction matching trend
        if regime in ['trending', 'trending_volatile']:
            # This is the short score method, only boost if trend is bearish
            if features.get('trend_direction', 0) < 0:
                score += 0.06
        elif regime == 'consolidation':
            score -= 0.08
        
        # Volatility squeeze bonus
        if features.get('volatility_state') == 'low':
            score += 0.04
        
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

    def bootstrap_from_paper_trades(self, trades: list[dict]) -> int:
        """Load closed paper-trade outcomes into memory after restart."""
        loaded = 0
        for trade in trades:
            trade_id = str(trade.get('id') or '')
            if not trade_id or trade_id in self._loaded_trade_ids:
                continue
            if trade.get('status') != 'closed' or trade.get('pnl_pct') is None:
                continue

            side = str(trade.get('side') or 'unknown')
            pattern_type = self._pattern_type_from_reason(str(trade.get('reason') or ''), side)
            pnl_pct = float(trade.get('pnl_pct') or 0)
            entry_price = float(trade.get('entry_price') or 0)
            exit_price = float(trade.get('exit_price') or 0)
            timestamp = int(trade.get('opened_at') or trade.get('closed_at') or time.time() * 1000)
            won = pnl_pct > 0

            memory = TradeMemory(
                trade_id=trade_id,
                timestamp=timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                side=side,
                price_level=entry_price,
                volatility=0,
                volume_ratio=1,
                trend_strength=0,
                regime='paper_history',
                pattern_features={
                    'confidence': float(trade.get('confidence') or 0),
                    'risk_reward': float(trade.get('risk_reward') or 0),
                },
                pattern_type=pattern_type,
                entry_reason=str(trade.get('reason') or ''),
                exit_reason=str(trade.get('close_reason') or ''),
                pnl_pct=pnl_pct,
                won=won,
                was_correct=won,
                lessons=[f"Restored paper outcome: {'WIN' if won else 'LOSS'} ({pnl_pct:.2f}%)"],
            )
            self.memory.add_trade(memory)
            self._loaded_trade_ids.add(trade_id)
            loaded += 1
        # Sync decision counters from memory to discard any inflation from
        # the old _record_decision() path (which counted every candle analysis
        # as a decision). Now only actual trade outcomes count.
        if loaded > 0:
            self.total_decisions = self.memory.total_trades
            self.correct_decisions = self.memory.winning_trades
        return loaded

    @staticmethod
    def _pattern_type_from_reason(reason: str, side: str) -> str:
        lowered = reason.lower()
        if "ai brain:" in lowered:
            fragment = lowered.split("ai brain:", 1)[1].split("|", 1)[0].strip()
            return fragment.replace(" ", "_") or f"{side}_ai_pattern"
        if "ai signal:" in lowered:
            return f"{side}_ai_signal"
        if "vwap" in lowered:
            return f"{side}_vwap"
        if "fvg" in lowered:
            return f"{side}_fvg"
        if "order block" in lowered or " ob" in lowered:
            return f"{side}_order_block"
        if "rsi" in lowered:
            return f"{side}_rsi"
        return f"{side}_paper_trade"
    
    def get_agent_status(self) -> dict:
        """Get agent learning status."""
        return {
            'decisions': self.total_decisions,
            'accuracy': self.correct_decisions / self.total_decisions if self.total_decisions > 0 else 0,
            'memory_stats': self.memory.get_statistics(),
            'patterns_learned': len(self.memory.patterns),
            'market_hours_knowledge': len(self.memory.cycles_learned),
        }

    def save_state(self, path: str = "data/agent_brain.json") -> None:
        """Save entire agent state to disk."""
        import json, os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.memory.save(path.replace("agent_brain.json", "market_memory.pkl"))
        state = {
            "total_decisions": self.total_decisions,
            "correct_decisions": self.correct_decisions,
            "_decision_ids": list(self._decision_ids),
            "_loaded_trade_ids": list(self._loaded_trade_ids),
        }
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, default=str)
        os.replace(tmp_path, path)

    def load_state(self, path: str = "data/agent_brain.json") -> bool:
        """Load agent state from disk. Returns True if loaded."""
        import json
        self.memory = MarketMemory.load(path.replace("agent_brain.json", "market_memory.pkl"))
        try:
            with open(path, "r") as f:
                state = json.load(f)
            self._decision_ids = set(state.get("_decision_ids", []))
            self._loaded_trade_ids = set(state.get("_loaded_trade_ids", []))
            # Sync counters from memory to discard any inflation from the
            # old _record_decision() path that counted every candle as a decision.
            self.total_decisions = self.memory.total_trades
            self.correct_decisions = self.memory.winning_trades
            return True
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return False


# ──────────────────────────────────────────────────────────────
# Singleton instance (lazy initialization)
# ──────────────────────────────────────────────────────────────

agent: SelfAwareTradingAgent | None = None


def get_agent() -> SelfAwareTradingAgent:
    """Get or create the singleton agent instance."""
    global agent
    if agent is None:
        agent = SelfAwareTradingAgent()
        agent.load_state()
    return agent
