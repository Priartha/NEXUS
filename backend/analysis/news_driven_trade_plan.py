from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.analysis.events_calendar import scan_for_events
from backend.analysis.sentiment import SentimentService
from backend.analysis.sentiment_nlp import NLPSentimentEngine
from backend.ingestion.fast_news import FastNewsSource, FastHeadline
from backend.models.types import (
    NewsActivityEntry,
    NewsDrivenPlan,
    NewsTradePlanSnapshot,
    SentimentSnapshot,
    to_wire,
)


BULLISH_KEYWORDS = [
    "surge", "rally", "breakout", "bull", "buy", "accumulation",
    "adoption", "approval", "inflow", "record high", "rebound",
    "short squeeze", "institutional", "etf inflow", "whale buys",
]

BEARISH_KEYWORDS = [
    "dump", "crash", "ban", "crackdown", "hack", "exploit",
    "bear", "sell-off", "etf outflow", "outflow", "liquidation",
    "regulation", "lawsuit", "fear", "capitulation",
]


class NewsDrivenTradePlanService:
    def __init__(
        self,
        sentiment_service: SentimentService,
        nlp_engine: NLPSentimentEngine,
        fast_news: Optional[FastNewsSource] = None,
        config: Optional[dict] = None,
    ):
        self._sentiment = sentiment_service
        self._nlp = nlp_engine
        self._fast_news = fast_news
        self._config = config or {}
        self._active_plans: list[NewsDrivenPlan] = []
        self._activity_log: list[NewsActivityEntry] = []
        self._max_plans = self._config.get("max_active_plans", 20)
        self._max_log = self._config.get("max_activity_log", 200)
        self._last_snapshot: Optional[NewsTradePlanSnapshot] = None

    @property
    def current(self) -> Optional[NewsTradePlanSnapshot]:
        return self._last_snapshot

    def _headline_title(self, h: Any) -> str:
        if isinstance(h, dict):
            return h.get("title", "")
        return getattr(h, "title", "")

    def _headline_source(self, h: Any) -> str:
        if isinstance(h, dict):
            return h.get("source", "unknown")
        return getattr(h, "source", "unknown")

    def _headline_url(self, h: Any) -> str:
        if isinstance(h, dict):
            return h.get("url", "")
        return getattr(h, "url", "")

    def _headline_score(self, h: Any) -> float:
        if isinstance(h, dict):
            return h.get("score", 0.0)
        return getattr(h, "score", 0.0)

    def _infer_direction(self, text: str) -> tuple[str, float]:
        text_lower = text.lower()
        bullish_score = sum(
            1 for kw in BULLISH_KEYWORDS if kw in text_lower
        )
        bearish_score = sum(
            1 for kw in BEARISH_KEYWORDS if kw in text_lower
        )
        if bullish_score > bearish_score:
            return ("bullish", min(1.0, bullish_score / max(bearish_score, 1) * 0.3))
        if bearish_score > bullish_score:
            return ("bearish", min(1.0, bearish_score / max(bullish_score, 1) * 0.3))
        return ("neutral", 0.0)

    def _make_plan_from_headline(
        self, headline: Any, sentiment_snapshot: SentimentSnapshot, current_price: Optional[float]
    ) -> Optional[NewsDrivenPlan]:
        title = self._headline_title(headline)
        direction, confidence = self._infer_direction(title)
        if direction == "neutral" or confidence < 0.15:
            return None
        plan_id = f"news_{uuid.uuid4().hex[:12]}"
        entry_zone_low = None
        entry_zone_high = None
        stop_loss = None
        target_1 = None
        target_2 = None
        if current_price and current_price > 0:
            atr_buffer = current_price * 0.005
            if direction == "bullish":
                entry_zone_low = round(current_price - atr_buffer, 1)
                entry_zone_high = round(current_price + atr_buffer, 1)
                stop_loss = round(current_price - atr_buffer * 2, 1)
                target_1 = round(current_price + atr_buffer * 3, 1)
                target_2 = round(current_price + atr_buffer * 5, 1)
            else:
                entry_zone_low = round(current_price - atr_buffer, 1)
                entry_zone_high = round(current_price + atr_buffer, 1)
                stop_loss = round(current_price + atr_buffer * 2, 1)
                target_1 = round(current_price - atr_buffer * 3, 1)
                target_2 = round(current_price - atr_buffer * 5, 1)
        rationale = (
            f"News-driven {direction} trade plan based on headline: "
            f"'{title}'. "
            f"Sentiment confidence: {sentiment_snapshot.confidence:.0%}."
        )
        return NewsDrivenPlan(
            id=plan_id,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            source=self._headline_source(headline),
            headline=title,
            url=self._headline_url(headline),
            impact="high" if confidence > 0.5 else "medium",
            direction=direction,
            confidence=confidence,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            rationale=rationale,
            status="active",
        )

    def _log_activity(
        self,
        event_type: str,
        source: str,
        title: str,
        detail: str = "",
        direction: str = "neutral",
        score: float = 0.0,
        related_plan_id: Optional[str] = None,
    ):
        entry = NewsActivityEntry(
            id=f"act_{uuid.uuid4().hex[:12]}",
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            event_type=event_type,
            source=source,
            title=title,
            detail=detail,
            direction=direction,
            score=score,
            related_plan_id=related_plan_id,
        )
        self._activity_log.append(entry)
        if len(self._activity_log) > self._max_log:
            self._activity_log = self._activity_log[-self._max_log:]

    def refresh(
        self,
        candles: Optional[list[dict]] = None,
        current_price: Optional[float] = None,
    ) -> NewsTradePlanSnapshot:
        sentiment_snapshot = self._sentiment.current or SentimentSnapshot(
            label="neutral",
            score=0.0,
            confidence=0.0,
            source_count=0,
            updated_at=None,
        )

        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        nlp_result = self._nlp.current

        macro = {}
        if candles:
            macro = scan_for_events(candles, lookback=100)
        else:
            macro = {"events_in_48h": 0, "calendar": [], "anomalies": [], "is_event_day": False}

        new_plans: list[NewsDrivenPlan] = []

        if self._fast_news:
            try:
                fast_snapshot = self._fast_news.current
                if fast_snapshot and fast_snapshot.headlines:
                    for fh in fast_snapshot.headlines:
                        plan = self._make_plan_from_fast_headline(fh, current_price)
                        if plan:
                            new_plans.append(plan)
                            tag = "BREAKING " if fh.is_breaking else ""
                            self._log_activity(
                                event_type="trade_plan",
                                source=f"fast:{fh.source}",
                                title=f"{tag}New {plan.direction} trade plan from {fh.source}",
                                detail=fh.title[:120],
                                direction=plan.direction,
                                score=plan.confidence,
                                related_plan_id=plan.id,
                            )
            except Exception as e:
                logger.warning(f"fast_news integration error: {e}")

        for headline in sentiment_snapshot.headlines:
            plan = self._make_plan_from_headline(headline, sentiment_snapshot, current_price)
            if plan:
                new_plans.append(plan)
                self._log_activity(
                    event_type="trade_plan",
                    source=headline.source,
                    title=f"New {plan.direction} trade plan from news",
                    detail=headline.title[:120],
                    direction=plan.direction,
                    score=plan.confidence,
                    related_plan_id=plan.id,
                )

        if macro.get("is_event_day"):
            for ev in macro.get("active_events_24h", []):
                self._log_activity(
                    event_type="macro_event",
                    source="events_calendar",
                    title=f"Active macro event: {ev.get('name', 'unknown')}",
                    detail=ev.get("detail", ""),
                    direction="neutral",
                    score=1.0,
                )

        if nlp_result:
            self._log_activity(
                event_type="sentiment_shift",
                source="nlp_engine",
                title=f"NLP sentiment: {nlp_result.label} ({nlp_result.score:.3f})",
                detail=nlp_result.description[:200],
                direction=nlp_result.label,
                score=abs(nlp_result.score),
            )

        if sentiment_snapshot and sentiment_snapshot.headlines:
            latest = sentiment_snapshot.headlines[-1]
            self._log_activity(
                event_type="headline",
                source=latest.source,
                title=latest.title[:120],
                detail=f"Score: {latest.score:.2f}",
                direction="bullish" if latest.score > 0 else "bearish" if latest.score < 0 else "neutral",
                score=abs(latest.score),
            )

        self._active_plans.extend(new_plans)
        self._active_plans.sort(key=lambda p: p.timestamp, reverse=True)
        if len(self._active_plans) > self._max_plans:
            self._active_plans = self._active_plans[: self._max_plans]

        # Include live headlines from fast news in snapshot for REST fallback
        live_h = []
        breaking_h = []
        if self._fast_news and self._fast_news.current:
            fh = self._fast_news.current
            live_h = [to_wire(h) for h in (fh.headlines or [])[:15]]
            breaking_h = [to_wire(h) for h in (fh.breaking or [])[:10]]

        snapshot = NewsTradePlanSnapshot(
            active_plans=self._active_plans[:10],
            recent_activity=self._activity_log[-50:],
            macro_events=macro.get("calendar", [])[:15],
            live_headlines=live_h,
            breaking_headlines=breaking_h,
            sentiment_label=sentiment_snapshot.label,
            sentiment_score=sentiment_snapshot.score,
            updated_at=now_ms,
            source_count=len(sentiment_snapshot.headlines),
        )
        self._last_snapshot = snapshot
        return snapshot

    def _make_plan_from_fast_headline(
        self, headline: FastHeadline, current_price: Optional[float]
    ) -> Optional[NewsDrivenPlan]:
        direction, confidence = self._infer_direction(headline.title)
        if direction == "neutral" or confidence < 0.15:
            return None
        plan_id = f"fnews_{uuid.uuid4().hex[:12]}"
        entry_zone_low = None
        entry_zone_high = None
        stop_loss = None
        target_1 = None
        target_2 = None
        if current_price and current_price > 0:
            atr_buffer = current_price * 0.005
            if direction == "bullish":
                entry_zone_low = round(current_price - atr_buffer, 1)
                entry_zone_high = round(current_price + atr_buffer, 1)
                stop_loss = round(current_price - atr_buffer * 2, 1)
                target_1 = round(current_price + atr_buffer * 3, 1)
                target_2 = round(current_price + atr_buffer * 5, 1)
            else:
                entry_zone_low = round(current_price - atr_buffer, 1)
                entry_zone_high = round(current_price + atr_buffer, 1)
                stop_loss = round(current_price + atr_buffer * 2, 1)
                target_1 = round(current_price - atr_buffer * 3, 1)
                target_2 = round(current_price - atr_buffer * 5, 1)
        impact = "high" if headline.is_breaking else ("medium" if confidence > 0.5 else "low")
        badge = "BREAKING: " if headline.is_breaking else ""
        rationale = (
            f"{badge}Fast news-driven {direction} trade plan from {headline.source}. "
            f"Confidence: {confidence:.0%}. "
            f"Headline: '{headline.title}'"
        )
        return NewsDrivenPlan(
            id=plan_id,
            timestamp=headline.published_at or int(datetime.now(timezone.utc).timestamp() * 1000),
            source=f"fast:{headline.source}",
            headline=headline.title,
            url=headline.url,
            impact=impact,
            direction=direction,
            confidence=confidence,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
            rationale=rationale,
            status="active",
        )

    def get_snapshot(self) -> Optional[NewsTradePlanSnapshot]:
        return self._last_snapshot
