from __future__ import annotations

import asyncio
import html
import json
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from backend.models.types import SentimentHeadline, SentimentSnapshot


RSS_FEEDS = (
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss/tag/bitcoin"),
)

BULLISH_TERMS = {
    "accumulation": 1.1,
    "adoption": 0.9,
    "approval": 0.8,
    "breakout": 1.2,
    "bull": 0.8,
    "buy": 0.5,
    "etf inflow": 1.3,
    "higher": 0.4,
    "inflow": 1.0,
    "institutional": 0.8,
    "rally": 1.1,
    "record high": 1.2,
    "rebound": 0.8,
    "reserves fall": 0.9,
    "short squeeze": 1.1,
    "surge": 1.0,
    "whale buys": 1.0,
}

BEARISH_TERMS = {
    "ban": 1.0,
    "bear": 0.8,
    "crackdown": 1.1,
    "dump": 1.0,
    "etf outflow": 1.3,
    "exploit": 1.1,
    "fall": 0.5,
    "hack": 1.2,
    "lawsuit": 0.8,
    "liquidation": 0.8,
    "outflow": 1.0,
    "plunge": 1.2,
    "rejection": 0.8,
    "resistance": 0.5,
    "sell": 0.5,
    "selloff": 1.1,
    "slump": 1.0,
    "warning": 0.8,
}


