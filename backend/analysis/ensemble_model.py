"""
NEXUS Ensemble Trading Model v1.0

3-model weighted blend with regime-aware weighting:
1. Microstructure Model (order flow, OBI, CVD, footprint)
2. ICT Model (FVG, OB, liquidity, structure)
3. Momentum Model (RSI, VWAP, volume, trend)

Self-improving via:
- Bayesian weight updates from trade outcomes
- Regime-specific performance tracking
- Walk-forward optimization
- Adaptive threshold adjustment
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ModelWeight:
    """Weight for one sub-model in the ensemble."""
    name: str
    base_weight: float
    current_weight: float
    regime_weights: dict[str, float] = field(default_factory=dict)
    total_predictions: int = 0
    correct_predictions: int = 0
    recent_pnl: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct_predictions / max(self.total_predictions, 1)

    def update(self, correct: bool, pnl: float, regime: str) -> None:
        self.total_predictions += 1
        if correct:
            self.correct_predictions += 1
        self.recent_pnl += pnl
        # Bayesian update with decay
        decay = 0.95
        if self.total_predictions > 5:
            performance = 1.0 if correct else 0.0
            self.current_weight = self.current_weight * decay + performance * (1 - decay)
            self.current_weight = max(0.1, min(0.6, self.current_weight))
        # Track regime-specific performance
        if regime not in self.regime_weights:
            self.regime_weights[regime] = self.base_weight
        regime_perf = 1.0 if correct else 0.0
        self.regime_weights[regime] = self.regime_weights[regime] * 0.9 + regime_perf * 0.1


@dataclass
class EnsembleScore:
    """Final ensemble prediction."""
    direction: str  # 'long' or 'short'
    confidence: float
    microstructure_score: float
    ict_score: float
    momentum_score: float
    regime: str
    weights_used: dict[str, float]
    reasons: list[str]


class EnsembleModel:
    """
    3-model ensemble with regime-aware weighting and adaptive learning.
    
    Each sub-model produces a directional score [0, 1] where:
    - 0.0 = strong short signal
    - 0.5 = neutral
    - 1.0 = strong long signal
    
    The ensemble blends them with regime-dependent weights.
    """

    def __init__(self) -> None:
        # Default weights (equal blend)
        self.models = {
            'microstructure': ModelWeight('microstructure', 0.35, 0.35),
            'ict': ModelWeight('ict', 0.35, 0.35),
            'momentum': ModelWeight('momentum', 0.30, 0.30),
        }
        
        # Regime-specific default weights
        self._regime_defaults = {
            'trending': {'microstructure': 0.30, 'ict': 0.40, 'momentum': 0.30},
            'trending_volatile': {'microstructure': 0.25, 'ict': 0.35, 'momentum': 0.40},
            'range_bound': {'microstructure': 0.40, 'ict': 0.30, 'momentum': 0.30},
            'consolidation': {'microstructure': 0.45, 'ict': 0.25, 'momentum': 0.30},
            'accumulation': {'microstructure': 0.35, 'ict': 0.45, 'momentum': 0.20},
            'distribution': {'microstructure': 0.35, 'ict': 0.45, 'momentum': 0.20},
        }
        
        # Performance tracking
        self.trade_history: deque = deque(maxlen=500)
        self.daily_stats: dict[str, dict] = {}
        self._last_optimization: float = 0
        self._optimization_interval: float = 3600  # 1 hour
        
        # Adaptive thresholds
        self.min_confidence: float = 0.55
        self.min_edge: float = 0.08
        
        # Load saved state
        self._load_state()

    def score_microstructure(
        self,
        order_flow: Any,
        vwap: Any,
        oi: Any,
        funding: Any,
        price: float,
        regime: str,
    ) -> tuple[float, list[str]]:
        """Microstructure model: order flow, OBI, CVD, funding, OI."""
        score = 0.5
        reasons: list[str] = []

        # Order Flow (strongest microstructure signal)
        if order_flow:
            delta = getattr(order_flow, 'delta', 0)
            cvd_slope = getattr(order_flow, 'cvd_slope', 0)
            footprint = getattr(order_flow, 'footprint_imbalance', 0.5)
            
            if delta > 0:
                score += 0.12; reasons.append("OF delta bullish")
            elif delta < 0:
                score -= 0.12; reasons.append("OF delta bearish")
            
            if cvd_slope > 0:
                score += 0.08; reasons.append("CVD rising")
            elif cvd_slope < 0:
                score -= 0.08; reasons.append("CVD falling")
            
            if footprint > 0.65:
                score += 0.06; reasons.append("Footprint bullish imbalance")
            elif footprint < 0.35:
                score -= 0.06; reasons.append("Footprint bearish imbalance")

        # VWAP position
        if vwap:
            dev = getattr(vwap, 'price_deviation_pct', 0)
            compressed = getattr(vwap, 'is_compressed', False)
            lower = getattr(vwap, 'lower_band_1sd', 0)
            upper = getattr(vwap, 'upper_band_1sd', 0)
            
            if price < lower:
                score += 0.08; reasons.append("Below VWAP lower band")
            elif price > upper:
                score -= 0.08; reasons.append("Above VWAP upper band")
            elif dev < -1.0:
                score += 0.04; reasons.append("Below VWAP")
            elif dev > 1.0:
                score -= 0.04; reasons.append("Above VWAP")
            
            if compressed:
                reasons.append("VWAP compressed (breakout imminent)")

        # Open Interest dynamics
        if oi:
            change = getattr(oi, 'oi_change_pct', 0)
            trend = getattr(oi, 'oi_trend', 'neutral')
            momentum = getattr(oi, 'momentum_confirmation', False)
            
            if momentum and change > 0:
                score += 0.06; reasons.append("OI momentum bullish")
            elif momentum and change < 0:
                score -= 0.06; reasons.append("OI momentum bearish")
            
            if trend == 'increasing':
                score += 0.03; reasons.append("OI increasing")
            elif trend == 'decreasing':
                score -= 0.03; reasons.append("OI decreasing")

        # Funding rate contrarian
        if funding:
            bias = getattr(funding, 'contrarian_bias', 'neutral')
            extreme = getattr(funding, 'is_extreme', False)
            
            if bias == 'bullish':
                score += 0.08; reasons.append("Funding contrarian bullish")
            elif bias == 'bearish':
                score -= 0.08; reasons.append("Funding contrarian bearish")
            
            if extreme:
                reasons.append("Funding extreme (reversal likely)")

        return max(0.0, min(1.0, score)), reasons

    def score_ict(
        self,
        fvgs: list | None,
        order_blocks: list | None,
        sweeps: list | None,
        regime_obj: Any,
        price: float,
        regime: str,
        candles: list | None = None,
    ) -> tuple[float, list[str]]:
        """ICT model: FVGs, order blocks, liquidity sweeps, structure."""
        score = 0.5
        reasons: list[str] = []

        # Fair Value Gaps
        if fvgs:
            bullish_fvgs = [f for f in fvgs if not getattr(f, 'is_filled', False) and getattr(f, 'direction', '') == 'bullish']
            bearish_fvgs = [f for f in fvgs if not getattr(f, 'is_filled', False) and getattr(f, 'direction', '') == 'bearish']
            
            for f in bullish_fvgs:
                bottom = getattr(f, 'bottom', 0)
                if bottom > 0 and abs(price - bottom) / price < 0.003:
                    score += 0.10; reasons.append("At bullish FVG support")
                    break
            
            for f in bearish_fvgs:
                top = getattr(f, 'top', 0)
                if top > 0 and abs(price - top) / price < 0.003:
                    score -= 0.10; reasons.append("At bearish FVG resistance")
                    break

        # Order Blocks
        if order_blocks:
            bullish_obs = [o for o in order_blocks if not getattr(o, 'is_breaker', False) and getattr(o, 'direction', '') == 'bullish']
            bearish_obs = [o for o in order_blocks if not getattr(o, 'is_breaker', False) and getattr(o, 'direction', '') == 'bearish']
            
            for o in bullish_obs:
                top = getattr(o, 'top', 0)
                if top > 0 and abs(price - top) / price < 0.003:
                    score += 0.08; reasons.append("At bullish OB")
                    break
            
            for o in bearish_obs:
                bottom = getattr(o, 'bottom', 0)
                if bottom > 0 and abs(price - bottom) / price < 0.003:
                    score -= 0.08; reasons.append("At bearish OB")
                    break

        # Liquidity Sweeps
        if sweeps:
            for s in sweeps:
                side = getattr(s, 'side', '')
                reclaimed = getattr(s, 'reclaimed', False)
                entry_trigger = getattr(s, 'entry_trigger', False)
                
                if side == 'long' and reclaimed and entry_trigger:
                    score += 0.12; reasons.append("Bullish sweep reclaimed")
                    break
                elif side == 'short' and reclaimed and entry_trigger:
                    score -= 0.12; reasons.append("Bearish sweep reclaimed")
                    break

        # Regime context
        if regime_obj:
            phase = getattr(regime_obj, 'phase', '')
            bias = getattr(regime_obj, 'bias', 'neutral')
            
            if phase == 'trending' and bias == 'bullish':
                score += 0.08; reasons.append("Trending bullish regime")
            elif phase == 'trending' and bias == 'bearish':
                score -= 0.08; reasons.append("Trending bearish regime")
            elif phase == 'accumulation':
                score += 0.05; reasons.append("Accumulation (bullish)")
            elif phase == 'distribution':
                score -= 0.05; reasons.append("Distribution (bearish)")

        return max(0.0, min(1.0, score)), reasons

    def score_momentum(
        self,
        rsi_3: float,
        candles: list | None,
        kill_active: bool,
        kill_session: str,
        metrics: Any,
        wick: Any = None,
    ) -> tuple[float, list[str]]:
        """Momentum model: RSI, trend, volume, killzone, wick rejection."""
        score = 0.5
        reasons: list[str] = []

        # RSI(3) - strongest momentum signal
        if rsi_3 < 25:
            score += 0.15; reasons.append(f"RSI(3) {rsi_3:.0f} extreme oversold")
        elif rsi_3 < 35:
            score += 0.10; reasons.append(f"RSI(3) {rsi_3:.0f} oversold")
        elif rsi_3 < 45:
            score += 0.04; reasons.append(f"RSI(3) {rsi_3:.0f} recovery zone")
        elif rsi_3 > 75:
            score -= 0.15; reasons.append(f"RSI(3) {rsi_3:.0f} extreme overbought")
        elif rsi_3 > 65:
            score -= 0.10; reasons.append(f"RSI(3) {rsi_3:.0f} overbought")
        elif rsi_3 > 55:
            score -= 0.04; reasons.append(f"RSI(3) {rsi_3:.0f} rejection zone")

        # Candle trend alignment
        if candles and len(candles) >= 20:
            closes = [c.close for c in candles]
            # EMA trend
            ema8 = self._ema(closes, 8)
            ema21 = self._ema(closes, 21)
            ema50 = self._ema(closes, min(50, len(closes) - 1))
            
            if ema8 > ema21 > ema50:
                score += 0.10; reasons.append("EMA bullish alignment")
            elif ema8 < ema21 < ema50:
                score -= 0.10; reasons.append("EMA bearish alignment")
            
            # Recent momentum
            if len(closes) >= 10:
                recent_return = (closes[-1] - closes[-10]) / closes[-10] * 100
                if recent_return > 1.0:
                    score += 0.06; reasons.append(f"Bullish momentum +{recent_return:.1f}%")
                elif recent_return < -1.0:
                    score -= 0.06; reasons.append(f"Bearish momentum {recent_return:.1f}%")
            
            # Volume confirmation
            if len(candles) >= 20:
                recent_vol = np.mean([c.volume for c in candles[-5:]])
                base_vol = np.mean([c.volume for c in candles[-20:-5]])
                if base_vol > 0:
                    vol_ratio = recent_vol / base_vol
                    if vol_ratio > 1.5:
                        score += 0.05; reasons.append(f"Volume surge {vol_ratio:.1f}x")
                    elif vol_ratio < 0.4:
                        reasons.append(f"Volume collapse {vol_ratio:.1f}x")

        # Killzone timing
        if kill_active:
            score += 0.05; reasons.append(f"Killzone: {kill_session}")

        # Wick rejection
        if wick:
            bull = getattr(wick, 'bullish_rejection_active', False)
            bear = getattr(wick, 'bearish_rejection_active', False)
            strength = getattr(wick, 'rejection_strength', 0)
            
            if bull:
                score += abs(strength) * 0.08; reasons.append("Bullish wick rejection")
            elif bear:
                score -= abs(strength) * 0.08; reasons.append("Bearish wick rejection")

        # Market metrics trend
        if metrics:
            trend = getattr(metrics, 'trend_score', 0) or 0
            if trend > 0.15:
                score += 0.05; reasons.append("Metrics trend bullish")
            elif trend < -0.15:
                score -= 0.05; reasons.append("Metrics trend bearish")

        return max(0.0, min(1.0, score)), reasons

    def combine(
        self,
        micro_score: float,
        ict_score: float,
        momentum_score: float,
        regime: str,
        micro_reasons: list[str],
        ict_reasons: list[str],
        momentum_reasons: list[str],
    ) -> EnsembleScore:
        """Combine sub-model scores with regime-aware weighting."""
        # Get regime-specific weights
        weights = self._regime_defaults.get(regime, {
            'microstructure': 0.35, 'ict': 0.35, 'momentum': 0.30,
        })
        
        # Override with learned weights if available
        for name, model in self.models.items():
            if regime in model.regime_weights:
                weights[name] = model.regime_weights[regime]
        
        # Normalize weights
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}
        
        # Weighted blend
        combined = (
            micro_score * weights.get('microstructure', 0.35) +
            ict_score * weights.get('ict', 0.35) +
            momentum_score * weights.get('momentum', 0.30)
        )
        
        # Determine direction
        direction = 'long' if combined > 0.5 else 'short'
        confidence = abs(combined - 0.5) * 2  # Map [0,1] to [0,1] confidence
        
        # Combine reasons
        all_reasons = []
        if micro_reasons:
            all_reasons.extend([f"[OF] {r}" for r in micro_reasons[:3]])
        if ict_reasons:
            all_reasons.extend([f"[ICT] {r}" for r in ict_reasons[:3]])
        if momentum_reasons:
            all_reasons.extend([f"[MOM] {r}" for r in momentum_reasons[:3]])
        
        return EnsembleScore(
            direction=direction,
            confidence=confidence,
            microstructure_score=micro_score,
            ict_score=ict_score,
            momentum_score=momentum_score,
            regime=regime,
            weights_used=weights,
            reasons=all_reasons,
        )

    def record_outcome(
        self,
        score: EnsembleScore,
        won: bool,
        pnl_pct: float,
    ) -> None:
        """Record trade outcome and update model weights."""
        correct = (won and score.direction == 'long' and pnl_pct > 0) or \
                  (won and score.direction == 'short' and pnl_pct > 0)
        
        for name, model in self.models.items():
            model.update(correct, pnl_pct, score.regime)
        
        self.trade_history.append({
            'timestamp': int(time.time() * 1000),
            'direction': score.direction,
            'regime': score.regime,
            'confidence': score.confidence,
            'won': won,
            'pnl_pct': pnl_pct,
            'weights': score.weights_used,
        })
        
        # Auto-optimize periodically
        if time.time() - self._last_optimization > self._optimization_interval:
            self._optimize_weights()
            self._last_optimization = time.time()
            self._save_state()

    def _optimize_weights(self) -> None:
        """Optimize model weights based on recent performance."""
        if len(self.trade_history) < 20:
            return
        
        recent = list(self.trade_history)[-50:]
        
        # Calculate per-regime performance
        regime_trades: dict[str, list] = {}
        for t in recent:
            r = t.get('regime', 'unknown')
            if r not in regime_trades:
                regime_trades[r] = []
            regime_trades[r].append(t)
        
        for regime, trades in regime_trades.items():
            if len(trades) < 5:
                continue
            
            # Simple Bayesian optimization: increase weight for models that
            # contributed to winning trades
            win_rate = sum(1 for t in trades if t['won']) / len(trades)
            
            if win_rate > 0.55:
                # Good regime - slightly increase all weights proportionally
                for name in self.models:
                    self.models[name].regime_weights[regime] = \
                        self.models[name].regime_weights.get(regime, 0.33) * 1.05
            elif win_rate < 0.45:
                # Bad regime - reduce momentum weight, increase microstructure
                self.models['microstructure'].regime_weights[regime] = \
                    self.models['microstructure'].regime_weights.get(regime, 0.33) * 1.1
                self.models['momentum'].regime_weights[regime] = \
                    self.models['momentum'].regime_weights.get(regime, 0.33) * 0.9
            
            # Normalize
            total = sum(self.models[n].regime_weights.get(regime, 0.33) for n in self.models)
            if total > 0:
                for name in self.models:
                    self.models[name].regime_weights[regime] /= total

    def get_stats(self) -> dict:
        """Get ensemble performance statistics."""
        total = len(self.trade_history)
        if total == 0:
            return {'total_trades': 0, 'win_rate': 0, 'avg_pnl': 0}
        
        wins = sum(1 for t in self.trade_history if t['won'])
        pnl = sum(t['pnl_pct'] for t in self.trade_history)
        
        return {
            'total_trades': total,
            'win_rate': round(wins / total, 4),
            'total_pnl_pct': round(pnl, 4),
            'avg_pnl_per_trade': round(pnl / total, 4),
            'model_weights': {n: round(m.current_weight, 4) for n, m in self.models.items()},
            'regime_weights': {
                n: {r: round(w, 4) for r, w in m.regime_weights.items()}
                for n, m in self.models.items()
            },
        }

    def _save_state(self) -> None:
        """Save ensemble state to disk."""
        state = {
            'models': {
                name: {
                    'base_weight': m.base_weight,
                    'current_weight': m.current_weight,
                    'regime_weights': m.regime_weights,
                    'total_predictions': m.total_predictions,
                    'correct_predictions': m.correct_predictions,
                    'recent_pnl': m.recent_pnl,
                }
                for name, m in self.models.items()
            },
            'min_confidence': self.min_confidence,
            'min_edge': self.min_edge,
            'trade_history': list(self.trade_history)[-100:],
        }
        path = 'data/ensemble_state.json'
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(state, f, indent=2, default=str)

    def _load_state(self) -> None:
        """Load ensemble state from disk."""
        path = 'data/ensemble_state.json'
        try:
            with open(path) as f:
                state = json.load(f)
            for name, data in state.get('models', {}).items():
                if name in self.models:
                    self.models[name].base_weight = data.get('base_weight', 0.33)
                    self.models[name].current_weight = data.get('current_weight', 0.33)
                    self.models[name].regime_weights = data.get('regime_weights', {})
                    self.models[name].total_predictions = data.get('total_predictions', 0)
                    self.models[name].correct_predictions = data.get('correct_predictions', 0)
                    self.models[name].recent_pnl = data.get('recent_pnl', 0)
            self.min_confidence = state.get('min_confidence', 0.55)
            self.min_edge = state.get('min_edge', 0.08)
            for t in state.get('trade_history', []):
                self.trade_history.append(t)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2.0 / (period + 1)
        r = values[0]
        for v in values[1:]:
            r = (v - r) * k + r
        return r


# Singleton
ensemble = EnsembleModel()
