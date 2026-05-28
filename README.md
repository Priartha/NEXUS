# NEXUS Trading System

Professional-grade BTCUSD perpetual futures scalping system implementing ICT (Inner Circle Trader) concepts with AI-assisted decision making, real-time market analysis, and comprehensive backtesting.

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Architecture

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | React 19 + TypeScript + Vite | Real-time UI with TradingView charts |
| State | Zustand 5 | Lightweight client-side state management |
| Charts | Lightweight Charts 5.2 | Candlestick rendering with overlays |
| Backend | FastAPI + Python 3.14 | REST API + WebSocket streaming |
| Market Data | Delta Exchange (primary) + Binance (fallback) | BTCUSD perpetual futures + spot |
| Storage | SQLite | Candle archive, metrics, trades, performance |
| AI | Gemini API (optional) | LLM-assisted trade decision review |
| Futures | Delta Exchange API | Funding rate, open interest, liquidations |

---

## UI Panels

### Scalp
Futures scalping signal panel with real-time confluence score, directional edge, signal quality blockers, and full breakdown of all 12 data sources. Shows entry zone, stop loss (1.5 ATR), T1 (3.0 ATR, 60% partial), T2 (7.5 ATR), leverage, funding cost estimate, and confidence rating.

### Signals
Primary trade signal display with grade (A+/A/B/C/NO_TRADE), readiness level, confidence gauge, and full ICT confluence breakdown. Shows entry price, stop loss, take profit targets, and invalidation conditions.

### Pats (Patterns)
ICT pattern intelligence dashboard showing:
- Detected Fair Value Gaps (bullish/bearish)
- Order Blocks with breaker status
- Liquidity levels (equal highs/lows)
- Pattern bias meter (bullish/neutral/bearish distribution)
- Bull/Bear scores and average confidence
- Context grid: session, regime, volatility, signal state

### Futures
Real-time BTCUSD perpetual futures context:
- Funding rate (current, annualized, cycle countdown)
- Open interest (change %, trend, momentum confirmation)
- Liquidation clusters (distance, concentration, proximity alerts)
- Estimated funding cost per 8h cycle
- Leverage and margin mode display

### Depth
Orderbook depth analysis showing bid/ask imbalances, spread compression/expansion, depth saturation levels, and accumulation/distribution pattern detection.

### Inst. (Institutional)
Institutional flow metrics including volume profile (POC, VAH, VAL), volume imbalance, realized volatility, and smart money detection patterns.

### Risk
Risk management dashboard with Kelly fraction, CVaR95 estimation, risk of ruin calculation, position sizing calculator, and enforced limits (daily loss, drawdown, max positions).

### Momentum
Momentum indicators including RSI, displacement ratio, trend score, volatility score, and expected move calculations.

### Alerts
System alert center with audio notifications for:
- High confidence signals (>= 75%)
- Engineered liquidity sweeps (score >= 70)
- Regime phase transitions

### Paper
Paper trading engine driven by scalp engine signals:
- Leveraged futures simulation (10x cross margin)
- Partial exits (60% at T1, 40% rides to T2)
- ATR-based trailing stops with breakeven
- Max concurrent positions (2), daily loss limit (3%)
- Cooldown between signals

### BT (Backtest)
Walk-forward backtesting engine with:
- Configurable position size, max hold bars, trailing stops
- Realistic friction (0.01% slippage, 0.02% commission)
- CSV data import for extended historical testing
- Parameter sweep optimization scripting
- Verdict system: GOOD MODEL (PF >= 1.5), PROFITABLE (PF > 1.0), BAD MODEL (PF < 1.0)
- Equity curve visualization
- Full trade history with PnL analysis

### Demo (Forward Test)
Live forward testing with real-time signal evaluation and trade lifecycle tracking.

### Config
Strategy configuration panel for adjusting signal thresholds, risk parameters, and analysis settings.

### Analytics
Risk analytics dashboard with performance metrics, drawdown analysis, and statistical summaries.

---

## Analysis Engine

### ICT Pattern Detection

| Pattern | Description |
|---------|-------------|
| Fair Value Gaps | 3-candle gap detection with fill tracking |
| Order Blocks | Last opposing candle before swing break, breaker detection |
| Liquidity Sweeps | Equal high/low sweep with reclaim confirmation |
| Break of Structure | Trend continuation (BOS) |
| Change of Character | Trend reversal (CHoCH) |
| Premium/Discount | Dealing range equilibrium pricing |
| Killzones | London (02-05 UTC), NY AM (08:30-11 UTC), NY PM (13:30-16 UTC) |

