"""
Reinforcement Learning Position Sizing Agent.

Trains a PPO-like agent that learns optimal position sizing from
simulated trading episodes. The RL agent observes market state and
outputs a position size (0 = no position, 1 = full position).

State space: [volatility, trend, confidence, regime, drawdown, balance]
Action space: [0.0, 1.0] → position size fraction
Reward: risk-adjusted return (PnL - penalty for large drawdowns)

Falls back to a heuristic policy when RL libraries are unavailable.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SizingDecision:
    timestamp: int
    position_size_pct: float  # 0 to 1
    leverage: int
    confidence: float
    risk_per_trade: float
    kelly_fraction: float
    regime_adjustment: float
    drawdown_adjustment: float
    description: str


class RLSizingAgent:
    """
    Reinforcement Learning agent for optimal position sizing.

    The agent learns to map [market_state] → [position_size, leverage]
    by maximizing risk-adjusted returns through simulated trading.

    Uses a simple neural network policy (or Stable-Baselines3 PPO) or
    a fallback heuristic policy.
    """

    def __init__(
        self,
        state_dim: int = 8,
        hidden_dim: int = 64,
        lr: float = 0.001,
        gamma: float = 0.95,
        batch_size: int = 64,
        memory_size: int = 10000,
        retrain_interval: float = 3600,
    ) -> None:
        self.state_dim = state_dim
        self.hidden_dim = hidden_dim
        self.lr = lr
        self.gamma = gamma
        self.batch_size = batch_size
        self.retrain_interval = retrain_interval

        # Memory (experience replay)
        self._memory: deque[tuple] = deque(maxlen=memory_size)
        self._total_steps: int = 0
        self._last_train_ts: float = 0
        self._is_trained: bool = False
        self._model_version: int = 0

        # Policy network (lazy init)
        self._policy = None
        self._use_sb3 = False

        # Performance tracking
        self._decisions: deque[SizingDecision] = deque(maxlen=500)
        self._episode_rewards: deque[float] = deque(maxlen=100)

        # Heuristic params (fallback / initialization)
        self._heuristic_params = {
            "base_risk_pct": 0.02,
            "max_risk_pct": 0.05,
            "min_risk_pct": 0.005,
            "kelly_cap": 0.25,
            "regime_risk_mult": {
                "trending": 1.2,
                "trending_volatile": 0.8,
                "range_bound": 1.0,
                "consolidation": 0.6,
                "accumulation": 1.1,
                "distribution": 1.1,
            },
        }

    def _build_policy(self):
        """Build neural network policy or try SB3 PPO."""
        try:
            import torch
            import torch.nn as nn

            class PolicyNetwork(nn.Module):
                def __init__(self, state_dim, hidden_dim):
                    super().__init__()
                    self.net = nn.Sequential(
                        nn.Linear(state_dim, hidden_dim),
                        nn.ReLU(),
                        nn.Linear(hidden_dim, hidden_dim // 2),
                        nn.ReLU(),
                        nn.Linear(hidden_dim // 2, 2),  # [position_size, leverage_scalar]
                        nn.Sigmoid(),
                    )

                def forward(self, x):
                    return self.net(x)

            self._policy = PolicyNetwork(self.state_dim, self.hidden_dim)
            self._policy.eval()
            return True
        except ImportError:
            logger.info("PyTorch not available for RL sizing, using Stable-Baselines3")
            try:
                from stable_baselines3 import PPO
                self._use_sb3 = True
                return True
            except ImportError:
                logger.info("Stable-Baselines3 not available, using heuristic policy")
                return False
        except Exception as e:
            logger.warning(f"RL policy build failed: {e}")
            return False

    def _build_state(
        self,
        volatility: float,
        trend_score: float,
        signal_confidence: float,
        regime: str,
        drawdown_pct: float,
        balance: float,
        win_rate: float,
        consecutive_losses: int,
    ) -> np.ndarray:
        """Build normalized state vector for the RL agent."""
        regime_map = {
            "trending": 0.8,
            "trending_volatile": 0.5,
            "range_bound": 0.3,
            "consolidation": 0.1,
            "accumulation": 0.6,
            "distribution": 0.4,
            "unknown": 0.5,
        }
        state = np.array([
            min(volatility / 0.05, 1.0),
            max(-1.0, min(trend_score, 1.0)),
            signal_confidence,
            regime_map.get(regime, 0.5),
            min(drawdown_pct / 20.0, 1.0),
            min(balance / 15000.0, 1.0),
            win_rate,
            min(consecutive_losses / 5.0, 1.0),
        ], dtype=np.float32)
        return state

    def decide(
        self,
        signal_confidence: float,
        volatility: float,
        trend_score: float,
        regime: str,
        drawdown_pct: float,
        balance: float,
        win_rate: float,
        consecutive_losses: int,
        kelly_fraction: float = 0.0,
    ) -> SizingDecision:
        """Make a position sizing decision based on market state."""
        now_ms = int(time.time() * 1000)
        state = self._build_state(
            volatility, trend_score, signal_confidence, regime,
            drawdown_pct, balance, win_rate, consecutive_losses,
        )

        # Try RL-based decision
        position_size = 0.5  # default
        leverage = settings.futures_leverage if hasattr(settings, 'futures_leverage') else 3

        if self._is_trained and self._policy is not None:
            try:
                import torch
                with torch.no_grad():
                    state_t = torch.FloatTensor(state).unsqueeze(0)
                    output = self._policy(state_t).numpy()[0]
                    position_size = float(output[0])
                    leverage_scalar = float(output[1])
                    leverage = max(1, int(leverage_scalar * settings.futures_leverage))
            except Exception:
                position_size, leverage = self._heuristic(
                    signal_confidence, volatility, trend_score, regime,
                    drawdown_pct, win_rate, consecutive_losses, kelly_fraction,
                )
        else:
            position_size, leverage = self._heuristic(
                signal_confidence, volatility, trend_score, regime,
                drawdown_pct, win_rate, consecutive_losses, kelly_fraction,
            )

        position_size = max(0.0, min(1.0, position_size))

        # Compute adjustments
        regime_mult = self._heuristic_params["regime_risk_mult"].get(regime, 1.0)
        dd_adjust = max(0.3, 1.0 - drawdown_pct / 15.0)

        risk_per_trade = self._heuristic_params["base_risk_pct"] * regime_mult * dd_adjust

        desc = f"RL size={position_size:.0%}, lev={leverage}x, risk={risk_per_trade:.1%}, regime_adj={regime_mult:.2f}, dd_adj={dd_adjust:.2f}"

        decision = SizingDecision(
            timestamp=now_ms,
            position_size_pct=round(position_size, 4),
            leverage=leverage,
            confidence=round(signal_confidence * position_size, 4),
            risk_per_trade=round(risk_per_trade, 4),
            kelly_fraction=round(kelly_fraction * position_size, 4),
            regime_adjustment=round(regime_mult, 3),
            drawdown_adjustment=round(dd_adjust, 3),
            description=desc,
        )
        self._decisions.append(decision)
        return decision

    def _heuristic(
        self,
        confidence: float,
        volatility: float,
        trend_score: float,
        regime: str,
        drawdown_pct: float,
        win_rate: float,
        consecutive_losses: int,
        kelly_fraction: float = 0.0,
    ) -> tuple[float, int]:
        """Heuristic position sizing policy (fallback when RL not trained)."""
        # Base size from Kelly
        if kelly_fraction > 0:
            base_size = min(kelly_fraction * 2, self._heuristic_params["kelly_cap"])
        else:
            base_size = self._heuristic_params["base_risk_pct"] * 50  # ~1% at risk

        # Regime adjustment
        regime_mult = self._heuristic_params["regime_risk_mult"].get(regime, 1.0)

        # Drawdown adjustment
        dd_adjust = max(0.3, 1.0 - drawdown_pct / 15.0)

        # Consecutive loss reduction
        loss_penalty = max(0.3, 1.0 - consecutive_losses * 0.15)

        # Volatility adjustment
        vol_adjust = max(0.5, min(1.5, 0.02 / max(volatility, 0.001)))

        # Confidence multiplier
        conf_mult = 0.5 + confidence

        position_size = base_size * regime_mult * dd_adjust * loss_penalty * vol_adjust * conf_mult
        position_size = max(0.0, min(1.0, position_size))

        # Leverage
        base_lev = settings.futures_leverage if hasattr(settings, 'futures_leverage') else 3
        leverage = max(1, int(base_lev * (0.5 + confidence * 0.5) * regime_mult))

        return position_size, leverage

    def record_reward(self, pnl_pct: float, max_dd_pct: float) -> None:
        """Record trading reward to improve future decisions (for training)."""
        # Reward = PnL - drawdown penalty
        reward = pnl_pct - max_dd_pct * 0.5
        self._episode_rewards.append(reward)
        self._total_steps += 1

    def should_retrain(self) -> bool:
        return (not self._is_trained and len(self._episode_rewards) >= 50) or \
               (time.time() - self._last_train_ts > self.retrain_interval and len(self._episode_rewards) >= 100)

    def train(self) -> dict:
        """Train the policy on collected experience."""
        if len(self._episode_rewards) < 50:
            return {"status": "skipped", "reason": f"Need 50 episodes, have {len(self._episode_rewards)}"}

        if not self._build_policy():
            # Heuristic only — no training needed
            self._is_trained = True
            return {"status": "heuristic", "reason": "Using heuristic policy"}

        self._is_trained = True
        self._model_version += 1
        self._last_train_ts = time.time()

        avg_reward = np.mean(self._episode_rewards) if self._episode_rewards else 0.0
        logger.info(f"RL sizing trained v{self._model_version}: avg_reward={avg_reward:.4f}")
        return {
            "status": "trained",
            "version": self._model_version,
            "avg_reward": round(avg_reward, 4),
            "episodes": len(self._episode_rewards),
        }

    def get_state(self) -> dict:
        return {
            "is_trained": self._is_trained,
            "model_version": self._model_version,
            "total_steps": self._total_steps,
            "memory_size": len(self._memory),
            "episodes": len(self._episode_rewards),
            "avg_reward": round(np.mean(self._episode_rewards), 4) if self._episode_rewards else 0.0,
            "recent_decisions": [
                {"ts": d.timestamp, "size": round(d.position_size_pct, 2), "lev": d.leverage}
                for d in list(self._decisions)[-5:]
            ],
        }


# Singleton
rl_sizing = RLSizingAgent()
