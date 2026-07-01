from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.config import settings


@dataclass
class SymbolScore:
    """Score for a symbol's trading opportunity."""
    symbol: str
    price: float
    change_24h: float
    volume_24h: float
    trend_score: float
    volatility_score: float
    momentum_score: float
    overall_score: float
    recommendation: str = "WAIT"


class MultiSymbolScanner:
    """Scans multiple crypto symbols for trading opportunities.
    Uses Binance API to find the best setups across top pairs."""

    TOP_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
        "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
        "LINKUSDT", "DOTUSDT", "MATICUSDT", "LTCUSDT",
    ]

    def __init__(self, base_url: str = ""):
        self.base_url = base_url or settings.market_data_rest_base_url

    async def scan(self, symbols: list[str] | None = None) -> list[SymbolScore]:
        """Scan symbols and rank by opportunity score."""
        symbols = symbols or self.TOP_SYMBOLS
        tasks = [self._analyze_symbol(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scores: list[SymbolScore] = []
        for result in results:
            if isinstance(result, SymbolScore):
                scores.append(result)

        return sorted(scores, key=lambda s: s.overall_score, reverse=True)

    async def _analyze_symbol(self, symbol: str) -> SymbolScore | None:
        """Analyze a single symbol for trading opportunity."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                ticker_resp = await client.get(
                    f"{self.base_url}/api/v3/ticker/24hr",
                    params={"symbol": symbol},
                )
                if ticker_resp.status_code != 200:
                    return None
                ticker = ticker_resp.json()

                klines_resp = await client.get(
                    f"{self.base_url}/api/v3/klines",
                    params={"symbol": symbol, "interval": "1h", "limit": 50},
                )
                if klines_resp.status_code != 200:
                    return None
                klines = klines_resp.json()

            price = float(ticker["lastPrice"])
            change_24h = float(ticker["priceChangePercent"])
            volume_24h = float(ticker["quoteVolume"])

            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            trend = self._calc_trend(closes)
            volatility = self._calc_volatility(closes)
            momentum = self._calc_momentum(closes, volumes)

            overall = (trend * 0.35 + abs(momentum) * 0.35 + volatility * 0.30)

            recommendation = "WAIT"
            if overall > 0.6 and trend > 0.3:
                recommendation = "BUY"
            elif overall > 0.6 and trend < -0.3:
                recommendation = "SELL"
            elif overall > 0.45:
                recommendation = "WATCH"

            return SymbolScore(
                symbol=symbol,
                price=price,
                change_24h=change_24h,
                volume_24h=volume_24h,
                trend_score=trend,
                volatility_score=volatility,
                momentum_score=momentum,
                overall_score=overall,
                recommendation=recommendation,
            )
        except Exception:
            return None

    def _calc_trend(self, closes: list[float]) -> float:
        """Calculate trend strength from -1 to 1."""
        if len(closes) < 20:
            return 0.0
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
        if sma50 == 0:
            return 0.0
        return max(-1.0, min(1.0, (sma20 - sma50) / sma50 * 10))

    def _calc_volatility(self, closes: list[float]) -> float:
        """Calculate normalized volatility 0-1."""
        if len(closes) < 10:
            return 0.0
        returns = [
            (closes[i] - closes[i-1]) / closes[i-1]
            for i in range(1, len(closes))
            if closes[i-1] > 0
        ]
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        vol = variance ** 0.5
        return min(vol * 20, 1.0)

    def _calc_momentum(self, closes: list[float], volumes: list[float]) -> float:
        """Calculate momentum score from -1 to 1."""
        if len(closes) < 14:
            return 0.0
        gains = []
        losses = []
        for i in range(1, min(15, len(closes))):
            diff = closes[i] - closes[i-1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains[:14]) / 14 if len(gains) >= 14 else sum(gains) / max(len(gains), 1)
        avg_loss = sum(losses[:14]) / 14 if len(losses) >= 14 else sum(losses) / max(len(losses), 1)
        if avg_loss == 0:
            return 1.0 if avg_gain > 0 else 0.0
        rs = avg_gain / avg_loss
        rsi = 100 - 100 / (1 + rs)
        return (rsi - 50) / 50