### Technical Indicators

ATR14, EMA 9/20/50/99, RSI14, VWAP, Volume Z-Score, Realized/Parkinson/Garman-Klass Volatility, Displacement Ratio, Trend Score, Volatility Score, Expected Move, SMA 20/50.

### Advanced Statistical Models

| Model | Purpose |
|-------|---------|
| Hurst Exponent | Mean-reverting vs trending regime |
| Shannon Entropy | Price distribution randomness |
| GARCH(1,1) | Volatility forecasting |
| Kalman Filter | Dynamic trend tracking |
| Markov Regime Switching | Bull/bear probability |
| Monte Carlo | 500-path VaR95, max drawdown probability |
| Fourier Transform | Dominant cycle detection |
| Volume Profile | POC, VAH, VAL, volume imbalance |
| Fractal Dimension | Market complexity measurement |

### BTC-Specific Patterns

**Movement Patterns (10):** Killzone Reversal, Volatility Squeeze, Weekend Drift, Halving Cycle, Session Gap Fill, Liquidation Cascade, Fractal S/R Bounce, Time-Price Reversal, Volume Climax, Double Distribution.

**Behavior Patterns (7):** Smart Money Distribution/Accumulation, Retail FOMO, Panic Capitulation, Stop Hunt Reversal, Order Block Wyckoff, Short Squeeze.

### Market Regime Detection v2.0

Phases: trending, range_bound, consolidation, accumulation, distribution.

**Improvements:**
- Price structure analysis (HH/HL vs LH/LL) instead of ADX proxy
- Efficiency ratio + EMA spread momentum requirements
- Volume state confirmation for accumulation/distribution
- Tighter thresholds to prevent false trending classification
- Default phase: range_bound (was trending — 96.5% false positive)

### Multi-Timeframe Context

Analyzes alignment across 1m, 5m, 15m, 1h, 4h timeframes. Used for AI decision context and display only — scalp engine does not block on MTF misalignment.

### Unified Scalping Engine v3.0 — Futures Only

12 data sources fused into a single confluence-weighted signal for BTCUSD perpetual futures:

| Source | Weight | Description |
|--------|--------|-------------|
| Order Flow | 0.25 | Delta, CVD slope, footprint imbalance |
| VWAP | 0.12 | Price deviation, band position, compression |
| Open Interest | 0.12 | Change %, trend, momentum confirmation |
| Funding Rate | 0.10 | Contrarian bias, extreme detection |
| Liquidity Sweeps | 0.15 | Reclaim status, entry triggers |
| Volume Profile | 0.07 | POC, VAH, VAL positioning |
| RSI(3) | 0.07 | Exhaustion reads (oversold/overbought) |
| Killzone | 0.05 | Session timing (London, NY) |
| ICT FVG | 0.05 | Trend-following only (pullback entries) |
| Order Block | 0.05 | Trend-following only (pullback entries) |
| Market Regime | 0.05 | Phase and bias alignment |
| Wick Rejection | 0.08 | Long-wick reversal detection |

**Key improvements from v2.0:**
- Removed all options-specific scoring (IV, gamma, momentum)
- OI and Funding weights increased (0.10 → 0.12, 0.08 → 0.10)
- New **Wick Rejection** source (weight 0.08) — detects candle reversal patterns
- Adaptive threshold normalization when futures data (OI, funding) is missing
- Reason-count gate: minimum 3 data sources required for signal
- Signal builder produces **3.2:1 blended RRR** (SL 1.5 ATR, T1 3.0 ATR, T2 7.5 ATR, 60% partial exit)

### Signal Quality Gates

| Gate | Trending | Range | Consolidation |
|------|----------|-------|---------------|
| Trend strength | ≥ 0.001 | ≥ 0.0003 | ≥ 0.0003 |
| Trend stack | Full EMA alignment | Price vs EMA50 | Skipped |
| Volume impulse | ≥ 0.80 | ≥ 0.50 | ≥ 0.40 |
| Directional edge | ≥ 0.10 | ≥ 0.10 | ≥ 0.05 |
| EMA100 filter | Price must align | Skipped | Skipped |
| Candle close | Strong (≥ 60%) | Discount/premium close | Strong (≥ 60%) |
| RSI momentum | In trade direction | Overbought/oversold | In trade direction |
| Data sources | ≥ 3 reasons | ≥ 3 reasons | ≥ 3 reasons |

