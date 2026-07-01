"""
Hidden Markov Model (HMM) Regime Classifier.

Detects latent market regimes (bull, bear, range) using a Gaussian HMM
trained on price returns, volatility, and volume features.

The HMM automatically identifies regime-switching behavior without
hard-coded thresholds, providing a probabilistic regime classification
that complements the rule-based regime detector.
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

from backend.models.types import Candle

logger = logging.getLogger(__name__)


@dataclass
class HMMRegime:
    timestamp: int
    regime_id: int
    regime_name: str
    probability: float
    transition_probability: float
    next_regime_id: int | None
    next_regime_name: str | None
    log_likelihood: float
    description: str


class HMMRegimeClassifier:
    """
    Hidden Markov Model for market regime classification.

    Uses scikit-learn's GaussianHMM (or hmmlearn if available) to model
    latent market regimes from observable price features.

    States typically represent:
      0 = Range / Consolidation
      1 = Bull Trend
      2 = Bear Trend
    """

    def __init__(
        self,
        n_regimes: int = 3,
        lookback: int = 200,
        retrain_interval: float = 3600,
        covariance_type: str = "diag",
        n_iter: int = 100,
        seed: int = 42,
    ) -> None:
        self.n_regimes = n_regimes
        self.lookback = lookback
        self.retrain_interval = retrain_interval
        self.covariance_type = covariance_type
        self.n_iter = n_iter
        self.seed = seed

        self._model: Any = None
        self._is_trained: bool = False
        self._last_train_ts: float = 0
        self._training_version: int = 0

        # Observed features
        self._feature_history: deque[np.ndarray] = deque(maxlen=self.lookback)
        self._regime_history: deque[HMMRegime] = deque(maxlen=500)

        # Regime name mapping (learned from data, with defaults)
        self._regime_names: dict[int, str] = {
            0: "range",
            1: "bull_trend",
            2: "bear_trend",
        }

        # Transition matrix
        self._transition_matrix: np.ndarray | None = None

    def _get_model_class(self):
        """Lazy import hmmlearn or sklearn."""
        try:
            from hmmlearn import hmm
            return hmm.GaussianHMM
        except ImportError:
            logger.info("hmmlearn not available, using sklearn")
            try:
                from sklearn import mixture
                return mixture.GaussianMixture  # approximate with GMM if HMM unavailable
            except ImportError:
                raise ImportError("Need hmmlearn or sklearn for HMM")

    def _extract_features(self, candles: list[Candle]) -> np.ndarray:
        """Extract feature matrix from candles for HMM training."""
        if len(candles) < 10:
            return np.array([])

        closes = np.array([c.close for c in candles[-self.lookback:]])
        highs = np.array([c.high for c in candles[-self.lookback:]])
        lows = np.array([c.low for c in candles[-self.lookback:]])
        volumes = np.array([c.volume for c in candles[-self.lookback:]])
        n = len(closes)

        # Returns
        returns = np.diff(closes) / closes[:-1]
        returns = np.append(returns, 0)

        # Log returns
        log_returns = np.diff(np.log(closes + 1e-10))
        log_returns = np.append(log_returns, 0)

        # Range
        ranges = (highs - lows) / closes

        # Volume change
        vol_change = np.diff(volumes) / (volumes[:-1] + 1e-10)
        vol_change = np.append(vol_change, 0)

        # Normalize volume
        vol_norm = (volumes - np.mean(volumes[-50:])) / (np.std(volumes[-50:]) + 1e-10)

        # Rolling volatility (5-period)
        vol_roll = np.zeros(n)
        for i in range(5, n):
            vol_roll[i] = np.std(returns[i - 5 : i])

        # Feature matrix: [log_return, range, volume_norm, rolling_vol, vol_change]
        features = np.column_stack([
            log_returns,
            ranges,
            vol_norm,
            vol_roll,
            vol_change,
        ])

        # Normalize each feature
        for i in range(features.shape[1]):
            col = features[:, i]
            mean = np.nanmean(col)
            std = np.nanstd(col)
            if std > 1e-10:
                features[:, i] = (col - mean) / std

        return np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)

    def train(self, candles: list[Candle]) -> dict:
        """Train the HMM on recent candle data."""
        if len(candles) < self.lookback:
            return {"status": "skipped", "reason": f"Need {self.lookback} candles, have {len(candles)}"}

        features = self._extract_features(candles)
        if len(features) < self.lookback:
            return {"status": "skipped", "reason": "Insufficient features"}

        ModelClass = self._get_model_class()

        try:
            # Try hmmlearn
            self._model = ModelClass(
                n_components=self.n_regimes,
                covariance_type=self.covariance_type,
                n_iter=self.n_iter,
                random_state=self.seed,
            )
            self._model.fit(features)
            self._is_trained = True
            self._transition_matrix = self._model.transmat_
        except Exception:
            try:
                # Fallback to sklearn GMM
                self._model = ModelClass(
                    n_components=self.n_regimes,
                    covariance_type=self.covariance_type,
                    random_state=self.seed,
                    max_iter=self.n_iter,
                )
                self._model.fit(features)
                self._is_trained = True
                self._transition_matrix = None
            except Exception as e:
                logger.error(f"HMM training failed: {e}")
                return {"status": "failed", "reason": str(e)}

        self._training_version += 1
        self._last_train_ts = time.time()

        # Predict regimes and store
        if hasattr(self._model, "predict"):
            states = self._model.predict(features)
        else:
            states = np.zeros(len(features))

        # Determine regime names from state means
        self._label_regimes(features)

        # Log-likelihood
        log_lik = float(self._model.score(features)) if hasattr(self._model, "score") else 0.0

        logger.info(f"HMM trained v{self._training_version}: {self._regime_names} logL={log_lik:.2f}")
        return {
            "status": "trained",
            "version": self._training_version,
            "regime_names": self._regime_names,
            "log_likelihood": round(log_lik, 2),
            "transition_matrix": self._transition_matrix.tolist() if self._transition_matrix is not None else [],
            "n_features": features.shape[1],
        }

    def _label_regimes(self, features: np.ndarray) -> None:
        """Assign human-readable names to HMM states based on return means."""
        try:
            means = self._model.means_
            return_means = means[:, 0]  # log_return is first feature
            sorted_idx = np.argsort(return_means)
            self._regime_names = {
                int(sorted_idx[0]): "bear_trend",
                int(sorted_idx[1]): "range",
                int(sorted_idx[2]): "bull_trend",
            } if self.n_regimes >= 3 else {
                int(sorted_idx[0]): "bear_trend",
                int(sorted_idx[1]): "bull_trend",
            }
        except Exception:
            pass

    def predict(self, candles: list[Candle]) -> HMMRegime:
        """Predict current market regime from latest candles."""
        now_ms = candles[-1].timestamp if candles else int(time.time() * 1000)

        if not self._is_trained or len(candles) < 20:
            return HMMRegime(now_ms, 0, "unknown", 0.0, 0.0, None, None, -999, "HMM not trained")

        features = self._extract_features(candles)
        if len(features) < 5:
            return HMMRegime(now_ms, 0, "unknown", 0.0, 0.0, None, None, -999, "Insufficient features")

        # Predict latest state
        try:
            if hasattr(self._model, "predict"):
                states = self._model.predict(features)
                current_state = int(states[-1])
            else:
                return HMMRegime(now_ms, 0, "unknown", 0.0, 0.0, None, None, -999, "Predict not supported")

            # State probability
            if hasattr(self._model, "predict_proba"):
                probs = self._model.predict_proba(features[-1:])[0]
                prob = float(probs[current_state])
            else:
                prob = 1.0

            # Transition probability to next regime
            trans_prob = 0.0
            next_regime = None
            next_name = None
            if self._transition_matrix is not None:
                trans_row = self._transition_matrix[current_state]
                next_regime = int(np.argmax(trans_row))
                trans_prob = float(trans_row[next_regime])
                next_name = self._regime_names.get(next_regime, f"state_{next_regime}")

            # Log-likelihood
            log_lik = float(self._model.score(features)) if hasattr(self._model, "score") else 0.0

            name = self._regime_names.get(current_state, f"state_{current_state}")
            regime = HMMRegime(
                timestamp=now_ms,
                regime_id=current_state,
                regime_name=name,
                probability=prob,
                transition_probability=trans_prob,
                next_regime_id=next_regime,
                next_regime_name=next_name,
                log_likelihood=round(log_lik, 2),
                description=f"HMM regime: {name} (prob={prob:.0%}, next={next_name or 'N/A'})",
            )
            self._regime_history.append(regime)
            return regime

        except Exception as e:
            logger.error(f"HMM predict failed: {e}")
            return HMMRegime(now_ms, 0, "unknown", 0.0, 0.0, None, None, -999, f"HMM error: {e}")

    def should_retrain(self) -> bool:
        return not self._is_trained or (time.time() - self._last_train_ts) > self.retrain_interval

    def get_state(self) -> dict:
        return {
            "is_trained": self._is_trained,
            "n_regimes": self.n_regimes,
            "regime_names": self._regime_names,
            "version": self._training_version,
            "history_length": len(self._regime_history),
            "last_train_ts": self._last_train_ts,
            "recent_regimes": [
                r.regime_name for r in list(self._regime_history)[-10:]
            ],
        }


# Singleton
hmm_classifier = HMMRegimeClassifier()
