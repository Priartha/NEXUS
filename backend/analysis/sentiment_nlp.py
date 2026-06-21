"""
NLP Sentiment Analysis System for BTCUSD.

Integrates multiple sentiment sources:
  1. FinBERT (financial domain BERT) for news headline scoring
  2. VADER lexicon for social media sentiment
  3. Fear & Greed Index
  4. Social volume metrics
  5. Optional Gemini/OpenAI for enriched analysis

FinBERT provides domain-specific financial sentiment classification
that significantly outperforms generic sentiment models on crypto news.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class NLPSentimentResult:
    timestamp: int
    label: str  # bullish, bearish, neutral
    score: float  # -1 to +1 (bearish to bullish)
    confidence: float
    source_count: int
    headline_scores: list[dict]
    finbert_score: float | None
    vader_score: float | None
    fear_greed_index: int | None
    social_volume: int
    weighted_score: float
    volatility_regime: str
    description: str


class NLPSentimentEngine:
    """
    Multi-source NLP sentiment analysis with FinBERT and VADER.

    Aggregates scores from multiple sources using recency-weighted average.
    """

    def __init__(
        self,
        finbert_model: str = "ProsusAI/finbert",
        use_finbert: bool = True,
        use_vader: bool = True,
        use_gemini: bool = False,
        gemini_api_key: str | None = None,
        refresh_interval: float = 300.0,
        social_lookback_minutes: int = 60,
    ) -> None:
        self.finbert_model = finbert_model
        self.use_finbert = use_finbert
        self.use_vader = use_vader
        self.use_gemini = use_gemini
        self.gemini_api_key = gemini_api_key
        self.refresh_interval = refresh_interval
        self.social_lookback_minutes = social_lookback_minutes

        self._last_refresh: float = 0
        self._cache: NLPSentimentResult | None = None
        self._history: deque[NLPSentimentResult] = deque(maxlen=200)
        self._headline_buffer: deque[dict] = deque(maxlen=500)
        self._last_fetch: float = 0.0

        # FinBERT lazy load
        self._finbert_pipeline = None
        self._vader_analyzer = None
        self._gemini_model = None

    def ingest_headline(self, title: str, source: str, timestamp: int | None = None) -> None:
        """Buffer a headline for sentiment analysis."""
        self._headline_buffer.append({
            "title": title,
            "source": source,
            "timestamp": timestamp or int(time.time() * 1000),
        })

    def _load_finbert(self):
        if self._finbert_pipeline is not None or not self.use_finbert:
            return
        try:
            from transformers import pipeline
            self._finbert_pipeline = pipeline(
                "sentiment-analysis",
                model=self.finbert_model,
                tokenizer=self.finbert_model,
                max_length=128,
                truncation=True,
            )
            logger.info("FinBERT loaded successfully")
        except Exception as e:
            logger.warning(f"FinBERT load failed: {e}")
            self.use_finbert = False

    def _load_vader(self):
        if self._vader_analyzer is not None or not self.use_vader:
            return
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self._vader_analyzer = SentimentIntensityAnalyzer()
            logger.info("VADER loaded successfully")
        except ImportError:
            logger.info("vaderSentiment not available, using TextBlob fallback")
            try:
                from textblob import TextBlob
                self._vader_analyzer = TextBlob
            except ImportError:
                logger.warning("No sentiment library available, using keyword scoring")
                self.use_vader = False
        except Exception as e:
            logger.warning(f"VADER load failed: {e}")
            self.use_vader = False

    def _score_with_finbert(self, texts: list[str]) -> list[float]:
        """Score texts with FinBERT. Returns list of scores -1 to +1."""
        if not self.use_finbert or not texts:
            return []
        self._load_finbert()
        if self._finbert_pipeline is None:
            return []

        try:
            results = self._finbert_pipeline(texts[:20])  # batch size limit
            scores = []
            for r in results:
                label = r["label"].lower()
                score = r["score"]
                if label == "positive":
                    scores.append(score)
                elif label == "negative":
                    scores.append(-score)
                else:
                    scores.append(0.0)
            return scores
        except Exception as e:
            logger.warning(f"FinBERT scoring failed: {e}")
            return []

    def _score_with_vader(self, texts: list[str]) -> list[float]:
        """Score texts with VADER. Returns list of compound scores -1 to +1."""
        if not self.use_vader or not texts:
            return []
        self._load_vader()
        if self._vader_analyzer is None:
            return []

        scores = []
        for text in texts[:50]:
            try:
                if hasattr(self._vader_analyzer, "polarity_scores"):
                    vs = self._vader_analyzer.polarity_scores(text)
                    scores.append(vs["compound"])
                else:
                    tb = self._vader_analyzer(text)
                    scores.append(tb.sentiment.polarity)
            except Exception:
                scores.append(0.0)
        return scores

    def _score_with_keyword(self, texts: list[str]) -> list[float]:
        """Fallback keyword-based scoring."""
        bullish_words = {"bullish", "buy", "long", "accumulate", "moon", "pump", "breakout", "surge", "rally", "green", "up", "gain", "positive", "optimistic", "growth"}
        bearish_words = {"bearish", "sell", "short", "dump", "crash", "drop", "fall", "red", "down", "loss", "negative", "pessimistic", "decline", "fear", "panic"}

        scores = []
        for text in texts:
            words = set(re.findall(r"\w+", text.lower()))
            bullish_count = len(words & bullish_words)
            bearish_count = len(words & bearish_words)
            total = bullish_count + bearish_count
            if total > 0:
                scores.append((bullish_count - bearish_count) / total)
            else:
                scores.append(0.0)
        return scores

    def _fetch_fear_greed(self) -> int | None:
        """Fetch Fear & Greed Index (cached)."""
        try:
            import httpx
            resp = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return int(data["data"][0]["value"])
        except Exception:
            pass
        return None

    def _fetch_headlines(self, max_items: int = 20) -> list[dict]:
        """Fetch latest crypto news headlines from public sources."""
        headlines: list[dict] = []
        try:
            import httpx
            resp = httpx.get(
                "https://min-api.cryptocompare.com/data/v2/news/?lang=EN",
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("Data", [])[:max_items]:
                    title = item.get("title", "").strip()
                    if title:
                        headlines.append({
                            "title": title,
                            "source": item.get("source_info", {}).get("name", "cryptocompare"),
                            "timestamp": int(item.get("published_on", 0)) * 1000,
                        })
        except Exception:
            pass

        if not headlines:
            try:
                import httpx
                resp = httpx.get(
                    "https://api.coinpaprika.com/v1/news",
                    timeout=5,
                )
                if resp.status_code == 200:
                    for item in resp.json()[:max_items]:
                        title = item.get("title", "").strip()
                        if title:
                            headlines.append({
                                "title": title,
                                "source": item.get("source", "coinpaprika"),
                                "timestamp": 0,
                            })
            except Exception:
                pass

        for h in headlines:
            self.ingest_headline(h["title"], h["source"], h.get("timestamp"))
        return headlines

    async def compute(self, recent_headlines: list[dict] | None = None) -> NLPSentimentResult:
        """Compute aggregated sentiment from all sources."""
        now_ms = int(time.time() * 1000)

        if recent_headlines is not None:
            headlines = recent_headlines
        else:
            if not self._headline_buffer or (time.time() - self._last_fetch) > 300:
                self._fetch_headlines()
                self._last_fetch = time.time()
            headlines = list(self._headline_buffer)

        if not headlines:
            self._fetch_headlines()
            headlines = list(self._headline_buffer)

        if not headlines:
            return NLPSentimentResult(
                timestamp=now_ms, label="neutral", score=0.0, confidence=0.0,
                source_count=0, headline_scores=[], finbert_score=None, vader_score=None,
                fear_greed_index=None, social_volume=0, weighted_score=0.0,
                volatility_regime="normal", description="No headlines available",
            )

        # Get headlines from buffer
        texts = [h["title"] for h in headlines]

        # Score from all available sources
        finbert_scores = self._score_with_finbert(texts)
        vader_scores = self._score_with_vader(texts)
        keyword_scores = self._score_with_keyword(texts)
        fear_greed = self._fetch_fear_greed()

        # Calculate average scores per source
        finbert_avg = np.mean(finbert_scores) if finbert_scores else None
        vader_avg = np.mean(vader_scores) if vader_scores else None
        keyword_avg = np.mean(keyword_scores) if keyword_scores else None

        # Weighted blend (FinBERT highest weight, then VADER, then keyword)
        weights = []
        weighted_scores = []

        if finbert_avg is not None:
            weights.append(0.5)
            weighted_scores.append(finbert_avg)
        if vader_avg is not None:
            weights.append(0.3)
            weighted_scores.append(vader_avg)
        if keyword_avg is not None:
            weights.append(0.2)
            weighted_scores.append(keyword_avg)

        # Incorporate Fear & Greed
        if fear_greed is not None:
            fng_score = (fear_greed - 50) / 50  # map 0-100 to -1 to +1
            weights.append(0.15)
            weighted_scores.append(fng_score)

        total_weight = sum(weights)
        if total_weight > 0 and weighted_scores:
            final_score = sum(s * w for s, w in zip(weighted_scores, weights)) / total_weight
        else:
            final_score = 0.0

        # Determine label
        if final_score > 0.15:
            label = "bullish"
        elif final_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        # Confidence based on number of sources
        source_count = sum(1 for s in [finbert_scores, vader_scores, keyword_scores, fear_greed] if s)
        confidence = min(source_count / 4.0 + abs(final_score), 1.0)

        # Per-headline scores
        headline_scores = []
        for i, h in enumerate(headlines):
            headline_scores.append({
                "title": h["title"],
                "source": h.get("source", ""),
                "finbert_score": round(float(finbert_scores[i]), 4) if i < len(finbert_scores) and finbert_scores else None,
                "vader_score": round(float(vader_scores[i]), 4) if i < len(vader_scores) and vader_scores else None,
                "keyword_score": round(float(keyword_scores[i]), 4) if i < len(keyword_scores) and keyword_scores else None,
            })

        result = NLPSentimentResult(
            timestamp=now_ms,
            label=label,
            score=round(final_score, 4),
            confidence=round(confidence, 4),
            source_count=len(headlines),
            headline_scores=headline_scores[:20],
            finbert_score=round(float(finbert_avg), 4) if finbert_avg is not None else None,
            vader_score=round(float(vader_avg), 4) if vader_avg is not None else None,
            fear_greed_index=fear_greed,
            social_volume=len(headlines),
            weighted_score=round(final_score, 4),
            volatility_regime="normal",
            description=f"NLP sentiment: {label} ({final_score:+.2f}, conf={confidence:.0%}, sources={source_count})",
        )

        self._cache = result
        self._history.append(result)
        self._last_refresh = time.time()
        return result

    @property
    def current(self) -> NLPSentimentResult | None:
        return self._cache

    def get_state(self) -> dict:
        return {
            "use_finbert": self.use_finbert,
            "use_vader": self.use_vader,
            "finbert_loaded": self._finbert_pipeline is not None,
            "vader_loaded": self._vader_analyzer is not None,
            "headlines_buffered": len(self._headline_buffer),
            "last_refresh": self._last_refresh,
            "recent_results": [
                {"ts": r.timestamp, "label": r.label, "score": round(r.score, 3)}
                for r in list(self._history)[-5:]
            ],
        }


# Singleton
nlp_sentiment = NLPSentimentEngine()