**Hard blocks:**
- Never trade in consolidation or range_bound regimes
- Only trade in direction of regime bias
- Require strong candle close in signal direction (trending regime)
- Require minimum 3 contributing data sources for any trade
- Counter-trend signals blocked in trending regimes

### AI Decision Grading

| Grade | Score | Readiness | Meaning |
|-------|-------|-----------|---------|
| A+ | >= 0.90 | Premium | Highest conviction |
| A | >= 0.80 | Premium | High conviction |
| B | >= 0.70 | Qualified | Tradeable |
| C | >= 0.60 | Watchlist | Monitor |
| NO_TRADE | < 0.60 | Avoid | Stay out |

---

## CSV Data Import

Supports 7 formats with auto-detection. Upload any historical OHLCV data for backtesting.

| Format | Headers | Source |
|--------|---------|--------|
| Auto-detect | Any supported format | Automatic |
| Binance | `open_time,open,high,low,close,volume` | Binance API export |
| TradingView | `time,open,high,low,close,volume` | TradingView export |
| CoinMarketCap | `timestamp,open*,high*,low*,close*,volume*` | CoinMarketCap |
| CoinGecko | `date,current_price,total_volume` | CoinGecko |
| Bitfinex/Investing | `Date,Price,Open,High,Low,Vol.,Change %` | Bitfinex, Investing.com |
| Generic OHLCV | Positional (no headers) | Any OHLCV source |

**Features:**
- Auto delimiter detection (comma, semicolon, tab)
- 15+ timestamp formats (ISO 8601, DD-MM-YYYY, MM/DD/YYYY, etc.)
- K/M/B suffix handling for volumes
- Missing high/low estimation
- OHLC validation and correction
- Duplicate removal

---

## Backtesting

### Configuration

| Parameter | Default | Range |
|-----------|---------|-------|
| Initial Balance | $10,000 | Any |
| Position Size | 2% | 0.5% - 10% |
| Max Hold Bars | 6 | 4 - 100 |
| Slippage | 0.01% | Fixed |
| Commission | 0.02% | Fixed |
| Trailing Stop | ON | Toggle |
| Breakeven at | 1.0R | 0.5R - 2.0R |

### Verdict Criteria

| Verdict | Win Rate | Profit Factor | Max Drawdown |
|---------|----------|---------------|--------------|
| GOOD MODEL | >= 50% | >= 1.5 | < 15% |
| NEEDS WORK | 40-50% | 1.0-1.5 | 15-25% |
| BAD MODEL | < 40% | < 1.0 | > 25% |

### Reported Metrics

Total PnL (%), Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown ($/%), Average Win/Loss, Risk/Reward Ratio, Average Hold Bars, Equity Curve, Individual Trade Details.

---

## Risk Management

### Enforced Limits

| Limit | Default |
|-------|---------|
| Max Daily Loss | 3% |
| Max Drawdown | 10% |
| Max Position Size | 2% |
| Max Open Positions | 2 |
| Max Leverage | 10x cross |

### Risk Metrics

Kelly fraction, CVaR95 (Conditional Value at Risk), Risk of Ruin estimation, Win probability, Suggested risk fraction (2% default).

---

## Chart Features

### Overlays (Toggleable)

- **EMA 9/23/99**: Exponential moving averages
- **Pattern Markers**: FVG, Order Block, Liquidity markers
- **Signal Lines**: Entry, stop loss, take profit visualization
- **Structure Labels**: HH/HL/LH/LL/BOS/CHoCH
- **Zone Rendering**: FVG zones, order block zones, liquidity levels

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| R | Focus recent candles |
| F | Fit all candles |
| 1 | Toggle pattern markers |
| 2 | Toggle EMA overlays |
| Right-click | Reset chart view |

### Navigation

Mouse wheel zoom, click-drag pan, pinch zoom (touch), price/time axis scaling. Default 140 visible bars, 8 bar right offset, up to 700 candles stored.

---

## API Endpoints

### Market Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | System health, candle counts |
| GET | `/snapshot?tf=5m` | Full analysis snapshot |
| GET | `/sentiment` | Current sentiment |
| GET | `/scanner` | Multi-symbol scanner (12 pairs) |
| GET | `/news/btc` | BTC news headlines |
| WS | `/ws/chart` | Real-time chart WebSocket |
| WS | `/ws/history` | Real-time history WebSocket |

