# NEXUS Trading System

Professional-grade cryptocurrency trading workstation implementing ICT (Inner Circle Trader) concepts with AI-assisted decision making, real-time market analysis, and comprehensive backtesting.

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
| Data | Binance WebSocket + SQLite | Live market data + persistent storage |
| AI | Gemini API (optional) | LLM-assisted trade decision review |
| Options | Delta Exchange API | BTC options chain analysis |

---

## UI Panels (13 Tabs)

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

### Opts (Options)
BTC options chain analysis with contract scoring based on delta, gamma, spread, moneyness, open interest, and implied volatility. Qualifies CALL/PUT contracts with momentum gating.

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
Paper trading engine with quality gates:
- Minimum confidence threshold (60%)
- Max concurrent positions (1)
- Max daily trades (5)
- Max daily loss (3%)
- Cooldown after 3 consecutive losses (90 min)
- ATR trailing stops with breakeven at 1R

### BT (Backtest)
Walk-forward backtesting engine with:
- Configurable position size, max hold bars, trailing stops
- Realistic friction (0.01% slippage, 0.02% commission)
- CSV data import for extended historical testing
- Verdict system: GOOD MODEL (WR >= 50%, PF >= 1.5, DD < 15%)
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

### Market Regime Detection

Phases: trending, range_bound, consolidation, accumulation, distribution. Uses ADX proxy, ATR compression, efficiency ratio, volume state, and liquidity sweeps.

### Multi-Timeframe Confluence

Analyzes alignment across 1m, 5m, 15m, 1h, 4h timeframes. Applies confluence multiplier (0.85-1.15) based on higher timeframe bias agreement.

### Confluence Scoring

Signals require multiple confirming factors (minimum 0.60 threshold):

| Factor | Weight |
|--------|--------|
| Trend alignment (HTF + local) | +0.20 |
| FVG proximity | +0.15 |
| Order Block proximity | +0.15 |
| Liquidity sweep reclaimed | +0.15 |
| Structure break (BOS) | +0.10 |
| Volume confirmation | +0.10 |
| Killzone timing | +0.10 |

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
| Max Hold Bars | 10 | 4 - 100 |
| Slippage | 0.01% | Fixed |
| Commission | 0.02% | Fixed |
| Trailing Stop | OFF | Toggle |

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
| Max Open Positions | 1 |
| Max Consecutive Losses | 3 |
| Cooldown After Loss | 90 minutes |
| Minimum Confidence | 55% |

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

### Default Settings

- Symbol: BTCUSDT
- Timeframes: 1m, 5m, 15m, 1h
- Candle storage: 700 per timeframe
- AI refresh: 180 seconds
- Sentiment refresh: 300 seconds
- Options refresh: 60 seconds
- History recording: Enabled
- Daily reports: Midnight UTC

---

## Supported Trading Pairs

Scanner monitors 12 pairs: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, DOT, MATIC, LTC.

Primary analysis: BTCUSDT (full feature set).

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
