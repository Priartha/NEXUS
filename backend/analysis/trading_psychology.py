"""
Trading Psychology Engine for NEXUS AI Agent.

Models the behavioral biases every trader faces and applies
corrective adjustments to the agent's decision-making:

1. Overconfidence — after win streaks, agent gets more bullish than warranted
2. Revenge/chase — after losses, agent feels pressure to immediately re-enter
3. Loss aversion — reluctance to acknowledge losing setups
4. Recency bias — overweighting recent trades vs long-term statistics
5. Decision fatigue — quality degradation after many rapid decisions
6. Confidence calibration — tracks whether predicted confidence matches reality
7. Anchoring bias — holding to entry price for exit decisions
8. Gambler's fallacy — expecting reversal after streaks
"""

from __future__ import annotations

import time
import logging
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("backend")

MAX_TRADE_HISTORY = 100
FATIGUE_WINDOW_SEC = 3600  # 1 hour
CALIBRATION_MIN_TRADES = 10


@dataclass
class TradeRecord:
    timestamp: int
    direction: str
    confidence: float
    pnl_pct: float
    won: bool


@dataclass
class PsychologyState:
    overconfidence_penalty: float = 0.0       # -1.0 to 0.0 (negative = reduce confidence)
    revenge_chase_penalty: float = 0.0        # -1.0 to 0.0
    loss_aversion_penalty: float = 0.0        # -1.0 to 0.0
    recency_bias_adj: float = 0.0             # -0.5 to 0.5
    decision_fatigue_penalty: float = 0.0      # -1.0 to 0.0
    confidence_calibration: float = 1.0        # 0.0-1.0, ideal = 1.0
    anchoring_bias_adj: float = 0.0            # -0.5 to 0.5
    gamblers_fallacy_adj: float = 0.0          # -0.5 to 0.5

    streak_length: int = 0                     # positive = win streak, negative = loss streak
    recent_decisions_1h: int = 0
    avg_confidence_vs_accuracy: float = 0.0    # positive = overconfident

    warnings: list[str] = field(default_factory=list)


