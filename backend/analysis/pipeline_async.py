"""
Async Pipeline Orchestrator with circuit breakers, retry, and health monitoring.

Coordinates all NEXUS analysis modules into a single async pipeline:
  1. Data ingestion (ticks -> candles -> indicators)
  2. ML inference (XGBoost, HMM, Transformer, NLP, RL)
  3. Signal generation (ensemble + unified_scalp)
  4. Position management
  5. Broadcast

Each external dependency is wrapped with a circuit breaker.
Pipeline health is exposed for monitoring and alerting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.analysis.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    circuit_registry,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineStepResult:
    step_name: str
    success: bool
    duration_ms: float
    error: str | None = None
    result: Any = None


@dataclass
class PipelineRunReport:
    timestamp: int
    total_duration_ms: float
    steps: list[PipelineStepResult]
    all_success: bool
    pipeline_id: str = "main"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "pipeline_id": self.pipeline_id,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "all_success": self.all_success,
            "steps": [
                {
                    "step": s.step_name,
                    "success": s.success,
                    "duration_ms": round(s.duration_ms, 2),
                    "error": s.error,
                    "has_result": s.result is not None,
                }
                for s in self.steps
            ],
        }


class AsyncPipeline:
    """
    Orchestrates all NEXUS analysis steps as an async DAG with circuit breakers.

    Usage:
        pipeline = AsyncPipeline()
        report = await pipeline.run_full(context)
    """

    def __init__(
        self,
        pipeline_id: str = "main",
        max_concurrent_steps: int = 4,
        step_timeout: float = 30.0,
        health_history_size: int = 500,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.max_concurrent_steps = max_concurrent_steps
        self.step_timeout = step_timeout

        self._health_history: deque[PipelineRunReport] = deque(maxlen=health_history_size)
        self._running: bool = False
        self._step_counter: int = 0
        self._semaphore = asyncio.Semaphore(max_concurrent_steps)

        self._init_circuit_breakers()

    def _init_circuit_breakers(self) -> None:
        breakers = {
            "xgboost": CircuitBreaker("xgboost", failure_threshold=0.4, min_failures=3),
            "transformer": CircuitBreaker("transformer", failure_threshold=0.4, min_failures=3),
            "rl_sizing": CircuitBreaker("rl_sizing", failure_threshold=0.4, min_failures=3),
            "hmm_regime": CircuitBreaker("hmm_regime", failure_threshold=0.4, min_failures=3),
            "nlp_sentiment": CircuitBreaker("nlp_sentiment", failure_threshold=0.4, min_failures=3),
            "onchain": CircuitBreaker("onchain", failure_threshold=0.5, min_failures=5, recovery_timeout=60.0),
            "cross_exchange": CircuitBreaker("cross_exchange", failure_threshold=0.5, min_failures=5),
            "feature_store": CircuitBreaker("feature_store", failure_threshold=0.6, min_failures=3),
        }
        for name, cb in breakers.items():
            circuit_registry.register(cb)

    async def run_full(self, context: dict) -> PipelineRunReport:
        """Run the full pipeline. Returns a report of all steps."""
        self._running = True
        start = time.time()
        steps: list[PipelineStepResult] = []

        steps.append(await self._run_step("feature_prep", self._feature_prep(context)))
        steps.append(await self._run_step("feature_store", self._update_feature_store(context)))
        steps.append(await self._run_step("regime_detection", self._detect_regime(context)))
        steps.append(await self._run_step("xgboost_inference", self._xgboost_infer(context)))
        steps.append(await self._run_step("ensemble_signal", self._ensemble_signal(context)))
        steps.append(await self._run_step("nlp_sentiment", self._nlp_refresh(context)))
        steps.append(await self._run_step("transformer_forecast", self._transformer_forecast(context)))
        steps.append(await self._run_step("position_sizing", self._position_sizing(context)))
        steps.append(await self._run_step("position_management", self._position_manage(context)))
        steps.append(await self._run_step("onchain_refresh", self._onchain_refresh(context)))
        steps.append(await self._run_step("cross_exchange", self._cross_exchange_refresh(context)))

        all_success = all(s.success for s in steps)

        report = PipelineRunReport(
            timestamp=int(time.time() * 1000),
            total_duration_ms=(time.time() - start) * 1000,
            steps=steps,
            all_success=all_success,
            pipeline_id=self.pipeline_id,
        )

        self._health_history.append(report)
        self._running = False
        return report

    async def _run_step(
        self,
        step_name: str,
        coro: Any,
    ) -> PipelineStepResult:
        """Run a single step with a timeout. Wraps result/error into a PipelineStepResult."""
        start = time.time()

        try:
            result = await asyncio.wait_for(coro, timeout=self.step_timeout)
            return PipelineStepResult(
                step_name=step_name,
                success=True,
                duration_ms=(time.time() - start) * 1000,
                result=result,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Pipeline step '{step_name}' timed out after {self.step_timeout}s")
            return PipelineStepResult(
                step_name=step_name,
                success=False,
                duration_ms=(time.time() - start) * 1000,
                error=f"Timeout after {self.step_timeout}s",
            )
        except CircuitBreakerOpenError as e:
            logger.warning(f"Pipeline step '{step_name}' skipped: {e}")
            return PipelineStepResult(
                step_name=step_name,
                success=False,
                duration_ms=(time.time() - start) * 1000,
                error=str(e),
            )
        except Exception as e:
            logger.exception(f"Pipeline step '{step_name}' failed: {e}")
            return PipelineStepResult(
                step_name=step_name,
                success=False,
                duration_ms=(time.time() - start) * 1000,
                error=str(e),
            )

    async def _feature_prep(self, ctx: dict) -> dict | None:
        from backend.analysis.label_generator import labeler
        return labeler.compute_labels(ctx.get("candles"))

    async def _update_feature_store(self, ctx: dict) -> None:
        cb = circuit_registry.get("feature_store")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("feature_store", cb.state)
        from backend.storage.feature_store import feature_store
        features = ctx.get("features", {})
        for name, value in features.items():
            feature_store.record_feature(name, value)
        if cb:
            cb.record_success()
        return None

    async def _detect_regime(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("hmm_regime")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("hmm_regime", cb.state)
        try:
            from backend.analysis.hmm_regime import hmm_classifier
            candles = ctx.get("candles", [])
            if not candles:
                return {"regime": "unknown", "probabilities": {}}
            prices = [c["close"] for c in candles if "close" in c]
            if len(prices) < hmm_classifier.n_states * 2:
                return {"regime": "unknown", "probabilities": {}}
            regime, probs = hmm_classifier.predict(prices)
            if cb:
                cb.record_success()
            return {"regime": regime, "probabilities": probs}
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _xgboost_infer(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("xgboost")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("xgboost", cb.state)
        try:
            from backend.analysis.xgboost_model import xgboost_model
            features = ctx.get("features", {})
            if not xgboost_model.is_trained:
                return {"trained": False, "signal": 0.0}
            signal = xgboost_model.predict(features)
            proba = xgboost_model.predict_proba(features)
            if cb:
                cb.record_success()
            return {"trained": True, "signal": float(signal), "probability": float(proba)}
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _ensemble_signal(self, ctx: dict) -> dict | None:
        return ctx.get("ensemble_result")

    async def _nlp_refresh(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("nlp_sentiment")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("nlp_sentiment", cb.state)
        try:
            from backend.analysis.sentiment_nlp import nlp_sentiment
            result = nlp_sentiment.get_aggregate_sentiment()
            if cb:
                cb.record_success()
            return result
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _transformer_forecast(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("transformer")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("transformer", cb.state)
        try:
            from backend.analysis.transformer_forecaster import transformer_forecaster
            from backend.models.types import Candle
            candles_data = ctx.get("candles", [])
            if len(candles_data) < 20:
                return {"forecast": None, "reason": "insufficient_data"}
            # Convert dicts to Candle objects
            candle_objs: list[Candle] = []
            for c in candles_data[-100:]:
                if isinstance(c, dict):
                    candle_objs.append(Candle(
                        timestamp=c.get("timestamp", 0),
                        open=c.get("open", 0.0),
                        high=c.get("high", 0.0),
                        low=c.get("low", 0.0),
                        close=c.get("close", 0.0),
                        volume=c.get("volume", 0.0),
                    ))
                else:
                    candle_objs.append(c)
            current_price = candle_objs[-1].close if candle_objs else 0.0
            forecasts = transformer_forecaster.predict(candle_objs, current_price)
            if cb:
                cb.record_success()
            return {
                "current_price": current_price,
                "horizons": [
                    {
                        "horizon": f.horizon,
                        "predicted_direction": f.predicted_direction,
                        "predicted_return_pct": f.predicted_return_pct,
                        "confidence": f.confidence,
                    }
                    for f in forecasts
                ],
            }
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _position_sizing(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("rl_sizing")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("rl_sizing", cb.state)
        try:
            from backend.analysis.rl_sizing import rl_sizing
            state = ctx.get("rl_state", {})
            if not state:
                return {"size": 0.0, "leverage": 1.0, "source": "no_state"}
            action = rl_sizing.decide(state)
            if cb:
                cb.record_success()
            return action
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _position_manage(self, ctx: dict) -> dict | None:
        try:
            from backend.analysis.position_manager import position_manager
            status = position_manager.get_status()
            return status
        except Exception:
            return None

    async def _onchain_refresh(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("onchain")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("onchain", cb.state)
        try:
            from backend.ingestion.onchain import onchain_provider
            btc_price = ctx.get("btc_price", 0) or 0
            try:
                await onchain_provider.refresh(btc_price=btc_price)
            except Exception:
                pass
            signal = onchain_provider.get_signal(btc_price)
            if cb:
                cb.record_success()
            return signal
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    async def _cross_exchange_refresh(self, ctx: dict) -> dict | None:
        cb = circuit_registry.get("cross_exchange")
        if cb and not cb.allow_request():
            raise CircuitBreakerOpenError("cross_exchange", cb.state)
        try:
            from backend.ingestion.cross_exchange import cross_exchange
            snapshot = await cross_exchange.refresh()
            if cb:
                cb.record_success()
            return {
                "median_price": snapshot.median_price,
                "spread_pct": snapshot.spread_pct,
                "exchange_count": snapshot.exchange_count,
                "basis_signals": [str(s) for s in cross_exchange.detect_basis()[:3]],
            }
        except Exception as e:
            if cb:
                cb.record_failure(str(e))
            raise

    def get_health(self) -> dict:
        recent = list(self._health_history)[-50:]
        if not recent:
            return {"healthy": True, "runs": 0, "avg_duration_ms": 0.0}

        success_rate = sum(1 for r in recent if r.all_success) / len(recent)
        avg_duration = sum(r.total_duration_ms for r in recent) / len(recent)

        step_success_rates: dict[str, float] = {}
        step_avg_durations: dict[str, float] = {}
        for r in recent:
            for s in r.steps:
                key = s.step_name
                if key not in step_success_rates:
                    step_success_rates[key] = []
                    step_avg_durations[key] = []
                step_success_rates[key].append(1 if s.success else 0)
                step_avg_durations[key].append(s.duration_ms)

        step_stats = {}
        for step_name, successes in step_success_rates.items():
            durations = step_avg_durations[step_name]
            step_stats[step_name] = {
                "success_rate": round(sum(successes) / len(successes), 4) if successes else 1.0,
                "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
                "times_called": len(successes),
            }

        return {
            "pipeline_id": self.pipeline_id,
            "healthy": success_rate >= 0.8,
            "success_rate": round(success_rate, 4),
            "avg_duration_ms": round(avg_duration, 2),
            "total_runs": len(self._health_history),
            "recent_runs": len(recent),
            "running": self._running,
            "step_stats": step_stats,
            "circuit_breakers": circuit_registry.get_all_states(),
        }

    def get_recent_reports(self, n: int = 10) -> list[dict]:
        return [r.to_dict() for r in list(self._health_history)[-n:]]


async_pipeline = AsyncPipeline()