class SentimentService:
    def __init__(
        self,
        symbol: str,
        provider: str = "auto",
        openai_model: str = "gpt-5.4-mini",
        openai_api_key: str = "",
        openai_base_url: str = "https://api.openai.com/v1",
        gemini_model: str = "gemini-2.5-flash",
        gemini_api_key: str = "",
        gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.symbol = symbol
        self.provider = provider.lower().strip()
        self.openai_model = openai_model
        self.openai_api_key = openai_api_key
        self.openai_base_url = openai_base_url.rstrip("/")
        self.gemini_model = gemini_model
        self.gemini_api_key = gemini_api_key
        self.gemini_base_url = gemini_base_url.rstrip("/")
        self.current = SentimentSnapshot(
            label="loading",
            score=0.0,
            confidence=0.0,
            source_count=0,
            updated_at=None,
            headlines=[],
            provider=self._active_provider_name(),
            model=self._active_model_name(),
            summary="Waiting for the first headline sentiment refresh.",
        )

    async def refresh(self) -> SentimentSnapshot:
        try:
            headlines = await self._fetch_headlines()
            local_snapshot = self._score_headlines(headlines)
            active_provider = self._active_provider_name()
            if active_provider == "gemini" and headlines:
                self.current = await self._score_with_gemini(headlines, local_snapshot)
            elif active_provider == "openai" and headlines:
                self.current = await self._score_with_openai(headlines, local_snapshot)
            else:
                self.current = local_snapshot
        except Exception as exc:
            self.current = SentimentSnapshot(
                label="unavailable",
                score=0.0,
                confidence=0.0,
                source_count=0,
                updated_at=int(time.time() * 1000),
                headlines=[],
                provider=self._active_provider_name(),
                model=self._active_model_name(),
                summary="Sentiment refresh failed.",
                error=str(exc),
            )
        return self.current

    async def _fetch_headlines(self) -> list[SentimentHeadline]:
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "ICT-Terminal/1.0 (+local sentiment reader)"},
        ) as client:
            responses = await asyncio.gather(
                *(client.get(url) for _, url in RSS_FEEDS),
                return_exceptions=True,
            )

        headlines: list[SentimentHeadline] = []
        for (source, _), response in zip(RSS_FEEDS, responses):
            if isinstance(response, Exception):
                continue
            try:
                response.raise_for_status()
                headlines.extend(self._parse_rss(source, response.text))
            except Exception:
                continue
        return sorted(
            headlines,
            key=lambda item: item.published_at or 0,
            reverse=True,
        )[:12]

    def _parse_rss(self, source: str, xml_text: str) -> list[SentimentHeadline]:
        root = ET.fromstring(xml_text)
        parsed: list[SentimentHeadline] = []
        for item in root.findall(".//item")[:20]:
            title = _text(item, "title")
            description = _text(item, "description")
            link = _text(item, "link")
            published_at = _parse_date(_text(item, "pubDate"))
            text = f"{title} {description}".lower()
            if not _is_relevant(text):
                continue
            parsed.append(
                SentimentHeadline(
                    title=html.unescape(title).strip(),
                    source=source,
                    url=link,
                    published_at=published_at,
                    score=round(_score_text(text), 3),
                )
            )
        return parsed

    def _score_headlines(self, headlines: list[SentimentHeadline]) -> SentimentSnapshot:
        updated_at = int(time.time() * 1000)
        if not headlines:
            return SentimentSnapshot(
                label="neutral",
                score=0.0,
                confidence=0.0,
                source_count=0,
                updated_at=updated_at,
                headlines=[],
                error="No Bitcoin headlines were available from the configured RSS feeds.",
            )

        weighted_total = 0.0
        weight_sum = 0.0
        for index, headline in enumerate(headlines):
            recency_weight = max(0.45, 1.0 - (index * 0.04))
            weighted_total += headline.score * recency_weight
            weight_sum += recency_weight
        score = _clamp(weighted_total / weight_sum if weight_sum else 0.0, -1.0, 1.0)

        if score > 0.18:
            label = "bullish"
        elif score < -0.18:
            label = "bearish"
        else:
            label = "neutral"

        confidence = min(0.9, abs(score) * 0.65 + min(len(headlines) / 20, 0.35))
        return SentimentSnapshot(
            label=label,
            score=round(score, 3),
            confidence=round(confidence, 3),
            source_count=len({headline.source for headline in headlines}),
            updated_at=updated_at,
            headlines=headlines[:6],
            provider="local_keyword",
            model=None,
            summary=_local_summary(label, score, headlines),
            drivers=_local_drivers(headlines),
            risk_flags=_local_risk_flags(headlines),
        )

    async def _score_with_openai(
        self,
        headlines: list[SentimentHeadline],
        fallback: SentimentSnapshot,
    ) -> SentimentSnapshot:
        payload = {
            "model": self.openai_model,
            "instructions": (
                "You are a crypto market sentiment analyst for a BTC trading terminal. "
                "Use only the supplied headlines. Return structured sentiment for BTC, "
                "not trade advice. Score must be from -1 bearish to +1 bullish."
            ),
            "input": self._openai_input(headlines),
            "max_output_tokens": 700,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "btc_market_sentiment",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["label", "score", "confidence", "summary", "drivers", "risk_flags"],
                        "properties": {
                            "label": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                            "score": {"type": "number"},
                            "confidence": {"type": "number"},
                            "summary": {"type": "string"},
                            "drivers": {"type": "array", "items": {"type": "string"}},
                            "risk_flags": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=18, follow_redirects=True) as client:
                response = await client.post(
                    f"{self.openai_base_url}/responses",
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
            parsed = json.loads(_extract_response_text(response.json()))
            label = parsed.get("label", fallback.label)
            score = _clamp(float(parsed.get("score", fallback.score)), -1.0, 1.0)
            confidence = _clamp(float(parsed.get("confidence", fallback.confidence)), 0.0, 1.0)
            return SentimentSnapshot(
                label=label if label in {"bullish", "bearish", "neutral"} else fallback.label,
                score=round(score, 3),
                confidence=round(confidence, 3),
                source_count=fallback.source_count,
                updated_at=int(time.time() * 1000),
                headlines=headlines[:6],
                provider="openai",
                model=self.openai_model,
                summary=str(parsed.get("summary", fallback.summary))[:420],
                drivers=_string_list(parsed.get("drivers"))[:5],
                risk_flags=_string_list(parsed.get("risk_flags"))[:5],
            )
        except Exception as exc:
            fallback.provider = "local_keyword"
            fallback.model = None
            fallback.error = f"OpenAI sentiment unavailable; local fallback used: {exc}"
            return fallback

    async def _score_with_gemini(
        self,
        headlines: list[SentimentHeadline],
        fallback: SentimentSnapshot,
    ) -> SentimentSnapshot:
        schema = {
            "type": "object",
            "properties": {
                "label": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
                "score": {"type": "number"},
                "confidence": {"type": "number"},
                "summary": {"type": "string"},
                "drivers": {"type": "array", "items": {"type": "string"}},
                "risk_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["label", "score", "confidence", "summary", "drivers", "risk_flags"],
        }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "You are a crypto market sentiment analyst for a BTC trading terminal. "
                                "Use only the supplied headlines. Return JSON sentiment for BTC, not trade advice. "
                                "score must be from -1 bearish to +1 bullish.\n\n"
                                f"{self._provider_input(headlines)}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.15,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=18, follow_redirects=True) as client:
                response = await client.post(
                    f"{self.gemini_base_url}/models/{self.gemini_model}:generateContent",
                    headers={
                        "x-goog-api-key": self.gemini_api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
            parsed = json.loads(_extract_gemini_text(response.json()))
            label = parsed.get("label", fallback.label)
            score = _clamp(float(parsed.get("score", fallback.score)), -1.0, 1.0)
            confidence = _clamp(float(parsed.get("confidence", fallback.confidence)), 0.0, 1.0)
            return SentimentSnapshot(
                label=label if label in {"bullish", "bearish", "neutral"} else fallback.label,
                score=round(score, 3),
                confidence=round(confidence, 3),
                source_count=fallback.source_count,
                updated_at=int(time.time() * 1000),
                headlines=headlines[:6],
                provider="gemini",
                model=self.gemini_model,
                summary=str(parsed.get("summary", fallback.summary))[:420],
                drivers=_string_list(parsed.get("drivers"))[:5],
                risk_flags=_string_list(parsed.get("risk_flags"))[:5],
            )
        except Exception as exc:
            fallback.provider = "local_keyword"
            fallback.model = None
            fallback.error = f"Gemini sentiment unavailable; local fallback used: {exc}"
            return fallback

    def _openai_input(self, headlines: list[SentimentHeadline]) -> str:
        return self._provider_input(headlines)

    def _provider_input(self, headlines: list[SentimentHeadline]) -> str:
        lines = [f"Symbol: {self.symbol}", "Headlines:"]
        for index, headline in enumerate(headlines[:12], start=1):
            published = headline.published_at or "unknown"
            lines.append(
                f"{index}. source={headline.source}; published_at_ms={published}; "
                f"title={headline.title}; url={headline.url}"
            )
        return "\n".join(lines)

    def _active_provider_name(self) -> str:
        if self.provider == "local":
            return "local_keyword"
        if self.provider == "gemini":
            return "gemini" if self.gemini_api_key else "local_keyword"
        if self.provider == "openai":
            return "openai" if self.openai_api_key else "local_keyword"
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return "local_keyword"

    def _active_model_name(self) -> str | None:
        provider = self._active_provider_name()
        if provider == "gemini":
            return self.gemini_model
        if provider == "openai":
            return self.openai_model
        return None


def _text(item: ET.Element, name: str) -> str:
    value = item.findtext(name)
    return value or ""


def _parse_date(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return int(parsed.timestamp() * 1000)
    except Exception:
        return None


def _is_relevant(text: str) -> bool:
    terms = ("bitcoin", "btc", "crypto", "exchange-traded fund", "etf")
    return any(term in text for term in terms)


def _score_text(text: str) -> float:
    bullish = sum(weight for term, weight in BULLISH_TERMS.items() if term in text)
    bearish = sum(weight for term, weight in BEARISH_TERMS.items() if term in text)
    if bullish == 0 and bearish == 0:
        return 0.0
    return _clamp((bullish - bearish) / max(bullish + bearish, 1.0), -1.0, 1.0)


def _local_summary(label: str, score: float, headlines: list[SentimentHeadline]) -> str:
    if not headlines:
        return "No relevant BTC headlines were available."
    strongest = max(headlines, key=lambda item: abs(item.score))
    return (
        f"Local fallback reads BTC sentiment as {label} "
        f"with score {score:.2f}; strongest headline came from {strongest.source}."
    )


def _local_drivers(headlines: list[SentimentHeadline]) -> list[str]:
    drivers: list[str] = []
    for headline in sorted(headlines, key=lambda item: abs(item.score), reverse=True)[:4]:
        direction = "bullish" if headline.score > 0 else "bearish" if headline.score < 0 else "neutral"
        drivers.append(f"{headline.source}: {direction} headline signal")
    return drivers


def _local_risk_flags(headlines: list[SentimentHeadline]) -> list[str]:
    risks: list[str] = []
    text = " ".join(headline.title.lower() for headline in headlines)
    for term in ("liquidation", "hack", "outflow", "crackdown", "lawsuit", "rejection"):
        if term in text:
            risks.append(f"Headline mentions {term}")
    return risks[:4]


def _extract_response_text(response_json: dict[str, Any]) -> str:
    direct = response_json.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    for output_item in response_json.get("output", []):
        for content in output_item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text

    raise ValueError("OpenAI response did not include output text")


def _extract_gemini_text(response_json: dict[str, Any]) -> str:
    candidates = response_json.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response did not include candidates")
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    for part in parts:
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return text
    raise ValueError("Gemini response did not include text")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:180] for item in value if str(item).strip()]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
