"""
Model Performance Drift Tracker for NEXUS.

Tracks AI ICT prediction accuracy over time, detects model degradation,
and alerts when performance falls below acceptable thresholds.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.storage.schema import get_conn

logger = logging.getLogger("backend")


@dataclass
class PredictionRecord:
    timestamp: int
    timeframe: str
    predicted_direction: str
    predicted_grade: str
    predicted_confidence: float
    actual_direction: str
    actual_return: float
    was_correct: bool
    hold_period_bars: int = 0


@dataclass
class ModelMetrics:
    total_predictions: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0
    avg_confidence: float = 0.0
    avg_return_when_correct: float = 0.0
    avg_return_when_wrong: float = 0.0
    accuracy_last_7d: float = 0.0
    accuracy_last_30d: float = 0.0
    accuracy_trend: str = "stable"
    degradation_alert: bool = False
    grade_distribution: dict[str, int] = field(default_factory=dict)
    timeframe_accuracy: dict[str, float] = field(default_factory=dict)


class ModelPerformanceTracker:
    """Tracks and analyzes AI model prediction performance over time."""

    def __init__(self):
        self._init_db()

    def _init_db(self) -> None:
        conn = get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_predictions (
                    id TEXT PRIMARY KEY,
                    timestamp INTEGER,
                    timeframe TEXT,
                    predicted_direction TEXT,
                    predicted_grade TEXT,
                    predicted_confidence REAL,
                    actual_direction TEXT,
                    actual_return REAL,
                    was_correct INTEGER,
                    hold_period_bars INTEGER DEFAULT 0,
                    created_at INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS model_daily_metrics (
                    date TEXT PRIMARY KEY,
                    total_predictions INTEGER,
                    correct_predictions INTEGER,
                    accuracy REAL,
                    avg_confidence REAL,
                    avg_return REAL,
                    created_at INTEGER
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def record_prediction(
        self,
        signal_id: str,
        timeframe: str,
        predicted_direction: str,
        predicted_grade: str,
        predicted_confidence: float,
    ) -> None:
        """Record a new model prediction."""
        conn = get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO model_predictions
                (id, timestamp, timeframe, predicted_direction, predicted_grade,
                 predicted_confidence, actual_direction, actual_return, was_correct, created_at)
                VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, ?)
            """, (
                signal_id, int(time.time() * 1000), timeframe,
                predicted_direction, predicted_grade, predicted_confidence,
                int(time.time() * 1000),
            ))
            conn.commit()
        finally:
            conn.close()

    def record_outcome(
        self,
        signal_id: str,
        actual_direction: str,
        actual_return: float,
        hold_period_bars: int = 0,
    ) -> None:
        """Record the actual outcome of a prediction."""
        conn = get_conn()
        try:
            predicted = conn.execute(
                "SELECT predicted_direction FROM model_predictions WHERE id=?", (signal_id,)
            ).fetchone()
            if not predicted:
                return

            was_correct = 1 if predicted[0] == actual_direction else 0
            conn.execute("""
                UPDATE model_predictions
                SET actual_direction=?, actual_return=?, was_correct=?, hold_period_bars=?
                WHERE id=?
            """, (actual_direction, actual_return, was_correct, hold_period_bars, signal_id))
            conn.commit()
        finally:
            conn.close()

    def get_metrics(self, days: int = 30) -> ModelMetrics:
        """Get model performance metrics for the specified period."""
        conn = get_conn()
        try:
            cutoff = int(time.time() * 1000) - days * 86400000

            rows = conn.execute("""
                SELECT predicted_direction, predicted_grade, predicted_confidence,
                       actual_direction, actual_return, was_correct, timeframe
                FROM model_predictions
                WHERE timestamp >= ? AND actual_direction != ''
            """, (cutoff,)).fetchall()

            if not rows:
                return ModelMetrics()

            total = len(rows)
            correct = sum(r[5] for r in rows)
            accuracy = correct / total if total > 0 else 0.0
            avg_conf = sum(r[2] for r in rows) / total

            correct_returns = [r[4] for r in rows if r[5] == 1]
            wrong_returns = [r[4] for r in rows if r[5] == 0]
            avg_ret_correct = sum(correct_returns) / len(correct_returns) if correct_returns else 0.0
            avg_ret_wrong = sum(wrong_returns) / len(wrong_returns) if wrong_returns else 0.0

            grade_dist: dict[str, int] = defaultdict(int)
            tf_correct: dict[str, list[int]] = defaultdict(list)
            for r in rows:
                grade_dist[r[1]] += 1
                tf_correct[r[6]].append(r[5])

            tf_accuracy = {
                tf: sum(results) / len(results) if results else 0.0
                for tf, results in tf_correct.items()
            }

            accuracy_7d = self._compute_accuracy(conn, 7)
            accuracy_30d = self._compute_accuracy(conn, 30)

            trend = self._compute_trend(conn)
            degradation = accuracy_7d < accuracy_30d * 0.85 and accuracy_7d < 0.45

            return ModelMetrics(
                total_predictions=total,
                correct_predictions=correct,
                accuracy=round(accuracy, 4),
                avg_confidence=round(avg_conf, 4),
                avg_return_when_correct=round(avg_ret_correct, 4),
                avg_return_when_wrong=round(avg_ret_wrong, 4),
                accuracy_last_7d=round(accuracy_7d, 4),
                accuracy_last_30d=round(accuracy_30d, 4),
                accuracy_trend=trend,
                degradation_alert=degradation,
                grade_distribution=dict(grade_dist),
                timeframe_accuracy=tf_accuracy,
            )
        finally:
            conn.close()

    def _compute_accuracy(self, conn, days: int) -> float:
        cutoff = int(time.time() * 1000) - days * 86400000
        row = conn.execute("""
            SELECT COUNT(*), SUM(was_correct) FROM model_predictions
            WHERE timestamp >= ? AND actual_direction != ''
        """, (cutoff,)).fetchone()
        if not row or row[0] == 0:
            return 0.0
        return row[1] / row[0]

    def _compute_trend(self, conn) -> str:
        now = int(time.time() * 1000)
        recent = self._compute_accuracy(conn, 7)
        older = self._compute_accuracy(conn, 14)
        if older == 0:
            return "stable"
        ratio = recent / older
        if ratio > 1.1:
            return "improving"
        elif ratio < 0.9:
            return "degrading"
        return "stable"

    def get_alerts(self) -> list[dict[str, Any]]:
        """Check for model performance alerts."""
        metrics = self.get_metrics()
        alerts = []

        if metrics.degradation_alert:
            alerts.append({
                "type": "model_degradation",
                "severity": "high",
                "message": f"Model accuracy dropped: 7d={metrics.accuracy_last_7d:.0%} vs 30d={metrics.accuracy_30d:.0%}",
                "timestamp": int(time.time() * 1000),
            })

        if metrics.accuracy < 0.40 and metrics.total_predictions > 20:
            alerts.append({
                "type": "low_accuracy",
                "severity": "critical",
                "message": f"Model accuracy critically low: {metrics.accuracy:.0%}",
                "timestamp": int(time.time() * 1000),
            })

        if metrics.accuracy_trend == "degrading":
            alerts.append({
                "type": "accuracy_trend",
                "severity": "medium",
                "message": f"Model accuracy trend is degrading (7d vs 14d)",
                "timestamp": int(time.time() * 1000),
            })

        return alerts


model_tracker = ModelPerformanceTracker()
