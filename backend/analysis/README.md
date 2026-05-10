# Backend Analysis Modules

This directory contains the core ICT (Inner Circle Trader) analysis algorithms for real-time market analysis.

## Modules Overview

### `ai_ict.py`
**Purpose**: Generates AI-powered trading decisions by combining technical analysis, sentiment, and market context.

**Key Features**:
- Local deterministic analysis (fallback when AI unavailable)
- Gemini/OpenAI integration for enhanced decision making
- Risk/reward calculations with institutional context
- Options integration for momentum confirmation

**Main Functions**:
- `analyze()`: Full AI analysis with external API calls
- `local_review()`: Deterministic analysis without external dependencies

### `sentiment.py`
**Purpose**: Analyzes market sentiment from RSS news feeds and AI processing.

**Key Features**:
- RSS feed aggregation from multiple sources
- AI-powered sentiment scoring (Gemini/OpenAI)
- Local keyword-based fallback
- Headline scoring and confidence calculation

### `pipeline.py`
**Purpose**: Orchestrates all analysis modules into a unified snapshot.

**Key Features**:
- Coordinates candle aggregation, technical analysis, and AI decisions
- Manages multi-timeframe analysis
- Provides structured data for frontend consumption

### `signals.py`
**Purpose**: Detects trade signals based on ICT principles.

**Key Features**:
- Bullish/bearish signal identification
- Risk/reward ratio calculations
- Institutional context integration

### `market_structure.py`
**Purpose**: Identifies market structure elements (swings, BOS, CHoCH).

**Key Features**:
- Swing high/low detection
- Break of Structure (BOS) identification
- Change of Character (CHoCH) analysis

### `fvg_detector.py`
**Purpose**: Detects Fair Value Gaps (FVGs) in price action.

**Key Features**:
- FVG identification and tracking
- Fill detection and timestamp recording
- Directional bias calculation

### `order_block.py`
**Purpose**: Identifies order blocks and breaker patterns.

**Key Features**:
- Order block detection
- Breaker validation
- Institutional footprint analysis

### `liquidity.py`
**Purpose**: Analyzes liquidity levels and sweeps.

**Key Features**:
- Equal high/low identification
- Touch count tracking
- Sweep detection

### `liquidity_engineering.py`
**Purpose**: Advanced liquidity analysis with engineering scores.

**Key Features**:
- Liquidity sweep scoring
- Reclamation analysis
- Engineering confidence metrics

### `institutional.py`
**Purpose**: Calculates institutional-grade market metrics.

**Key Features**:
- ATR, EMA, RSI calculations
- VWAP and volume analysis
- Volatility measures (Realized, Parkinson, Garman-Klass)
- Institutional bias scoring

### `options.py`
**Purpose**: Options market analysis for momentum confirmation.

**Key Features**:
- Options contract filtering
- Greeks analysis (delta, gamma, etc.)
- Momentum scoring
- Contract qualification

### `regime.py`
**Purpose**: Market regime classification.

**Key Features**:
- Trending vs ranging detection
- Accumulation/distribution phases
- Confidence scoring

### `swing_detector.py`
**Purpose**: Swing point detection for structure analysis.

### `ids.py`
**Purpose**: Institutional Detection System metrics.

### `signals.py`
**Purpose**: Trade signal generation.

### `options.py`
**Purpose**: Options analysis integration.

## Data Flow

1. **Ingestion** (`delta_ws.py`, `delta_rest.py`): Raw market data
2. **Aggregation** (`candle_aggregator.py`): OHLCV candles
3. **Analysis Pipeline** (`pipeline.py`): Technical analysis
4. **AI Integration** (`ai_ict.py`): Final decision making
5. **Broadcast** (`ws_manager.py`): Real-time updates to frontend

## Configuration

Analysis parameters are configured via environment variables in `config.py`. Key settings include:

- `ICT_TIMEFRAMES`: Supported timeframes
- `ICT_AI_ICT_PROVIDER`: AI provider (gemini/openai/local)
- `ICT_SENTIMENT_PROVIDER`: Sentiment analysis provider
- `ICT_MIN_OPTIONS_MOMENTUM_SCORE`: Options filtering threshold

## Testing

Run tests with:
```bash
cd backend
PYTHONPATH=. python -m pytest tests/ -v
```

## Dependencies

- `httpx`: HTTP client for API calls
- `asyncio`: Asynchronous processing
- `logging`: Structured logging
- `dataclasses`: Data structures