class TradingPsychologyEngine:
    def __init__(self):
        self.trades: deque[TradeRecord] = deque(maxlen=MAX_TRADE_HISTORY)
        self._decision_timestamps: deque[int] = deque(maxlen=200)
        self._win_streak = 0
        self._loss_streak = 0
        self._consecutive_wins = 0
        self._consecutive_losses = 0
        self._last_trade_result: bool | None = None
        self._last_trade_direction: str | None = None

    def record_trade_outcome(
        self, direction: str, confidence: float, pnl_pct: float, won: bool
    ) -> None:
        ts = int(time.time() * 1000)
        self.trades.append(TradeRecord(
            timestamp=ts, direction=direction,
            confidence=confidence, pnl_pct=pnl_pct, won=won,
        ))

        if won:
            self._consecutive_wins += 1
            self._consecutive_losses = 0
            self._win_streak += 1
            self._loss_streak = 0
        else:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
            self._loss_streak += 1
            self._win_streak = 0

        self._last_trade_result = won
        self._last_trade_direction = direction

    def record_decision(self) -> None:
        self._decision_timestamps.append(int(time.time()))

    def get_state(self) -> PsychologyState:
        state = PsychologyState()

        # Compute decision fatigue even when no trades exist yet
        self._compute_decision_fatigue(state)

        if not self.trades:
            if state.recent_decisions_1h > 30:
                state.warnings.append(f"Psychology: {state.recent_decisions_1h} decisions in last hour — fatigue risk")
            return state

        self._compute_overconfidence(state)
        self._compute_revenge_chase(state)
        self._compute_loss_aversion(state)
        self._compute_recency_bias(state)
        self._compute_decision_fatigue(state)
        self._compute_calibration(state)
        self._compute_anchoring(state)
        self._compute_gamblers_fallacy(state)

        warnings = []
        if state.decision_fatigue_penalty < -0.15:
            warnings.append(f"Psychology: {state.recent_decisions_1h} decisions in last hour — fatigue risk")
        if state.overconfidence_penalty < -0.2:
            warnings.append(f"Psychology: {abs(state.overconfidence_penalty)*100:.0f}% overconfidence after {self._consecutive_wins} wins")
        if state.revenge_chase_penalty < -0.2:
            warnings.append(f"Psychology: revenge trading risk after {self._consecutive_losses} losses")
        if state.loss_aversion_penalty < -0.15:
            warnings.append("Psychology: loss aversion may be affecting judgment")
        if state.gamblers_fallacy_adj < -0.1:
            warnings.append("Psychology: expecting reversal after streak — let data decide")
        if state.confidence_calibration < 0.7:
            warnings.append(f"Psychology: confidence calibration {state.confidence_calibration:.0%} — predictions vs reality diverging")
        state.warnings = warnings

        return state

    def adjust_score(self, base_score: float, state: PsychologyState | None = None) -> tuple[float, list[str]]:
        if state is None:
            state = self.get_state()
        reasons = []

        score = base_score

        over = state.overconfidence_penalty
        if over < -0.1:
            adj = over * 0.15
            score += adj
            reasons.append(f"Overconfidence correction {adj:+.3f}")

        rev = state.revenge_chase_penalty
        if rev < -0.1:
            adj = rev * 0.12
            score += adj
            reasons.append(f"Revenge-chase dampener {adj:+.3f}")

        la = state.loss_aversion_penalty
        if la < -0.1:
            adj = la * 0.10
            score += adj
            reasons.append(f"Loss-aversion discount {adj:+.3f}")

        fatigue = state.decision_fatigue_penalty
        if fatigue < -0.1:
            adj = fatigue * 0.10
            score += adj
            reasons.append(f"Fatigue penalty {adj:+.3f}")

        gf = state.gamblers_fallacy_adj
        if gf < -0.1:
            adj = gf * 0.08
            score += adj
            reasons.append(f"Gambler's fallacy correction {adj:+.3f}")

        cc = state.confidence_calibration
        if cc < 0.75:
            adj = (cc - 0.75) * 0.10
            score += adj
            reasons.append(f"Calibration correction {adj:+.3f}")

        score = max(0.05, min(0.95, score))
        return score, reasons

    def _compute_overconfidence(self, state: PsychologyState) -> None:
        if self._consecutive_wins >= 2:
            penalty = min(self._consecutive_wins / 15.0, 0.5)
            state.overconfidence_penalty = -penalty
        else:
            state.overconfidence_penalty = 0.0
        state.streak_length = self._consecutive_wins - self._consecutive_losses

    def _compute_revenge_chase(self, state: PsychologyState) -> None:
        if self._consecutive_losses >= 2:
            penalty = min(self._consecutive_losses / 10.0, 0.5)
            state.revenge_chase_penalty = -penalty
        else:
            state.revenge_chase_penalty = 0.0

    def _compute_loss_aversion(self, state: PsychologyState) -> None:
        if len(self.trades) < 3:
            return
        recent = list(self.trades)[-5:]
        losses = [t for t in recent if not t.won]
        if not losses:
            return
        total_pnl = sum(t.pnl_pct for t in recent)
        if total_pnl < -5.0:
            state.loss_aversion_penalty = -min(abs(total_pnl) / 50.0, 0.4)

    def _compute_recency_bias(self, state: PsychologyState) -> None:
        if len(self.trades) < 6:
            return
        all_trades = list(self.trades)
        recent_5 = all_trades[-5:]
        older = all_trades[:-5]

        recent_wr = sum(1 for t in recent_5 if t.won) / len(recent_5)
        older_wr = sum(1 for t in older if t.won) / len(older) if older else 0.5

        diff = recent_wr - older_wr
        if diff > 0.3:
            state.recency_bias_adj = -0.15
        elif diff < -0.3:
            state.recency_bias_adj = 0.15

    def _compute_decision_fatigue(self, state: PsychologyState) -> None:
        now = time.time()
        cutoff = now - FATIGUE_WINDOW_SEC
        recent = [t for t in self._decision_timestamps if t >= cutoff]
        count = len(recent)
        state.recent_decisions_1h = count
        if count > 30:
            state.decision_fatigue_penalty = -min((count - 30) / 50.0, 0.4)

    def _compute_calibration(self, state: PsychologyState) -> None:
        if len(self.trades) < CALIBRATION_MIN_TRADES:
            state.confidence_calibration = 1.0
            return
        all_trades = list(self.trades)
        avg_conf = sum(t.confidence for t in all_trades) / len(all_trades)
        accuracy = sum(1 for t in all_trades if t.won) / len(all_trades)
        diff = avg_conf - accuracy
        state.avg_confidence_vs_accuracy = diff
        if diff > 0.15:
            state.confidence_calibration = max(0.3, 1.0 - diff * 2)
        elif diff < -0.15:
            state.confidence_calibration = max(0.3, 1.0 - abs(diff) * 2)
        else:
            state.confidence_calibration = 1.0

    def _compute_anchoring(self, state: PsychologyState) -> None:
        if len(self.trades) < 3:
            return
        recent = list(self.trades)[-3:]
        same_dir = [t for t in recent if t.direction == self._last_trade_direction]
        if len(same_dir) >= 2 and all(not t.won for t in same_dir):
            state.anchoring_bias_adj = -0.2

    def _compute_gamblers_fallacy(self, state: PsychologyState) -> None:
        if abs(state.streak_length) >= 4 and state.streak_length > 0:
            state.gamblers_fallacy_adj = -min(state.streak_length / 15.0, 0.3)
        elif abs(state.streak_length) >= 4 and state.streak_length < 0:
            state.gamblers_fallacy_adj = -min(abs(state.streak_length) / 15.0, 0.3)
