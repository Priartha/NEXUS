"""
NEXUS Dynamic Threshold Engine v1.0

Replaces ALL static thresholds with learned, market-adaptive parameters.
Every threshold learns from historical trade outcomes, adapting per regime,
volatility state, and recent performance.

Philosophy: Markets are not governed by static rules. Neither is this engine.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class FactorWeight:
    name: str
    base_weight: float
    current_weight: float
    total_signals: int = 0
    correct_signals: int = 0
    regime_weights: dict[str, float] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        return self.correct_signals / max(self.total_signals, 1)

    def update(self, correct: bool, regime: str) -> None:
        self.total_signals += 1
        if correct:
            self.correct_signals += 1
        alpha = 0.15
        perf = 1.0 if correct else 0.0
        self.current_weight = self.current_weight * (1 - alpha) + perf * alpha
        self.current_weight = max(0.05, min(0.95, self.current_weight))
        if regime not in self.regime_weights:
            self.regime_weights[regime] = self.base_weight
        self.regime_weights[regime] = self.regime_weights[regime] * 0.85 + perf * 0.15


class DynamicThresholds:
    """
    All thresholds are adaptive — nothing is hardcoded beyond initial defaults.
    Learns from every trade outcome to continuously refine decision boundaries.
    """

    def __init__(self) -> None:
        self._atr_window: deque[float] = deque(maxlen=100)
        self._volume_window: deque[float] = deque(maxlen=100)
        self._volatility_window: deque[float] = deque(maxlen=50)
        self._win_rate_window: deque[bool] = deque(maxlen=50)
        self._trade_outcomes: deque[dict] = deque(maxlen=500)

        self.momentum_strong = 0.55
        self.momentum_moderate = 0.12
        self.min_confidence = 0.55
        self.min_edge = 0.08
        self.signal_cooldown_ms = 45_000
        self.sl_base_mult = 2.0
        self.tp_base_mult = 3.0

        self.regime_params: dict[str, dict] = {}

        self.factor_weights: dict[str, FactorWeight] = {
            'order_flow_delta': FactorWeight('order_flow_delta', 0.12, 0.12),
            'order_flow_cvd': FactorWeight('order_flow_cvd', 0.08, 0.08),
            'order_flow_footprint': FactorWeight('order_flow_footprint', 0.05, 0.05),
            'vwap': FactorWeight('vwap', 0.12, 0.12),
            'open_interest': FactorWeight('open_interest', 0.12, 0.12),
            'funding_rate': FactorWeight('funding_rate', 0.10, 0.10),
            'liquidity_sweeps': FactorWeight('liquidity_sweeps', 0.15, 0.15),
            'volume_profile': FactorWeight('volume_profile', 0.07, 0.07),
            'rsi_3': FactorWeight('rsi_3', 0.07, 0.07),
            'killzone': FactorWeight('killzone', 0.05, 0.05),
            'fvg': FactorWeight('fvg', 0.05, 0.05),
            'order_block': FactorWeight('order_block', 0.05, 0.05),
            'regime_bias': FactorWeight('regime_bias', 0.05, 0.05),
            'trend_score': FactorWeight('trend_score', 0.03, 0.03),
            'futures_funding': FactorWeight('futures_funding', 0.06, 0.06),
            'futures_oi': FactorWeight('futures_oi', 0.04, 0.04),
            'wick_rejection': FactorWeight('wick_rejection', 0.08, 0.08),
        }

        self._last_learning_update: float = -600  # First learning fires immediately
        self._last_learning_trade_count: int = 0
        self._learning_interval: float = 300
        self._min_trades_for_learning: int = 5
        self._min_new_trades_for_learning: int = 5

        self._time_between_signals: deque[float] = deque(maxlen=20)
        self._avg_signal_interval: float = 300_000

        self._load_state()

    def update_market_stats(self, atr: float, volume: float, volatility: float) -> None:
        if atr > 0:
            self._atr_window.append(atr)
        if volume > 0:
            self._volume_window.append(volume)
        if volatility > 0:
            self._volatility_window.append(volatility)

    def record_trade_outcome(self, trade: dict) -> None:
        self._trade_outcomes.append(trade)
        self._win_rate_window.append(trade.get('won', False))

        if 'signal_interval_ms' in trade:
            self._time_between_signals.append(trade['signal_interval_ms'])

        if 'factor_accuracies' in trade:
            for factor_name, correct in trade['factor_accuracies'].items():
                if factor_name in self.factor_weights:
                    self.factor_weights[factor_name].update(
                        correct, trade.get('regime', 'unknown')
                    )

        if len(self._win_rate_window) >= self._min_trades_for_learning:
            now = time.time()
            new_trades_count = len(self._trade_outcomes) - self._last_learning_trade_count
            time_elapsed = now - self._last_learning_update
            if new_trades_count >= self._min_new_trades_for_learning or time_elapsed >= self._learning_interval:
                self._learn_thresholds()
                self._last_learning_update = now
                self._last_learning_trade_count = len(self._trade_outcomes)

    def _learn_thresholds(self) -> None:
        if len(self._trade_outcomes) < self._min_trades_for_learning:
            return

        trades = list(self._trade_outcomes)
        recent = trades[-min(100, len(trades)):]

        confidences = [t.get('confidence', 0.5) for t in recent]
        wins = [t.get('won', False) for t in recent]

        if len(confidences) >= 10:
            best_threshold = 0.50
            best_win_rate = 0.0
            for thresh in [x / 100 for x in range(25, 85, 5)]:
                above = [w for c, w in zip(confidences, wins) if c >= thresh]
                if above:
                    wr = sum(above) / len(above)
                    if wr > best_win_rate and len(above) >= 3:
                        best_win_rate = wr
                        best_threshold = thresh

            alpha = 0.25
            self.min_confidence = self.min_confidence * (1 - alpha) + best_threshold * alpha
            self.min_confidence = max(0.25, min(0.85, self.min_confidence))

        strong_trades = [t for t in recent if t.get('momentum_strength', 0) > 0.2]
        if len(strong_trades) >= 5:
            strong_wins_wr = [t for t in strong_trades if t.get('won', False)]
            strong_losses_wr = [t for t in strong_trades if not t.get('won', False)]

            if strong_wins_wr and strong_losses_wr:
                avg_win_s = np.mean([t.get('momentum_strength', 0) for t in strong_wins_wr])
                if avg_win_s > 0:
                    optimal = max(0.25, avg_win_s - 0.1)
                    alpha = 0.2
                    self.momentum_strong = self.momentum_strong * (1 - alpha) + optimal * alpha
                    self.momentum_strong = max(0.25, min(0.90, self.momentum_strong))

        if len(self._time_between_signals) >= 5:
            intervals = list(self._time_between_signals)
            self._avg_signal_interval = float(np.mean(intervals))
            optimal_cooldown = self._avg_signal_interval * 0.3
            optimal_cooldown = max(10_000, min(360_000, optimal_cooldown))
            alpha = 0.2
            self.signal_cooldown_ms = int(
                self.signal_cooldown_ms * (1 - alpha) + optimal_cooldown * alpha
            )

        if len(self._atr_window) >= 10:
            recent_atrs = list(self._atr_window)[-20:]
            atr_mean = float(np.mean(recent_atrs))
            atr_std = float(np.std(recent_atrs)) if len(recent_atrs) > 1 else atr_mean * 0.5
            current_wr = sum(wins) / max(len(wins), 1)

            if current_wr < 0.40 and len(wins) >= 10:
                self.sl_base_mult = min(4.5, self.sl_base_mult * 1.08)
            elif current_wr > 0.65:
                self.sl_base_mult = max(1.2, self.sl_base_mult * 0.95)

            if atr_std > 0 and atr_mean > 0:
                vol_ratio = atr_std / atr_mean if atr_mean > 0 else 0.5
                if vol_ratio > 0.5:
                    self.sl_base_mult = min(4.5, self.sl_base_mult * (1 + vol_ratio * 0.1))

        for regime in set(t.get('regime', 'unknown') for t in recent):
            regime_trades = [t for t in recent if t.get('regime') == regime]
            if len(regime_trades) >= 5:
                regime_wr = sum(1 for t in regime_trades if t.get('won', False)) / len(regime_trades)

                if regime not in self.regime_params:
                    self.regime_params[regime] = {
                        'min_confidence': 0.55,
                        'min_edge': 0.08,
                        'win_rate': 0.5,
                        'trades': 0,
                    }

                rp = self.regime_params[regime]
                rp['trades'] = len(regime_trades)
                rp['win_rate'] = regime_wr

                if regime_wr < 0.40:
                    rp['min_confidence'] = min(0.80, rp['min_confidence'] + 0.04)
                    rp['min_edge'] = min(0.18, rp['min_edge'] + 0.02)
                elif regime_wr > 0.62:
                    rp['min_confidence'] = max(0.35, rp['min_confidence'] - 0.02)
                    rp['min_edge'] = max(0.02, rp['min_edge'] - 0.01)

        self._save_state()

    def get_momentum_thresholds(self, regime: str | None = None) -> dict:
        strong = self.momentum_strong
        moderate = self.momentum_moderate

        if regime and regime in self.regime_params:
            rp = self.regime_params[regime]
            if rp['win_rate'] < 0.40:
                strong += 0.10
                moderate += 0.05
            elif rp['win_rate'] > 0.60:
                strong -= 0.05
                moderate -= 0.02

        return {
            'strong': max(0.20, min(0.95, strong)),
            'moderate': max(0.05, min(0.50, moderate)),
        }

    def get_confidence_threshold(self, regime: str | None = None, atr_pct: float = 0.0) -> float:
        base = self.min_confidence
        if regime and regime in self.regime_params:
            base = self.regime_params[regime].get('min_confidence', base)
        if atr_pct > 0.03:
            base -= 0.05
        elif atr_pct < 0.01:
            base += 0.03
        return max(0.25, min(0.88, base))

    def get_edge_threshold(self, regime: str | None = None) -> float:
        base = self.min_edge
        if regime and regime in self.regime_params:
            base = self.regime_params[regime].get('min_edge', base)
        return max(0.01, min(0.22, base))

    def get_cooldown_ms(self) -> int:
        return self.signal_cooldown_ms

    def get_sltp_multipliers(self, regime: str | None = None, confidence: float = 0.5) -> dict:
        sl = self.sl_base_mult
        tp = self.tp_base_mult

        if regime == 'trending':
            sl *= 1.2; tp *= 1.3
        elif regime == 'trending_volatile':
            sl *= 1.4; tp *= 1.2
        elif regime in ('range_bound', 'consolidation'):
            sl *= 0.8; tp *= 0.7
        elif regime in ('accumulation', 'distribution'):
            sl *= 1.0; tp *= 1.0

        if confidence > 0.65:
            sl *= 0.9; tp *= 1.2
        elif confidence < 0.45:
            sl *= 1.2; tp *= 0.8

        return {'sl_mult': max(1.0, min(5.5, sl)), 'tp_mult': max(1.0, min(8.0, tp))}

    def get_factor_weights(self, regime: str | None = None) -> dict[str, float]:
        weights = {}
        for name, fw in self.factor_weights.items():
            if regime and regime in fw.regime_weights:
                weights[name] = fw.regime_weights[regime]
            else:
                weights[name] = fw.current_weight
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        return weights

    def should_block_regime(self, regime: str) -> tuple[bool, str]:
        if regime not in self.regime_params:
            if regime in ('consolidation',):
                return True, f"No data for {regime} — conservatively blocking"
            return False, ""

        rp = self.regime_params[regime]
        if rp['trades'] < 5:
            return False, ""

        wr = rp['win_rate']
        if wr < 0.30 and rp['trades'] >= 10:
            return True, f"{regime}: {wr:.0%} WR over {rp['trades']} trades — blocking"

        return False, ""

    def get_regime_advice(self, regime: str) -> dict:
        if regime not in self.regime_params:
            return {'action': 'default', 'notes': 'No data yet'}

        rp = self.regime_params[regime]
        if rp['trades'] < 5:
            return {'action': 'default', 'notes': f'Only {rp["trades"]} trades observed'}

        wr = rp['win_rate']

        if regime == 'range_bound':
            if wr > 0.55:
                return {'action': 'fade_extremes', 'notes': f'Fading works ({wr:.0%} WR)'}
            return {'action': 'wait_for_breakout', 'notes': f'Fading failing ({wr:.0%} WR)'}

        if regime == 'consolidation':
            if wr > 0.55:
                return {'action': 'trade_breakout', 'notes': f'Breakouts working ({wr:.0%} WR)'}
            return {'action': 'wait_for_expansion', 'notes': f'Consolidation losing ({wr:.0%} WR)'}

        if regime in ('trending', 'trending_volatile'):
            if wr > 0.60:
                return {'action': 'aggressive_trend', 'notes': f'Trend winning ({wr:.0%} WR)'}
            return {'action': 'conservative_trend', 'notes': f'Trend struggling ({wr:.0%} WR)'}

        return {'action': 'default', 'notes': f'{wr:.0%} WR over {rp["trades"]} trades'}

    def get_status(self) -> dict:
        return {
            'momentum_strong': round(self.momentum_strong, 3),
            'momentum_moderate': round(self.momentum_moderate, 3),
            'min_confidence': round(self.min_confidence, 3),
            'min_edge': round(self.min_edge, 4),
            'signal_cooldown_ms': self.signal_cooldown_ms,
            'sl_base_mult': round(self.sl_base_mult, 2),
            'tp_base_mult': round(self.tp_base_mult, 2),
            'avg_signal_interval_ms': int(self._avg_signal_interval),
            'trades_learned': len(self._trade_outcomes),
            'recent_win_rate': round(
                sum(self._win_rate_window) / max(len(self._win_rate_window), 1), 3
            ) if self._win_rate_window else 0,
            'regime_params': self.regime_params,
        }

    def _save_state(self) -> None:
        state = {
            'momentum_strong': self.momentum_strong,
            'momentum_moderate': self.momentum_moderate,
            'min_confidence': self.min_confidence,
            'min_edge': self.min_edge,
            'signal_cooldown_ms': self.signal_cooldown_ms,
            'sl_base_mult': self.sl_base_mult,
            'tp_base_mult': self.tp_base_mult,
            'regime_params': self.regime_params,
            'avg_signal_interval': self._avg_signal_interval,
            'factor_weights': {
                name: {
                    'current_weight': fw.current_weight,
                    'regime_weights': fw.regime_weights,
                }
                for name, fw in self.factor_weights.items()
            },
        }
        path = 'data/dynamic_thresholds.json'
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(state, f, indent=2, default=str)

    def _load_state(self) -> None:
        path = 'data/dynamic_thresholds.json'
        try:
            with open(path) as f:
                state = json.load(f)
            self.momentum_strong = state.get('momentum_strong', 0.55)
            self.momentum_moderate = state.get('momentum_moderate', 0.12)
            self.min_confidence = state.get('min_confidence', 0.55)
            self.min_edge = state.get('min_edge', 0.08)
            self.signal_cooldown_ms = state.get('signal_cooldown_ms', 45000)
            self.sl_base_mult = state.get('sl_base_mult', 2.0)
            self.tp_base_mult = state.get('tp_base_mult', 3.0)
            self.regime_params = state.get('regime_params', {})
            self._avg_signal_interval = state.get('avg_signal_interval', 300000)
            for name, data in state.get('factor_weights', {}).items():
                if name in self.factor_weights:
                    self.factor_weights[name].current_weight = data.get('current_weight', self.factor_weights[name].current_weight)
                    self.factor_weights[name].regime_weights = data.get('regime_weights', {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass


dynamic_thresholds = DynamicThresholds()
