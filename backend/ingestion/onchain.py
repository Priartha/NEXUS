"""
On-Chain Data Integration for Bitcoin.

Provides real-time and historical on-chain metrics:
  - MVRV Z-Score (market value vs realized value)
  - Exchange Net Flow (inflow/outflow from exchanges)
  - Whale Transaction Count (>$100k transactions)
  - SOPR (Spent Output Profit Ratio)

Data sources: Glassnode API, CoinMetrics, or public blockchain explorers.
Falls back to simulated data when APIs are unavailable.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class OnChainSnapshot:
    timestamp: int
    mvrv_zscore: float
    exchange_net_flow: float  # positive = inflow to exchanges (bearish)
    whale_tx_count: int
    sopr: float
    exchange_reserve: float
    realized_price: float
    market_price: float
    active_addresses: int
    transaction_count: int
    hash_rate: float
    description: str


class OnChainDataProvider:
    """
    Fetches and caches on-chain Bitcoin metrics.

    Supports multiple data sources with automatic fallback.
    """

    def __init__(
        self,
        refresh_interval: float = 300.0,
        glassnode_api_key: str | None = None,
    ) -> None:
        self.refresh_interval = refresh_interval
        self.glassnode_api_key = glassnode_api_key
        self._last_refresh: float = 0
        self._cache: OnChainSnapshot | None = None
        self._history: deque[OnChainSnapshot] = deque(maxlen=500)
        self._use_fallback: bool = False
        self._source: str = "none"
        self._fallback_initialized: bool = False

        # Fallback state is deterministic and explicitly labeled. Do not
        # present random synthetic metrics as live on-chain data.
        self._fb_mvrv: float = 1.0
        self._fb_flow: float = 0.0
        self._fb_sopr: float = 1.0
        self._fb_price: float = 60000.0
        self._fb_hash: float = 600.0

    async def refresh(self, btc_price: float | None = None) -> OnChainSnapshot:
        """Fetch latest on-chain data. Returns cached or fresh data."""
        now = time.time()

        if self._cache and (now - self._last_refresh) < self.refresh_interval:
            return self._cache

        snapshot = await self._fetch_onchain(btc_price or self._fb_price)
        if snapshot:
            self._cache = snapshot
            self._history.append(snapshot)
            self._last_refresh = now
        elif self._cache:
            snapshot = self._cache
        else:
            snapshot = self._generate_fallback(btc_price or 60000.0)
            self._cache = snapshot
            self._last_refresh = now

        return snapshot

    async def _fetch_onchain(self, btc_price: float) -> OnChainSnapshot | None:
        """Try to fetch from Glassnode API, fall back to public sources."""
        if self.glassnode_api_key:
            try:
                return await self._fetch_glassnode(btc_price)
            except Exception as e:
                logger.warning(f"Glassnode API failed: {e}")

        try:
            return await self._fetch_public(btc_price)
        except Exception as e:
            logger.warning(f"Public on-chain data failed: {e}")

        return None

    async def _fetch_glassnode(self, btc_price: float) -> OnChainSnapshot | None:
        """Fetch from Glassnode API."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {"X-API-Key": self.glassnode_api_key}

            # MVRV Z-Score
            r1 = await client.get(
                "https://api.glassnode.com/v1/metrics/market/mvrv_z_score",
                params={"a": "BTC", "api_key": self.glassnode_api_key, "timestamp": "now"},
            )
            mvrv = float(r1.json()[-1]["v"]) if r1.status_code == 200 else self._fb_mvrv

            # Exchange Net Flow
            r2 = await client.get(
                "https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_net",
                params={"a": "BTC", "api_key": self.glassnode_api_key, "timestamp": "now"},
            )
            flow = float(r2.json()[-1]["v"]) if r2.status_code == 200 else self._fb_flow

            # SOPR
            r3 = await client.get(
                "https://api.glassnode.com/v1/metrics/indicators/sopr",
                params={"a": "BTC", "api_key": self.glassnode_api_key, "timestamp": "now"},
            )
            sopr = float(r3.json()[-1]["v"]) if r3.status_code == 200 else self._fb_sopr

            self._use_fallback = False
            self._source = "glassnode"
            return OnChainSnapshot(
                timestamp=int(time.time() * 1000),
                mvrv_zscore=round(mvrv, 4),
                exchange_net_flow=round(flow, 2),
                whale_tx_count=self._estimate_whale_tx(btc_price),
                sopr=round(sopr, 4),
                exchange_reserve=self._estimate_reserve(btc_price),
                realized_price=self._estimate_realized(btc_price, mvrv),
                market_price=btc_price,
                active_addresses=self._estimate_active_addresses(),
                transaction_count=self._estimate_tx_count(),
                hash_rate=self._fb_hash,
                description=f"Glassnode: MVRV={mvrv:.2f}, flow={flow:.1f} BTC, SOPR={sopr:.2f}",
            )

    async def _fetch_public(self, btc_price: float) -> OnChainSnapshot | None:
        """Fetch from public APIs (blockchain.info, etc.)."""
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            # Blockchain.info stats
            try:
                r = await client.get("https://api.blockchain.info/stats")
                if r.status_code == 200:
                    data = r.json()
                    self._use_fallback = False
                    self._source = "blockchain.info"
                    return OnChainSnapshot(
                        timestamp=int(time.time() * 1000),
                        mvrv_zscore=self._estimate_mvrv(btc_price, data.get("market_price_usd", btc_price)),
                        exchange_net_flow=0.0,
                        whale_tx_count=int(data.get("n_tx", 0) * 0.02),
                        sopr=0.0,
                        exchange_reserve=data.get("totalbc", 0) * 0.1,
                        realized_price=btc_price * 0.6,
                        market_price=btc_price,
                        active_addresses=data.get("n_unique_addresses", 800000),
                        transaction_count=data.get("n_tx", 300000),
                        hash_rate=data.get("hash_rate", 600) / 1e15,
                        description="Blockchain.info public data; exchange flow and SOPR unavailable from this source",
                    )
            except Exception:
                pass
        return None

    def _generate_fallback(self, btc_price: float) -> OnChainSnapshot:
        """Generate an unavailable snapshot without synthetic signal data."""
        if not self._fallback_initialized:
            self._fb_price = btc_price
            self._fallback_initialized = True
        self._use_fallback = True
        self._source = "fallback"

        self._fb_price = btc_price

        return OnChainSnapshot(
            timestamp=int(time.time() * 1000),
            mvrv_zscore=0.0,
            exchange_net_flow=0.0,
            whale_tx_count=0,
            sopr=0.0,
            exchange_reserve=0.0,
            realized_price=self._estimate_realized(btc_price, self._fb_mvrv),
            market_price=btc_price,
            active_addresses=0,
            transaction_count=0,
            hash_rate=round(self._fb_hash, 2),
            description="On-chain providers unavailable; no synthetic signal generated",
        )

    def _estimate_mvrv(self, price: float, realized: float | None = None) -> float:
        if realized and price > 0:
            return (price - realized) / realized if realized > 0 else 0.0
        return self._fb_mvrv

    def _estimate_realized(self, price: float, mvrv: float) -> float:
        if mvrv > 0:
            return price / (1 + mvrv)
        return price * 0.6

    def _estimate_whale_tx(self, price: float) -> int:
        return 0

    def _estimate_reserve(self, price: float) -> float:
        return 0.0

    def _estimate_active_addresses(self) -> int:
        return 0

    def _estimate_tx_count(self) -> int:
        return 0

    def get_signal(self, btc_price: float) -> dict:
        """
        Generate a trading signal from on-chain data.

        Returns dict with direction, strength, and reasoning.
        """
        snap = self._cache
        if not snap:
            return {"direction": "neutral", "strength": 0.0, "reasons": ["No on-chain data"]}

        reasons: list[str] = []
        direction = "neutral"
        strength = 0.0

        # MVRV Z-Score
        if snap.mvrv_zscore > 3.0:
            direction = "bearish"
            strength += 0.3
            reasons.append(f"MVRV Z-score {snap.mvrv_zscore:.2f} — overvalued")
        elif snap.mvrv_zscore < 0.5:
            direction = "bullish"
            strength += 0.3
            reasons.append(f"MVRV Z-score {snap.mvrv_zscore:.2f} — undervalued")

        # Exchange Net Flow
        if snap.exchange_net_flow > 5000:
            if direction == "bullish":
                direction = "neutral"
            strength += 0.2
            reasons.append(f"Exchange inflow {snap.exchange_net_flow:.0f} BTC — selling pressure")
        elif snap.exchange_net_flow < -5000:
            if direction == "bearish":
                direction = "neutral"
            strength += 0.2
            reasons.append(f"Exchange outflow {abs(snap.exchange_net_flow):.0f} BTC — accumulation")

        # SOPR
        if snap.sopr > 1.5:
            strength += 0.15
            reasons.append(f"SOPR {snap.sopr:.2f} — profit taking")
        elif 0 < snap.sopr < 0.8:
            strength += 0.15
            reasons.append(f"SOPR {snap.sopr:.2f} — capitulation (buying opp)")
        if not reasons:
            reasons.append(snap.description or "No actionable on-chain edge")

        return {
            "direction": direction,
            "strength": round(min(strength, 1.0), 4),
            "reasons": reasons[:3],
            "snapshot": {
                "mvrv_zscore": snap.mvrv_zscore,
                "exchange_net_flow": snap.exchange_net_flow,
                "whale_tx_count": snap.whale_tx_count,
                "sopr": snap.sopr,
            },
        }

    def get_recent_history(self, n: int = 100) -> list[OnChainSnapshot]:
        return list(self._history)[-n:]

    def get_state(self) -> dict:
        return {
            "last_refresh": self._last_refresh,
            "cached": self._cache is not None,
            "history_length": len(self._history),
            "use_fallback": self._use_fallback,
            "source": self._source,
            "glassnode_configured": bool(self.glassnode_api_key),
        }


# Singleton
onchain_provider = OnChainDataProvider()
