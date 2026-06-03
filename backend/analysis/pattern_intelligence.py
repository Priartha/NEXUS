"""
Self-Learning Pattern Intelligence Engine for NEXUS.

Discovers, stores, and analyzes price patterns autonomously:
1. Shape similarity — compares normalized candle body/wick sequences
2. Outcome analysis — tracks what happened after each pattern occurrence
3. Pattern discovery — clusters similar segments into recognized patterns
4. Context-aware matching — factors in price level and volatility regime
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from backend.models.types import Candle

logger = logging.getLogger("backend")

# Configuration
SEGMENT_LENGTH = 8          # candles per pattern segment
LOOKAHEAD_CANDLES = 4       # candles to measure outcome
MIN_SIMILARITY = 0.80       # minimum similarity for a "match" (raised from 0.75 — see diagnostic)
MIN_CLUSTER_SIZE = 4        # minimum segments to form a discovered pattern (raised from 3 for noise reduction)
MAX_SEGMENTS = 2000         # total historical segments to retain
DECAY_DAYS = 7              # days after last_seen before decay begins
MAX_DECAY_DAYS = 30         # days after which pattern is considered expired and removed
FEATURE_KEYS = ["body", "upper_wick", "lower_wick", "volume_ratio", "close_pos"]


def normalize_candles(candles: list[Candle]) -> list[dict[str, float]]:
    """Convert a list of candles into a normalized shape vector.

    Each candle becomes:
      body        = (close - open) / (high - low)  # -1 to +1
      upper_wick  = (high - max(open, close)) / (high - low)  # 0 to 1
      lower_wick  = (min(open, close) - low) / (high - low)   # 0 to 1
      volume_ratio = volume / avg_volume of segment
      close_pos   = (close - low) / (high - low)  # 0 to 1
    """
    if not candles:
        return []

    avg_vol = sum(c.volume for c in candles) / len(candles) if candles else 1

    result = []
    for c in candles:
        rng = c.high - c.low
        if rng <= 0:
            result.append({"body": 0, "upper_wick": 0, "lower_wick": 0, "volume_ratio": 1.0, "close_pos": 0.5})
            continue

        body = (c.close - c.open) / rng
        upper_wick = (c.high - max(c.open, c.close)) / rng
        lower_wick = (min(c.open, c.close) - c.low) / rng
        vol_ratio = c.volume / avg_vol if avg_vol > 0 else 1
        close_pos = (c.close - c.low) / rng

        result.append({
            "body": max(-1, min(1, body)),
            "upper_wick": max(0, min(1, upper_wick)),
            "lower_wick": max(0, min(1, lower_wick)),
            "volume_ratio": min(vol_ratio, 3.0),  # cap outliers
            "close_pos": max(0, min(1, close_pos)),
        })
    return result


def segment_to_vector(segment: list[dict[str, float]]) -> list[float]:
    """Flatten a list of candle feature dicts into a single vector."""
    vec = []
    for c in segment:
        vec.extend([c[k] for k in FEATURE_KEYS])
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(ai * bi for ai, bi in zip(a, b))
    na = math.sqrt(sum(ai * ai for ai in a))
    nb = math.sqrt(sum(bi * bi for bi in b))
    if na == 0 or nb == 0:
        return 0
    return dot / (na * nb)


def shape_distance(a: list[dict[str, float]], b: list[dict[str, float]]) -> float:
    """Euclidean distance between two normalized candle sequences."""
    va = segment_to_vector(a)
    vb = segment_to_vector(b)
    dist = math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(va, vb)))
    # Normalize to 0-1 range: max distance for 5 features across N candles is sqrt(N*5*4)
    max_dist = math.sqrt(len(va) * 4)
    return min(dist / max_dist, 1.0)


def shape_similarity(a: list[dict[str, float]], b: list[dict[str, float]]) -> float:
    """Convert shape distance to similarity score (0-1)."""
    return 1.0 - shape_distance(a, b)


@dataclass
class PatternOccurrence:
    """One occurrence of a pattern in history."""
    timestamp: int
    normalized: list[dict[str, float]]  # normalized candle features
    price_at_pattern: float              # price when pattern completed
    volatility_regime: str               # market context
    seg_hash: str = ""                  # dedup hash; cleared from _segment_hash_set on deque eviction
    outcome_return: float | None = None  # return over lookahead period
    outcome_high: float | None = None    # max favorable excursion
    outcome_low: float | None = None     # max adverse excursion
    matched_pattern_id: str | None = None


@dataclass
class DiscoveredPattern:
    """A pattern discovered by clustering similar segments."""
    pattern_id: str
    prototype: list[dict[str, float]]  # average of all member segments
    member_count: int
    occurrences: int
    avg_return: float
    win_rate: float
    avg_high_excursion: float
    avg_low_excursion: float
    direction: str  # bullish, bearish, neutral
    confidence: float
    first_seen: int
    last_seen: int
    similar_recent: bool = False  # True if a recent segment matched this


@dataclass
class PatternIntelligenceSnapshot:
    timestamp: int
    discovered_patterns: list[DiscoveredPattern]
    total_segments_analyzed: int
    current_match: dict | None = None  # closest match for current price action
    current_outlook: str = "neutral"
    current_confidence: float = 0.0


class PatternIntelligenceEngine:
    """Self-learning pattern intelligence that discovers and analyzes patterns."""

    def __init__(self):
        self.segments: deque[PatternOccurrence] = deque(maxlen=MAX_SEGMENTS)
        self.discovered: dict[str, DiscoveredPattern] = {}
        self._segment_hash_set: set[str] = set()  # dedup

    def record_candles(
        self, candles: list[Candle],
        lookahead: list[Candle] | None = None,
        volatility_regime: str = "normal",
    ) -> None:
        """Record a candle sequence as a pattern segment with optional outcome."""
        if len(candles) < SEGMENT_LENGTH:
            return

        # Use the most recent SEGMENT_LENGTH candles
        segment = candles[-SEGMENT_LENGTH:]
        normalized = normalize_candles(segment)

        # Deduplicate
        seg_hash = self._segment_hash(normalized)
        if seg_hash in self._segment_hash_set:
            return

        price = segment[-1].close
        ts = segment[-1].timestamp

        occ = PatternOccurrence(
            timestamp=ts,
            normalized=normalized,
            price_at_pattern=price,
            volatility_regime=volatility_regime,
        )

        # Compute outcome from lookahead candles
        if lookahead and len(lookahead) >= LOOKAHEAD_CANDLES:
            future = lookahead[-LOOKAHEAD_CANDLES:]
            start_price = future[0].open
            end_price = future[-1].close
            occ.outcome_return = (end_price - start_price) / start_price if start_price else 0
            occ.outcome_high = max((c.high - start_price) / start_price for c in future) if start_price else 0
            occ.outcome_low = min((c.low - start_price) / start_price for c in future) if start_price else 0

        occ.seg_hash = seg_hash
        # When deque is full, appending evicts the oldest segment;
        # also remove its hash to keep _segment_hash_set bounded.
        if len(self.segments) == self.segments.maxlen:
            self._segment_hash_set.discard(self.segments[0].seg_hash)
        self.segments.append(occ)
        self._segment_hash_set.add(seg_hash)

    def find_similar(
        self, candles: list[Candle], top_k: int = 5,
    ) -> list[tuple[PatternOccurrence, float]]:
        """Find the most similar historical segments to the given candle sequence."""
        if len(candles) < SEGMENT_LENGTH or not self.segments:
            return []

        query = normalize_candles(candles[-SEGMENT_LENGTH:])

        scored: list[tuple[PatternOccurrence, float]] = []
        for occ in self.segments:
            sim = shape_similarity(query, occ.normalized)
            if sim >= MIN_SIMILARITY:
                scored.append((occ, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def analyze_current(self, candles: list[Candle]) -> dict:
        """Analyze current price action against discovered patterns.

        Returns a dict with:
        - closest_match: the single best-matching historical occurrence
        - discovered_match: which discovered pattern (if any) this matches
        - outcome_stats: aggregate stats from all similar occurrences
        - outlook: directional bias from historical outcomes
        - confidence: how reliable the outlook is
        """
        if len(candles) < SEGMENT_LENGTH:
            return {"outlook": "neutral", "confidence": 0, "matches": 0}

        matches = self.find_similar(candles, top_k=20)
        if not matches:
            return {"outlook": "neutral", "confidence": 0, "matches": 0}

        # Find the closest discovered pattern prototype match
        query_norm = normalize_candles(candles[-SEGMENT_LENGTH:])
        best_discovered = None
        best_dp_sim = 0
        for pid, dp in self.discovered.items():
            sim = shape_similarity(query_norm, dp.prototype)
            if sim > best_dp_sim:
                best_dp_sim = sim
                best_discovered = dp

        # Compute outcome statistics from all matches
        outcomes = [m[0].outcome_return for m in matches if m[0].outcome_return is not None]
        wins = sum(1 for o in outcomes if o and o > 0)
        total = len(outcomes)

        avg_return = sum(outcomes) / total if total > 0 else 0
        win_rate = wins / total if total > 0 else 0

        if total == 0:
            outlook = "neutral"
        elif win_rate >= 0.6:
            outlook = "bullish"
        elif win_rate <= 0.4:
            outlook = "bearish"
        else:
            outlook = "neutral"

        # Confidence based on number of matches + win rate strength
        confidence = min(0.5 + abs(win_rate - 0.5) + min(total / 20.0, 0.2), 0.95)

        result = {
            "outlook": outlook,
            "confidence": round(confidence, 3),
            "matches": total,
            "avg_return": round(avg_return, 4),
            "win_rate": round(win_rate, 3),
            "best_similarity": round(matches[0][1], 3),
            "closest_match_ts": matches[0][0].timestamp if matches else None,
        }

        if best_discovered and best_dp_sim >= MIN_SIMILARITY:
            result["discovered_pattern_id"] = best_discovered.pattern_id
            result["discovered_pattern_occurrences"] = best_discovered.occurrences
            result["discovered_pattern_confidence"] = round(self._effective_confidence(best_discovered), 3)
            result["discovered_pattern_decay"] = round(self._decay_factor(best_discovered.last_seen), 3)
            result["discovered_pattern_effective_win_rate"] = round(self._effective_win_rate(best_discovered), 3)

        return result

    def discover_patterns(self) -> list[DiscoveredPattern]:
        """Cluster recent segments into discovered patterns.

        Uses a simple greedy clustering approach:
        1. Take all segments with outcome data
        2. Group by similarity (similarity >= threshold)
        3. Each cluster with >= MIN_CLUSTER_SIZE members becomes a discovered pattern
        """
        if len(self.segments) < MIN_CLUSTER_SIZE * 2:
            return list(self.discovered.values())

        all_segs = list(self.segments)
        clustered: set[int] = set()
        new_patterns: list[DiscoveredPattern] = []
        clusters: list[list[int]] = []

        # Greedy clustering
        for i in range(len(all_segs)):
            if i in clustered:
                continue
            cluster = [i]
            for j in range(i + 1, len(all_segs)):
                if j in clustered:
                    continue
                sim = shape_similarity(all_segs[i].normalized, all_segs[j].normalized)
                if sim >= MIN_SIMILARITY:
                    cluster.append(j)
            if len(cluster) >= MIN_CLUSTER_SIZE:
                clusters.append(cluster)
                clustered.update(cluster)

        for cl in clusters:
            members = [all_segs[i] for i in cl]
            prototypes = [m.normalized for m in members]
            n_candles = len(prototypes[0])
            n_features = len(FEATURE_KEYS)

            # Average prototype
            avg_proto = []
            for ci in range(n_candles):
                feat = {}
                for k in FEATURE_KEYS:
                    vals = [p[ci][k] for p in prototypes]
                    feat[k] = sum(vals) / len(vals)
                avg_proto.append(feat)

            outcomes = [m.outcome_return for m in members if m.outcome_return is not None]
            highs = [m.outcome_high for m in members if m.outcome_high is not None]
            lows = [m.outcome_low for m in members if m.outcome_low is not None]

            avg_ret = sum(outcomes) / len(outcomes) if outcomes else 0
            win_rate = sum(1 for o in outcomes if o and o > 0) / len(outcomes) if outcomes else 0.5
            avg_high = sum(highs) / len(highs) if highs else 0
            avg_low = sum(lows) / len(lows) if lows else 0

            if len(outcomes) == 0:
                direction = "neutral"
            elif win_rate >= 0.6:
                direction = "bullish"
            elif win_rate <= 0.4:
                direction = "bearish"
            else:
                direction = "neutral"

            confidence = min(0.5 + abs(win_rate - 0.5) + min(len(members) / 20.0, 0.3), 0.95)

            prototype_str = json.dumps(avg_proto, default=str)
            pid = "dp_" + hashlib.md5(prototype_str.encode()).hexdigest()[:10]

            if pid in self.discovered:
                # Update existing
                existing = self.discovered[pid]
                existing.member_count = len(members)
                existing.occurrences = len(outcomes)
                existing.avg_return = round(avg_ret, 4)
                existing.win_rate = round(win_rate, 3)
                existing.confidence = round(confidence, 3)
                existing.last_seen = max(m.timestamp for m in members)
            else:
                dp = DiscoveredPattern(
                    pattern_id=pid,
                    prototype=avg_proto,
                    member_count=len(members),
                    occurrences=len(outcomes),
                    avg_return=round(avg_ret, 4),
                    win_rate=round(win_rate, 3),
                    avg_high_excursion=round(avg_high, 4),
                    avg_low_excursion=round(avg_low, 4),
                    direction=direction,
                    confidence=round(confidence, 3),
                    first_seen=min(m.timestamp for m in members),
                    last_seen=max(m.timestamp for m in members),
                )
                self.discovered[pid] = dp
                new_patterns.append(dp)

        # Match remaining (unclustered) segments against existing prototypes
        # to update last_seen — keeps patterns alive when they match real data
        remaining = [i for i in range(len(all_segs)) if i not in clustered]
        for i in remaining:
            seg = all_segs[i]
            for pid, dp in self.discovered.items():
                sim = shape_similarity(seg.normalized, dp.prototype)
                if sim >= MIN_SIMILARITY:
                    if seg.timestamp > dp.last_seen:
                        dp.last_seen = seg.timestamp
                    break  # matched one pattern, move on

        # Update effective stats with decay applied
        for dp in self.discovered.values():
            if dp.last_seen > 0:
                effective_wr = self._effective_win_rate(dp)
                effective_conf = self._effective_confidence(dp)
                effective_ret = self._effective_avg_return(dp)
                decay = self._decay_factor(dp.last_seen)
                # Only update direction if decay hasn't fully neutralized it
                if decay > 0.3:
                    if effective_wr >= 0.6:
                        dp.direction = "bullish"
                    elif effective_wr <= 0.4:
                        dp.direction = "bearish"
                    else:
                        dp.direction = "neutral"

        # Remove fully decayed patterns
        removed = self._clean_expired()

        if new_patterns or removed:
            logger.info(
                "Patterns: %d new, %d expired, %d total",
                len(new_patterns), removed, len(self.discovered),
            )

        return list(self.discovered.values())

    def _decay_factor(self, last_seen_ms: int) -> float:
        """Compute decay multiplier based on time since last_seen.

        Returns 1.0 (full) if within DECAY_DAYS, 0.0 (dead) after MAX_DECAY_DAYS.
        Linear interpolation in between.
        """
        now_ms = int(time.time() * 1000)
        ms_since = now_ms - last_seen_ms
        days_since = ms_since / (1000 * 3600 * 24)
        if days_since <= DECAY_DAYS:
            return 1.0
        if days_since >= MAX_DECAY_DAYS:
            return 0.0
        return max(0.0, 1.0 - (days_since - DECAY_DAYS) / (MAX_DECAY_DAYS - DECAY_DAYS))

    def _effective_win_rate(self, dp: DiscoveredPattern) -> float:
        """Decay win_rate toward 0.5 (neutral) as pattern ages."""
        decay = self._decay_factor(dp.last_seen)
        return 0.5 + (dp.win_rate - 0.5) * decay

    def _effective_confidence(self, dp: DiscoveredPattern) -> float:
        """Decay confidence toward 0 as pattern ages."""
        decay = self._decay_factor(dp.last_seen)
        return dp.confidence * decay

    def _effective_avg_return(self, dp: DiscoveredPattern) -> float:
        """Decay avg_return toward 0 as pattern ages."""
        decay = self._decay_factor(dp.last_seen)
        return dp.avg_return * decay

    def _clean_expired(self) -> int:
        """Remove patterns that have fully decayed. Returns count removed."""
        expired = [pid for pid, dp in self.discovered.items()
                   if self._decay_factor(dp.last_seen) <= 0]
        for pid in expired:
            del self.discovered[pid]
        if expired:
            logger.info("Removed %d expired patterns (decayed beyond %d days)", len(expired), MAX_DECAY_DAYS)
        return len(expired)

    def get_state(self) -> PatternIntelligenceSnapshot:
        """Get current pattern intelligence state."""
        now = int(time.time() * 1000)
        return PatternIntelligenceSnapshot(
            timestamp=now,
            discovered_patterns=list(self.discovered.values()),
            total_segments_analyzed=len(self.segments),
        )

    def to_wire(self) -> dict:
        """Serialize to dict for JSON/API responses."""
        patterns = []
        for dp in self.discovered.values():
            decay = self._decay_factor(dp.last_seen)
            patterns.append({
                "pattern_id": dp.pattern_id,
                "member_count": dp.member_count,
                "occurrences": dp.occurrences,
                "avg_return": dp.avg_return,
                "effective_avg_return": round(self._effective_avg_return(dp), 4),
                "win_rate": dp.win_rate,
                "effective_win_rate": round(self._effective_win_rate(dp), 3),
                "direction": dp.direction,
                "confidence": dp.confidence,
                "effective_confidence": round(self._effective_confidence(dp), 3),
                "decay_factor": round(decay, 3),
                "first_seen": dp.first_seen,
                "last_seen": dp.last_seen,
            })
        return {
            "discovered_patterns": patterns,
            "total_segments": len(self.segments),
        }

    def _segment_hash(self, normalized: list[dict[str, float]]) -> str:
        """Generate a hash for deduplication."""
        raw = json.dumps(normalized, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    def _clamp(self, val: float, lo: float = -1, hi: float = 1) -> float:
        return max(lo, min(hi, val))
