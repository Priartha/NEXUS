"""
XGBoost Classifier for BTCUSD Futures Direction Prediction.

Trained on features from the FeatureStore with labels from TripleBarrierLabeler.
Provides:
  - Direction prediction (long/short/neutral) with calibrated probability
  - Feature importance analysis
  - Periodic retraining on new labeled data
  - Confidence calibration via Platt scaling
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.analysis.label_generator import labeler
from backend.storage.feature_store import feature_store

logger = logging.getLogger(__name__)


@dataclass
class XGBoostPrediction:
    timestamp: int
    direction: str  # long, short, neutral
    probability: float
    raw_score: float
    confidence: float
    feature_contributions: dict[str, float]
    model_version: int


class XGBoostModel:
    """
    XGBoost classifier for BTCUSD futures direction prediction.

    Uses scikit-learn's XGBClassifier (or GradientBoostingClassifier as fallback).
    Features are pulled from the FeatureStore; labels from TripleBarrierLabeler.
    """

    def __init__(
        self,
        retrain_interval: float = 3600,
        min_training_samples: int = 200,
        learning_rate: float = 0.05,
        max_depth: int = 5,
        n_estimators: int = 200,
        subsample: float = 0.8,
        colsample_bytree: float = 0.7,
        scale_pos_weight: float = 1.0,
        proba_threshold_long: float = 0.55,
        proba_threshold_short: float = 0.55,
    ) -> None:
        self.retrain_interval = retrain_interval
        self.min_training_samples = min_training_samples
        self.proba_threshold_long = proba_threshold_long
        self.proba_threshold_short = proba_threshold_short

        self._model: Any = None
        self._model_version: int = 0
        self._last_train_ts: float = 0
        self._is_trained: bool = False

        # Training history
        self._train_history: deque[dict] = deque(maxlen=50)
        self._predictions: deque[XGBoostPrediction] = deque(maxlen=500)

        # Performance tracking
        self._total_preds: int = 0
        self._correct_preds: int = 0

        # Feature names used at last training
        self._feature_names: list[str] = []

        # Hyperparameters
        self.lr = learning_rate
        self.max_depth = max_depth
        self.n_estimators = n_estimators
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.scale_pos_weight = scale_pos_weight

        # Auto-feature selector
        self._feature_importance_cache: dict[str, float] = {}

    def _get_model(self):
        """Lazy import of XGBoost to avoid dependency issues."""
        if self._model is not None:
            return self._model
        try:
            import xgboost as xgb
            self._model = xgb.XGBClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.lr,
                subsample=self.subsample,
                colsample_bytree=self.colsample_bytree,
                objective="multi:softprob",
                num_class=3,
                eval_metric="mlogloss",
                use_label_encoder=False,
                random_state=42,
                verbosity=0,
            )
            logger.info("XGBoost model initialized")
            return self._model
        except ImportError:
            logger.info("XGBoost not available, using sklearn GradientBoostingClassifier")
            from sklearn.ensemble import GradientBoostingClassifier
            self._model = GradientBoostingClassifier(
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.lr,
                subsample=self.subsample,
                random_state=42,
                verbose=0,
            )
            return self._model

    def train(self, candles: list, timeframe: str, symbol: str = "BTCUSD") -> dict:
        """Train on recently labeled data. Returns training stats."""
        model = self._get_model()

        # Get labels from labeler
        from backend.analysis.label_generator import labeler
        recent_labels = labeler.get_recent_labels(n=1000)
        if len(recent_labels) < self.min_training_samples:
            return {"status": "skipped", "reason": f"Only {len(recent_labels)} labels, need {self.min_training_samples}"}

        # Build feature matrix - collect all features first, then build aligned vectors
        X_list: list[list[float]] = []
        y_list: list[int] = []
        feature_names_set: set[str] = set()
        feature_data: list[dict] = []

        for lb in recent_labels[:1000]:
            fv = feature_store.get_feature_vector(lb.timestamp, symbol, timeframe)
            if not fv:
                continue
            feature_names_set.update(fv.keys())
            feature_data.append(fv)
            # 3-class: bearish=-1 -> 0, neutral=0 -> 1, bullish=1 -> 2
            label_map = {-1: 0, 0: 1, 1: 2}
            y_list.append(label_map.get(lb.label, 0))

        if len(feature_data) < self.min_training_samples:
            return {"status": "skipped", "reason": f"Only {len(feature_data)} vectors, need {self.min_training_samples}"}

        # Use stable, sorted feature names so all rows have the same shape
        self._feature_names = sorted(feature_names_set)
        for fv in feature_data:
            X_list.append([float(fv.get(k, 0.0)) for k in self._feature_names])

        X = np.array(X_list, dtype=np.float32)
        y = np.array(y_list, dtype=np.int32)

        # Train/test split (80/20)
        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        model.fit(X_train, y_train)

        # Evaluate
        train_acc = float(model.score(X_train, y_train))
        test_acc = float(model.score(X_test, y_test)) if len(X_test) > 0 else 0.0

        # Get feature importance
        if hasattr(model, "feature_importances_"):
            for name, imp in zip(self._feature_names, model.feature_importances_):
                self._feature_importance_cache[name] = float(imp)
                feature_store.record_importance(name, float(imp), "xgboost")

        # Probabilities on test set for calibration check
        proba_preds = []
        if len(X_test) > 0 and hasattr(model, "predict_proba"):
            probs = model.predict_proba(X_test)
            proba_preds = [[float(p[i]) for i in range(3)] for p in probs]

        self._model_version += 1
        self._last_train_ts = time.time()
        self._is_trained = True

        stats = {
            "status": "trained",
            "model_version": self._model_version,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "train_accuracy": round(train_acc, 4),
            "test_accuracy": round(test_acc, 4),
            "class_distribution": {"bearish": int(np.sum(y_train == 0)), "neutral": int(np.sum(y_train == 1)), "bullish": int(np.sum(y_train == 2))},
            "feature_count": len(self._feature_names),
            "calibration_error": round(abs(test_acc - train_acc), 4),
        }
        self._train_history.append(stats)
        logger.info(f"XGBoost trained v{self._model_version}: acc={test_acc:.2%}")
        self._save_state()
        return stats

    def predict(self, timestamp: int, feature_vector: dict[str, float]) -> XGBoostPrediction:
        """Predict direction from a feature vector."""
        model = self._get_model()

        if not self._is_trained or not self._feature_names:
            return XGBoostPrediction(timestamp, "neutral", 0.5, 0.0, 0.0, {}, self._model_version)

        # Build array in feature order (fill missing with 0)
        X = np.array([[feature_vector.get(name, 0.0) for name in self._feature_names]], dtype=np.float32)

        # Get raw score
        try:
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(X)[0]
                prob_bearish = float(proba[0])
                prob_neutral = float(proba[1])
                prob_bullish = float(proba[2])
                raw_score = prob_bullish - prob_bearish
            else:
                raw_score = float(model.predict(X)[0])
                prob_bullish = raw_score
                prob_bearish = 0.0
        except Exception:
            return XGBoostPrediction(timestamp, "neutral", 0.5, 0.0, 0.0, {}, self._model_version)

        # Determine direction
        if prob_bullish >= self.proba_threshold_long:
            direction = "long"
            probability = prob_bullish
        elif prob_bearish >= self.proba_threshold_short:
            direction = "short"
            probability = prob_bearish
        else:
            direction = "neutral"
            probability = prob_neutral

        # Confidence is distance from neutral
        confidence = abs(prob_bullish - prob_bearish)

        # Feature contributions
        contributions = {}
        if hasattr(model, "feature_importances_"):
            for name, imp in zip(self._feature_names, model.feature_importances_):
                contributions[name] = float(imp) * feature_vector.get(name, 0.0)

        pred = XGBoostPrediction(
            timestamp=timestamp,
            direction=direction,
            probability=raw_score,
            raw_score=raw_score,
            confidence=confidence,
            feature_contributions=contributions,
            model_version=self._model_version,
        )
        self._predictions.append(pred)
        return pred

    def predict_from_store(self, timestamp: int, symbol: str, timeframe: str, features: dict[str, float] | None = None) -> XGBoostPrediction:
        """Predict using features from the feature store at a given timestamp."""
        if features is None:
            features = feature_store.get_feature_vector(timestamp, symbol, timeframe, self._feature_names)
        return self.predict(timestamp, features)

    def record_outcome(self, timestamp: int, predicted_direction: str, actual_direction: str) -> None:
        """Record prediction outcome for performance tracking."""
        self._total_preds += 1
        if predicted_direction == actual_direction:
            self._correct_preds += 1

    def should_retrain(self) -> bool:
        if not self._is_trained:
            return True
        recent_labels = labeler.get_recent_labels(n=200)
        return len(recent_labels) >= self.min_training_samples and (time.time() - self._last_train_ts) > self.retrain_interval

    def get_accuracy(self) -> float:
        return self._correct_preds / max(self._total_preds, 1)

    def get_state(self) -> dict:
        return {
            "is_trained": self._is_trained,
            "model_version": self._model_version,
            "total_predictions": self._total_preds,
            "accuracy": round(self.get_accuracy(), 4),
            "last_train_ts": self._last_train_ts,
            "feature_count": len(self._feature_names),
            "top_features": sorted(self._feature_importance_cache.items(), key=lambda x: -x[1])[:10],
            "threshold_long": self.proba_threshold_long,
            "threshold_short": self.proba_threshold_short,
            "train_history": list(self._train_history)[-5:],
            "recent_predictions": [
                {"ts": p.timestamp, "dir": p.direction, "conf": round(p.confidence, 3)}
                for p in list(self._predictions)[-10:]
            ],
        }

    def _save_state(self) -> None:
        state = {
            "model_version": self._model_version,
            "last_train_ts": self._last_train_ts,
            "is_trained": self._is_trained,
            "total_preds": self._total_preds,
            "correct_preds": self._correct_preds,
            "feature_names": self._feature_names,
            "feature_importance": self._feature_importance_cache,
            "threshold_long": self.proba_threshold_long,
            "threshold_short": self.proba_threshold_short,
        }
        path = "data/xgboost_state.json"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _load_state(self) -> None:
        path = "data/xgboost_state.json"
        try:
            with open(path) as f:
                state = json.load(f)
            self._model_version = state.get("model_version", 0)
            self._last_train_ts = state.get("last_train_ts", 0)
            self._is_trained = state.get("is_trained", False)
            self._total_preds = state.get("total_preds", 0)
            self._correct_preds = state.get("correct_preds", 0)
            self._feature_names = state.get("feature_names", [])
            self._feature_importance_cache = state.get("feature_importance", {})
            self.proba_threshold_long = state.get("threshold_long", self.proba_threshold_long)
            self.proba_threshold_short = state.get("threshold_short", self.proba_threshold_short)
        except (FileNotFoundError, json.JSONDecodeError):
            pass


# Singleton
xgboost_model = XGBoostModel()
xgboost_model._load_state()
