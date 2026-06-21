"""
NEXUS Self-Optimization Engine v1.0

Walk-forward self-optimization that:
1. Analyzes recent trade performance
2. Proposes parameter adjustments
3. Backtests changes on recent data
4. Keeps improvements, reverts failures
5. Adapts thresholds based on market conditions

Inspired by ATLAS and El Oraculo systems.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np


@dataclass
class OptimizationAttempt:
    """Record of one optimization attempt."""
    timestamp: int
    params_before: dict
    params_after: dict
    backtest_result: dict
    improvement: float
    kept: bool
    reason: str


class SelfOptimizationEngine:
    """
    Walk-forward self-optimization loop:
    - Every N hours, analyze performance
    - Propose parameter tweaks
    - Backtest on recent window
    - Keep if improved, revert if not
    """
    
    def __init__(self) -> None:
        self.state_version = 2
        self.attempts: deque[OptimizationAttempt] = deque(maxlen=200)
        self._last_optimization: float = 0
        self._optimization_interval: float = 3600  # 1 hour (faster adaptation)
        self._min_trades_for_optimization: int = 5
        
        # Current adaptive parameters
        self.params = {
            'min_confidence': 0.55,
            'min_edge': 0.08,
            'sl_multiplier_base': 2.0,
            'tp_multiplier_base': 3.0,
            'cooldown_minutes': 5,
            'max_hold_minutes': 25,
            'risk_per_trade_pct': 0.02,
        }
        
        # Performance tracking
        self.performance_window: deque = deque(maxlen=200)
        self.regime_performance: dict[str, dict] = {}
        
        # Load saved state
        self._load_state()

    def bootstrap_history(self, n_trades: int = 50) -> int:
        """Do not synthesize optimizer history.

        Kept as a no-op compatibility shim for older callers. The optimizer
        must learn only from real closed trades.
        """
        return 0

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade for optimization analysis."""
        self.performance_window.append({
            'timestamp': int(time.time() * 1000),
            'direction': trade.get('direction', 'unknown'),
            'regime': trade.get('regime', 'unknown'),
            'confidence': trade.get('confidence', 0),
            'pnl_pct': trade.get('pnl_pct', 0),
            'won': trade.get('won', False),
            'hold_minutes': trade.get('hold_minutes', 0),
            'entry_price': trade.get('entry_price', 0),
            'exit_price': trade.get('exit_price', 0),
        })
        
        # Update regime stats
        regime = trade.get('regime', 'unknown')
        if regime not in self.regime_performance:
            self.regime_performance[regime] = {
                'trades': 0, 'wins': 0, 'total_pnl': 0,
                'avg_confidence': 0, 'avg_hold': 0,
            }
        rp = self.regime_performance[regime]
        rp['trades'] += 1
        if trade.get('won'):
            rp['wins'] += 1
        rp['total_pnl'] += trade.get('pnl_pct', 0)
        n = rp['trades']
        rp['avg_confidence'] = (rp['avg_confidence'] * (n - 1) + trade.get('confidence', 0)) / n
        rp['avg_hold'] = (rp['avg_hold'] * (n - 1) + trade.get('hold_minutes', 0)) / n

    def should_optimize(self) -> bool:
        """Check if enough time has passed and enough data exists."""
        if time.time() - self._last_optimization < self._optimization_interval:
            return False
        if len(self.performance_window) < self._min_trades_for_optimization:
            return False
        return True

    def run_optimization(self) -> dict:
        """
        Run one optimization cycle:
        1. Analyze current performance
        2. Identify weaknesses
        3. Propose parameter changes
        4. Evaluate if changes are likely to help
        5. Apply improvements
        """
        if not self.should_optimize():
            return {'status': 'skipped', 'reason': 'not_ready'}
        
        self._last_optimization = time.time()
        
        # 1. Analyze current performance
        analysis = self._analyze_performance()
        
        # 2. Identify weaknesses
        weaknesses = self._identify_weaknesses(analysis)
        
        # 3. Propose changes
        proposed = self._propose_changes(analysis, weaknesses)
        
        # 4. Evaluate (simplified backtest on recent window)
        result = self._evaluate_changes(proposed, analysis)
        
        # 5. Apply or revert
        if result['improvement'] > 0:
            params_before = self.params.copy()
            self.params.update(proposed)
            self.attempts.append(OptimizationAttempt(
                timestamp=int(time.time() * 1000),
                params_before=params_before,
                params_after=proposed,
                backtest_result=result,
                improvement=result['improvement'],
                kept=True,
                reason=f"Improved by {result['improvement']:.4f}",
            ))
            self._save_state()
            return {'status': 'applied', 'improvement': result['improvement'], 'changes': proposed}
        else:
            self.attempts.append(OptimizationAttempt(
                timestamp=int(time.time() * 1000),
                params_before=self.params.copy(),
                params_after=proposed,
                backtest_result=result,
                improvement=result['improvement'],
                kept=False,
                reason=f"No improvement ({result['improvement']:.4f})",
            ))
            return {'status': 'reverted', 'improvement': result['improvement']}

    def optimize_on_close(self, trade: dict) -> dict:
        """Run lightweight optimization on every trade close.

        Adjusts parameters in-place based on the latest trade outcome
        to keep signals in tune with current market conditions. Returns the
        result of the optimization run (or skipped if no changes needed).
        """
        if len(self.performance_window) < 3:
            return {'status': 'skipped', 'reason': 'insufficient_data'}

        # Check if we should optimize: either time interval passed OR enough new trades
        recent_closes = [t for t in list(self.performance_window)[-3:] if t.get('won') is not None]
        recent_losses = sum(1 for t in recent_closes if not t.get('won'))
        if recent_losses >= 2:
            # After 2 consecutive losses, optimize immediately
            self._last_optimization = 0
        elif time.time() - self._last_optimization < self._optimization_interval:
            if len(self.performance_window) < self._min_trades_for_optimization:
                return {'status': 'skipped', 'reason': 'not_enough_trades'}
            return {'status': 'skipped', 'reason': 'too_soon'}

        self._last_optimization = 0
        result = self.run_optimization()
        return result

    def score_signal(self, direction: str, regime: str, confidence: float) -> float:
        """Score a new signal based on historical performance of similar setups.

        Returns a multiplier in [0.5, 1.3]:
        - 1.0 = neutral (no history)
        - 1.3 = strong historical edge
        - 0.5 = historically losing setup

        The historical edge has a strong floor; even low-confidence signals
        get the benefit/drawback of the regime's track record.
        """
        rp = self.regime_performance.get(regime, {})
        if not rp or rp.get('trades', 0) < 3:
            return 1.0
        wr = rp['wins'] / rp['trades']
        avg_pnl = rp['total_pnl'] / rp['trades']
        n = rp['trades']
        # Base quality: combines win rate (60%) and avg pnl (40%)
        pnl_component = max(-0.15, min(0.15, avg_pnl / 5))
        quality = 0.5 + (wr - 0.5) * 0.6 + pnl_component * 0.4
        # Confidence amplifies the move but with less dampening
        quality = 0.8 + (quality - 0.8) * (0.5 + 0.5 * confidence)
        # Confidence-conditional boost: high conf in winning regime = more
        if confidence > 0.6 and wr > 0.55:
            quality += 0.05
        # Clamp
        return float(max(0.5, min(1.3, quality)))

    def _analyze_performance(self) -> dict:
        """Analyze recent performance metrics."""
        trades = list(self.performance_window)
        if not trades:
            return {'win_rate': 0, 'avg_pnl': 0, 'sharpe': 0, 'max_dd': 0}
        
        wins = sum(1 for t in trades if t['won'])
        total = len(trades)
        win_rate = wins / total if total > 0 else 0
        
        pnls = [t['pnl_pct'] for t in trades]
        avg_pnl = np.mean(pnls) if pnls else 0
        
        # Sharpe-like ratio
        if len(pnls) > 1:
            std = np.std(pnls)
            sharpe = avg_pnl / std if std > 0 else 0
        else:
            sharpe = 0
        
        # Max drawdown
        equity = [10000]
        for p in pnls:
            equity.append(equity[-1] * (1 + p / 100))
        peak = equity[0]
        max_dd = 0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
        
        # Confidence calibration
        high_conf = [t for t in trades if t['confidence'] > 0.7]
        low_conf = [t for t in trades if t['confidence'] <= 0.5]
        high_conf_wr = sum(1 for t in high_conf if t['won']) / max(len(high_conf), 1)
        low_conf_wr = sum(1 for t in low_conf if t['won']) / max(len(low_conf), 1)
        
        # Regime breakdown
        regimes = {}
        for t in trades:
            r = t.get('regime', 'unknown')
            if r not in regimes:
                regimes[r] = {'trades': 0, 'wins': 0, 'pnl': 0}
            regimes[r]['trades'] += 1
            if t['won']:
                regimes[r]['wins'] += 1
            regimes[r]['pnl'] += t['pnl_pct']
        
        return {
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'total_trades': total,
            'high_confidence_wr': high_conf_wr,
            'low_confidence_wr': low_conf_wr,
            'regimes': regimes,
            'avg_hold': np.mean([t.get('hold_minutes', 0) for t in trades]),
        }

    def _identify_weaknesses(self, analysis: dict) -> list[str]:
        """Identify specific weaknesses in current performance."""
        weaknesses = []
        
        if analysis['win_rate'] < 0.50:
            weaknesses.append('low_win_rate')
        if analysis['avg_pnl'] < 0:
            weaknesses.append('negative_avg_pnl')
        if analysis['sharpe'] < 0:
            weaknesses.append('negative_sharpe')
        if analysis['max_drawdown'] > 10:
            weaknesses.append('high_drawdown')
        if analysis['high_confidence_wr'] < 0.60:
            weaknesses.append('confidence_miscalibrated')
        
        # Regime-specific weaknesses
        for regime, stats in analysis.get('regimes', {}).items():
            if stats['trades'] >= 5:
                wr = stats['wins'] / stats['trades']
                if wr < 0.40:
                    weaknesses.append(f'weak_in_{regime}')
        
        return weaknesses

    def _propose_changes(self, analysis: dict, weaknesses: list[str]) -> dict:
        """Propose parameter changes based on weaknesses."""
        proposed = self.params.copy()
        
        if 'low_win_rate' in weaknesses:
            # Increase confidence threshold to be more selective
            proposed['min_confidence'] = min(0.70, self.params['min_confidence'] + 0.03)
            proposed['min_edge'] = min(0.15, self.params['min_edge'] + 0.02)
        
        if 'negative_avg_pnl' in weaknesses:
            # Widen stops, tighten targets
            proposed['sl_multiplier_base'] = min(3.0, self.params['sl_multiplier_base'] + 0.2)
            proposed['tp_multiplier_base'] = max(2.0, self.params['tp_multiplier_base'] - 0.3)
        
        if 'high_drawdown' in weaknesses:
            # Reduce risk per trade
            proposed['risk_per_trade_pct'] = max(0.01, self.params['risk_per_trade_pct'] - 0.005)
            proposed['cooldown_minutes'] = min(10, self.params['cooldown_minutes'] + 1)
        
        if 'confidence_miscalibrated' in weaknesses:
            # Raise confidence threshold
            proposed['min_confidence'] = min(0.70, self.params['min_confidence'] + 0.02)
        
        # Regime-specific adjustments
        for weakness in weaknesses:
            if weakness.startswith('weak_in_'):
                regime = weakness.replace('weak_in_', '')
                # For weak regimes, increase minimum edge
                proposed['min_edge'] = min(0.15, proposed['min_edge'] + 0.01)
        
        return proposed

    def _evaluate_changes(self, proposed: dict, analysis: dict) -> dict:
        """Evaluate if proposed changes would improve performance.
        
        Uses a statistical approach based on historical trade data rather than
        pure heuristics, making the optimizer actually learn from outcomes.
        """
        current_wr = analysis['win_rate']
        current_pnl = analysis['avg_pnl']
        trades = list(self.performance_window)
        
        # Analyze trade outcomes by confidence bucket
        if len(trades) >= 5:
            high_conf_trades = [t for t in trades if t.get('confidence', 0) >= proposed['min_confidence']]
            low_conf_trades = [t for t in trades if t.get('confidence', 0) < proposed['min_confidence']]
            
            actual_high_wr = sum(1 for t in high_conf_trades if t.get('won')) / max(len(high_conf_trades), 1)
            actual_low_wr = sum(1 for t in low_conf_trades if t.get('won')) / max(len(low_conf_trades), 1)
            
            # If raising threshold would filter out losing trades, it's beneficial
            trade_quality_gain = 0.0
            if low_conf_trades:
                low_wr = actual_low_wr
                if low_wr < current_wr - 0.05:
                    trade_quality_gain = (current_wr - low_wr) * 0.5
            
            # If raising edge threshold, check if low-edge trades are losers
            edge_gain = 0.0
            if proposed.get('min_edge', 0) > self.params.get('min_edge', 0):
                low_edge = [t for t in trades if abs(t.get('pnl_pct', 0)) < proposed['min_edge'] * 10]
                if low_edge:
                    low_edge_wr = sum(1 for t in low_edge if t.get('won')) / len(low_edge)
                    if low_edge_wr < 0.40:
                        edge_gain = (0.50 - low_edge_wr) * 0.3
            
            # Check if regime-specific improvements are warranted
            regime_gain = 0.0
            for regime, stats in analysis.get('regimes', {}).items():
                if stats['trades'] >= 3:
                    wr = stats['wins'] / stats['trades']
                    if wr < 0.35:
                        regime_gain += 0.05  # Benefit from blocking this regime
        else:
            trade_quality_gain = 0.0
            edge_gain = 0.0
            regime_gain = 0.0
        
        improvement = trade_quality_gain + edge_gain + regime_gain
        
        # Penalty for reducing trade count too much
        conf_delta = proposed['min_confidence'] - self.params['min_confidence']
        trade_reduction = max(0, conf_delta * 0.5)
        if trade_reduction > 0.1:
            improvement -= trade_reduction * 0.3
        
        return {
            'improvement': improvement,
            'estimated_wr': current_wr + trade_quality_gain,
            'estimated_pnl': current_pnl + 0.0,
        }

    def get_adaptive_params(self, regime: str | None = None) -> dict:
        """Get current adaptive parameters, optionally regime-adjusted."""
        params = self.params.copy()
        
        if regime and regime in self.regime_performance:
            rp = self.regime_performance[regime]
            if rp['trades'] >= 10:
                wr = rp['wins'] / rp['trades']
                if wr < 0.40:
                    # Bad regime - be more conservative
                    params['min_confidence'] = min(0.75, params['min_confidence'] + 0.05)
                    params['min_edge'] = min(0.15, params['min_edge'] + 0.03)
                elif wr > 0.60:
                    # Good regime - slightly more aggressive
                    params['min_confidence'] = max(0.50, params['min_confidence'] - 0.02)
                    params['min_edge'] = max(0.05, params['min_edge'] - 0.01)
        
        return params

    def get_status(self) -> dict:
        """Get optimization engine status."""
        # Compute live signal quality scores per regime
        signal_quality = {}
        for regime, s in self.regime_performance.items():
            if s.get('trades', 0) >= 3:
                wr = s['wins'] / s['trades']
                avg_pnl = s['total_pnl'] / s['trades']
                quality_score = max(0.5, min(1.2, 0.5 + (wr - 0.5) * 0.6 + max(-0.1, min(0.1, avg_pnl / 10)) * 0.4))
                signal_quality[regime] = {
                    'quality_score': round(quality_score, 4),
                    'win_rate': round(wr, 4),
                    'avg_pnl': round(avg_pnl, 4),
                    'trades': s['trades'],
                }
        return {
            'total_attempts': len(self.attempts),
            'kept_attempts': sum(1 for a in self.attempts if a.kept),
            'current_params': self.params,
            'regime_performance': {
                r: {
                    'trades': s['trades'],
                    'win_rate': round(s['wins'] / max(s['trades'], 1), 4),
                    'total_pnl': round(s['total_pnl'], 4),
                }
                for r, s in self.regime_performance.items()
            },
            'signal_quality': signal_quality,
            'last_optimization': self._last_optimization,
            'next_optimization': self._last_optimization + self._optimization_interval,
            'active_learning': True,
        }

    def _save_state(self) -> None:
        state = {
            'state_version': self.state_version,
            'params': self.params,
            'regime_performance': self.regime_performance,
            'last_optimization': self._last_optimization,
            'attempts': [
                {
                    'timestamp': a.timestamp,
                    'improvement': a.improvement,
                    'kept': a.kept,
                    'reason': a.reason,
                }
                for a in list(self.attempts)[-50:]
            ],
        }
        path = 'data/optimization_state.json'
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(state, f, indent=2, default=str)

    def _load_state(self) -> None:
        path = 'data/optimization_state.json'
        try:
            with open(path) as f:
                state = json.load(f)
            if int(state.get('state_version', 0) or 0) < self.state_version:
                return
            self.params.update(state.get('params', {}))
            self.regime_performance = state.get('regime_performance', {})
            self._last_optimization = state.get('last_optimization', 0)
            # Restore attempts list so counter persists across restarts
            loaded_attempts = state.get('attempts', [])
            for a in loaded_attempts:
                if isinstance(a, dict):
                    self.attempts.append(OptimizationAttempt(
                        timestamp=a.get('timestamp', 0),
                        params_before=a.get('params_before', {}),
                        params_after=a.get('params_after', {}),
                        backtest_result=a.get('backtest_result', {}),
                        improvement=a.get('improvement', 0.0),
                        kept=a.get('kept', False),
                        reason=a.get('reason', ''),
                    ))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _rebuild_performance_window(self) -> None:
        """Compatibility no-op: aggregate stats cannot recreate real trades."""
        return None


# Singleton
optimizer = SelfOptimizationEngine()
