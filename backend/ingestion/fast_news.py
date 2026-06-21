from __future__ import annotations

import asyncio
import html
import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

FAST_RSS_FEEDS: list[tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("CoinTelegraph", "https://cointelegraph.com/rss/tag/bitcoin"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
    ("CryptoSlate", "https://cryptoslate.com/feed/"),
]

CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

BULLISH_TERMS = {
    "surge": 1.2, "rally": 1.1, "breakout": 1.2, "bull": 0.8, "buy": 0.5,
    "accumulation": 1.1, "adoption": 0.9, "approval": 0.8, "inflow": 1.0,
    "record high": 1.2, "rebound": 0.8, "short squeeze": 1.1,
    "institutional": 0.8, "etf inflow": 1.3, "whale buys": 1.0,
    "upgrade": 0.7, "partnership": 0.6, "launch": 0.4, "positive": 0.5,
    "gain": 0.6, "green": 0.3, "recovery": 0.7, "all-time high": 1.2,
}

BEARISH_TERMS = {
    "dump": 1.0, "crash": 1.2, "ban": 1.0, "crackdown": 1.1, "hack": 1.2,
    "exploit": 1.1, "bear": 0.8, "sell-off": 1.1, "etf outflow": 1.3,
    "outflow": 0.8, "liquidation": 0.9, "regulation": 0.7, "lawsuit": 0.8,
    "fear": 0.6, "capitulation": 1.1, "scam": 1.0, "fraud": 1.1,
    "decline": 0.6, "drop": 0.6, "fall": 0.5, "negative": 0.5,
    "risk": 0.4, "warning": 0.5, "ban": 1.0, "restrict": 0.7,
}


@dataclass
class FastHeadline:
    title: str
    source: str
    url: str
    published_at: int
    score: float = 0.0
    is_breaking: bool = False
    categories: list[str] = field(default_factory=list)


@dataclass
class FastNewsSnapshot:
    headlines: list[FastHeadline] = field(default_factory=list)
    breaking: list[FastHeadline] = field(default_factory=list)
    source_count: int = 0
    updated_at: Optional[int] = None


def _score_text(text: str) -> float:
    text_lower = text.lower()
    score = 0.0
    for term, weight in BULLISH_TERMS.items():
        if term in text_lower:
            score += weight
    for term, weight in BEARISH_TERMS.items():
        if term in text_lower:
            score -= weight
    return max(-1.0, min(1.0, score / 4.0))


def _is_relevant(text: str) -> bool:
    keywords = ["bitcoin", "btc", "crypto", "blockchain", "ethereum", "eth",
                "market", "trading", "price", "fed", "sec", "regulation",
                "mining", "halving", "etf", "institutional", "whale",
                "liquidation", "volatility", "rally", "crash"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _parse_rss(source: str, xml_text: str) -> list[FastHeadline]:
    headlines: list[FastHeadline] = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item")[:15]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "#").strip()
            pub_date = item.findtext("pubDate", "")
            desc = item.findtext("description", "")
            text = f"{title} {desc}".lower()
            if not title or not _is_relevant(text):
                continue
            ts = 0
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = int(parsedate_to_datetime(pub_date).timestamp())
                except Exception:
                    ts = int(time.time())
            headlines.append(FastHeadline(
                title=html.unescape(title).strip(),
                source=source,
                url=link,
                published_at=ts,
                score=round(_score_text(text), 3),
                is_breaking=_is_breaking(title),
            ))
    except ET.ParseError as e:
        logger.warning(f"RSS parse error for {source}: {e}")
    return headlines


def _is_breaking(title: str) -> bool:
    t = title.lower()
    triggers = ["breaking", "urgent", "just in", "flash", "alert",
                "emergency", "crisis", "unexpected", "shock",
                "plunge", "soar", "explodes", "crashes"]
    return any(kw in t for kw in triggers)


class FastNewsSource:
    def __init__(self, refresh_interval: float = 30.0, max_headlines: int = 50):
        self._refresh_interval = refresh_interval
        self._max_headlines = max_headlines
        self._headlines: list[FastHeadline] = []
        self._seen_urls: set[str] = set()
        self._last_refresh: float = 0.0
        self._snapshot: Optional[FastNewsSnapshot] = None

    @property
    def current(self) -> Optional[FastNewsSnapshot]:
        return self._snapshot

    @property
    def latest_headlines(self) -> list[FastHeadline]:
        return self._headlines[:20]

    async def refresh(self) -> FastNewsSnapshot:
        new_headlines: list[FastHeadline] = []

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            rss_tasks = [
                self._fetch_rss(client, source, url)
                for source, url in FAST_RSS_FEEDS
            ]
            crypto_tasks = [self._fetch_cryptocompare(client)]

            results = await asyncio.gather(*rss_tasks, *crypto_tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, list):
                    new_headlines.extend(result)
                elif isinstance(result, Exception):
                    logger.debug(f"fast_news fetch error: {result}")

        deduped: list[FastHeadline] = []
        for h in new_headlines:
            if h.url and h.url not in self._seen_urls:
                self._seen_urls.add(h.url)
                deduped.append(h)

        deduped.sort(key=lambda h: h.published_at or 0, reverse=True)
        self._headlines = (deduped + self._headlines)[:self._max_headlines]

        if len(self._seen_urls) > 2000:
            self._seen_urls = set(list(self._seen_urls)[-1000:])

        breaking = [h for h in deduped if h.is_breaking]
        self._snapshot = FastNewsSnapshot(
            headlines=self._headlines[:30],
            breaking=breaking[:10],
            source_count=len({h.source for h in self._headlines}),
            updated_at=int(time.time() * 1000),
        )
        self._last_refresh = time.time()
        return self._snapshot

    async def _fetch_rss(self, client: httpx.AsyncClient, source: str, url: str) -> list[FastHeadline]:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return _parse_rss(source, resp.text)
        except Exception as e:
            logger.debug(f"RSS fetch failed for {source}: {e}")
            return []

    async def continuous_refresh(self) -> AsyncIterator[FastNewsSnapshot]:
        while True:
            snapshot = await self.refresh()
            yield snapshot
            await asyncio.sleep(self._refresh_interval)

    async def _fetch_cryptocompare(self, client: httpx.AsyncClient) -> list[FastHeadline]:
        try:
            resp = await client.get(
                CRYPTOCOMPARE_NEWS_URL,
                params={"lang": "EN", "feeds": "coindesk,cointelegraph,decrypt,newsbtc,bitcoinist"},
            )
            resp.raise_for_status()
            data = resp.json()
            headlines: list[FastHeadline] = []
            for item in data.get("Data", [])[:20]:
                title = (item.get("title") or "").strip()
                body = (item.get("body") or "")
                url = (item.get("url") or "#")
                source_info = item.get("source_info", {}) or {}
                source_name = source_info.get("name", "CryptoCompare") or "CryptoCompare"
                published = item.get("published_on", 0)
                categories = item.get("categories", "")
                text = f"{title} {body}".lower()
                if not title or not _is_relevant(text):
                    continue
                headlines.append(FastHeadline(
                    title=html.unescape(title).strip(),
                    source=source_name,
                    url=url,
                    published_at=published,
                    score=round(_score_text(text), 3),
                    is_breaking=_is_breaking(title),
                    categories=[c.strip() for c in categories.split("|") if c.strip()],
                ))
            return headlines
        except Exception as e:
            logger.debug(f"CryptoCompare news fetch failed: {e}")
            return []

    async def continuous_refresh(self) -> AsyncIterator[FastNewsSnapshot]:
        while True:
            snapshot = await self.refresh()
            yield snapshot
            await asyncio.sleep(self._refresh_interval)