### Trading

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ai-ict` | AI ICT decision |
| GET | `/risk` | Risk management status |
| GET | `/paper-trades` | List paper trades |
| GET | `/paper-trades/stats` | Paper trade statistics |
| POST | `/paper-trades/toggle` | Toggle paper trading |
| POST | `/paper-trades/reset` | Clear paper trades |

### Backtesting

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/backtest/run` | Run backtest |
| GET | `/backtest/runs` | List backtest runs |
| GET | `/backtest/runs/{id}` | Run detail with trades |
| POST | `/backtest/reset` | Clear backtest data |
| GET | `/csv-import/formats` | Supported CSV formats |
| POST | `/csv-import/parse` | Parse CSV data |
| POST | `/csv-import/backtest` | Backtest from CSV |

### Alerts & Journal

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts` | List alerts |
| POST | `/alerts/{id}/acknowledge` | Acknowledge alert |
| GET | `/signals/journal` | Signal history |
| GET | `/journal` | Trade journal entries |

---

## Data Storage

SQLite database (`data/nexus.db`) with 17 tables:

`signals`, `paper_trades`, `backtest_runs`, `backtest_trades`, `equity_curve`, `alerts`, `trade_journal_entries`, `market_snapshots`, `pattern_history`, `regime_history`, `metrics_history`, `candle_archive`, `ai_decisions_history`, `liquidity_history`, `orderbook_history`, `performance_daily`, `daily_reports`.

---

## Configuration

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Enable AI ICT decision engine |
| `OPENAI_API_KEY` | Enable OpenAI sentiment analysis |
| `NEXUS_API_KEY` | REST/WebSocket authentication |

### Scalping Engine Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NEXUS_SCALP_MIN_CONFLUENCE` | 0.45 | Minimum confluence score |
| `NEXUS_SCALP_MIN_DIRECTIONAL_EDGE` | 0.10 | Minimum directional edge |
| `NEXUS_SCALP_MIN_TREND_STRENGTH` | 0.001 | Minimum trend strength |
| `NEXUS_SCALP_MIN_VOLUME_IMPULSE` | 0.60 | Minimum volume impulse |
| `NEXUS_SCALP_MAX_LEVERAGE` | 10 | Max leverage (10x) |
| `NEXUS_SCALP_MAX_POSITIONS` | 2 | Max concurrent positions |
| `NEXUS_SCALP_DAILY_LOSS_PCT` | 0.03 | Max daily loss (3%) |
| `NEXUS_SCALP_MAX_HOLD_MINUTES` | 30 | Max hold time (30 min) |
| `NEXUS_SCALP_PARTIAL_EXIT` | 0.60 | Partial exit at T1 (60%) |
| `NEXUS_SCALP_BE_PREMIUM_PCT` | 0.25 | Breakeven premium above entry |
| `NEXUS_SCALP_MIN_RRR` | 1.5 | Minimum risk-reward ratio |
| `NEXUS_SCALP_REQUIRE_CANDLE_CONFIRMATION` | false | Require strong close (disabled) |
| `NEXUS_SCALP_REQUIRE_MTF_ALIGNMENT` | false | Require multi-TF alignment (disabled) |

### Wick Rejection Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NEXUS_SCALP_WICK_MIN_RATIO` | 2.0 | Min wick-to-body ratio for rejection |
| `NEXUS_SCALP_WICK_LOOKBACK` | 5 | Candles to analyze for wick pattern |
| `NEXUS_SCALP_WICK_MAX_LOOKBACK` | 8 | Max candles to scan for context |

### Default Settings

- Symbol: BTCUSD (perpetual futures)
- Primary exchange: Delta Exchange (product_id=372)
- Fallback: Binance spot (BTCUSDT)
- Timeframes: 1m, 5m, 15m, 1h
- Candle storage: 1000 per timeframe
- Futures context refresh: 30 seconds
- AI refresh: 180 seconds
- Sentiment refresh: 300 seconds
- History recording: Enabled
- Daily reports: Midnight UTC

---

## Supported Trading Pairs

Scanner monitors 12 pairs: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT, MATIC, LTC.

Primary analysis: BTCUSD perpetual (full feature set).

---

## Dependencies

### Frontend
- React 19.2.5
- Zustand 5.0.13
- Lightweight Charts 5.2.0
- Lucide React 1.14.0
- Zod 3.23.8
- Vite 8.0.11
- TypeScript 6.0.2

### Backend
- FastAPI 0.136.1+
- Uvicorn 0.46.0+
- Websockets 12.0.0+
- HTTPX 0.28.1+
- NumPy 2.4.0+
- Pandas 3.0.2+
- SciPy 1.17.1+
- TA 0.11.0+
- SlowAPI 0.1.9+
