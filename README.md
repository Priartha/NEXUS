# NEXUS

Real-time BTCUSD ICT charting MVP:

- FastAPI backend seeds Delta Exchange historical candles through REST.
- Delta public WebSocket trades are aggregated into live OHLCV candles.
- Live price display uses Delta `ob_l1` top-of-book quotes instead of delayed ticker prices, while candles stay built from real trades.
- ICT analysis runs only on candle close: swings, structure, FVGs, order blocks, and liquidity.
- Multi-timeframe views are available for `1m`, `5m`, `15m`, and `1h`.
- Signal levels use FVG/order-block midpoint entries, VWAP/equilibrium context, OTE retracement clusters, ATR-buffered stops, and a fixed 1:3 target model.
- Institutional model metrics include ATR14, EMA20/EMA50, RSI14, VWAP, volume z-score, realized volatility, Parkinson volatility, Garman-Klass volatility, displacement ratio, premium/discount, and expected move.
- Liquidity engineering detects buy-side and sell-side sweeps, scores reclaim depth against ATR, and feeds the trade confidence model.
- Market phase detection labels trending, range-bound, consolidation, accumulation, and distribution states, then blocks trades that fight high-confidence phase context.
- Options mode fetches live Delta BTC call/put tickers and only allows final trades when directional momentum clears the configured threshold and the selected contract passes delta, gamma, spread, moneyness, volume, and open-interest checks.
- Real headline sentiment is pulled from public RSS feeds and analyzed by Gemini or OpenAI when an API key is set, with a local keyword fallback when no AI key is configured.
- AI ICT review merges the technical model, liquidity engineering, volatility, structure, risk/reward, and AI sentiment into one final setup only. It provides probabilistic direction, confirmations, blockers, entry, TP 1:3, stop, and invalidation.
- React + Lightweight Charts renders candles plus the single final AI setup, with clean chart navigation, timeframe switching, and an `ICT Marks` toggle for OB/FVG/liquidity study overlays.

## Run

Double-click:

```text
Run NEXUS.cmd
```

This installs missing dependencies, starts backend and frontend in the background, and opens `http://127.0.0.1:5173`.

To stop the app, double-click:

```text
Stop NEXUS.cmd
```

Manual run:

```powershell
.\scripts\start-backend.ps1
.\scripts\start-frontend.ps1
```

Then open `http://127.0.0.1:5173`.

Backend endpoints:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/snapshot`
- `http://127.0.0.1:8000/sentiment`
- `http://127.0.0.1:8000/ai-ict`
- `ws://127.0.0.1:8000/ws/chart`

## Deployment

### Docker Deployment

1. Copy `.env.example` to `.env` and configure your settings:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

2. Build and run with Docker Compose:
   ```bash
   docker-compose up --build
   ```

3. Access the application at `http://localhost:5173`

### Manual Production Deployment

1. Install dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   cd ../frontend
   npm install
   ```

2. Configure environment variables (see `.env.example`)

3. Build frontend:
   ```bash
   cd frontend
   npm run build
   ```

4. Run backend:
   ```bash
   cd backend
   gunicorn --workers=4 --worker-class=uvicorn.workers.UvicornWorker --bind=0.0.0.0:8000 main:app
   ```

5. Serve frontend (using nginx, Apache, or any static file server)

## Configuration

Environment variables:

- `ICT_SYMBOL`, default `BTCUSD`
- `ICT_TIMEFRAME`, default `5m`
- `ICT_TIMEFRAMES`, default `1m,5m,15m,1h`
- `ICT_MAX_CANDLES`, default `500`
- `ICT_AI_ICT_REFRESH_SECONDS`, default `180`
- `ICT_AI_ICT_PROVIDER`, default `auto`; use `gemini` or `local`
- `ICT_SENTIMENT_REFRESH_SECONDS`, default `300`
- `ICT_SENTIMENT_PROVIDER`, default `auto`; use `gemini`, `openai`, or `local`
- `GEMINI_API_KEY`, optional; enables Gemini AI sentiment analysis through Google AI Studio
- `GEMINI_MODEL`, default `gemini-2.5-flash`
- `GEMINI_BASE_URL`, default `https://generativelanguage.googleapis.com/v1beta`
- `ICT_SENTIMENT_MODEL`, default `gpt-5.4-mini`
- `OPENAI_API_KEY`, optional; enables AI sentiment analysis through the OpenAI Responses API
- `OPENAI_BASE_URL`, default `https://api.openai.com/v1`
- `ICT_API_KEY`, optional; when set, requires `x-api-key` for REST and `?api_key=` for websocket access
- `DELTA_REST_BASE_URL`, default `https://api.india.delta.exchange`
- `DELTA_WS_URL`, default `wss://public-socket.india.delta.exchange`
- `ICT_OPTIONS_UNDERLYING`, default `BTC`
- `ICT_OPTIONS_REFRESH_SECONDS`, default `60`
- `ICT_MIN_OPTIONS_MOMENTUM_SCORE`, default `0.40`
- `ICT_OPTIONS_MAX_SPREAD_PCT`, default `0.18`
- `ICT_OPTIONS_MIN_DELTA_ABS`, default `0.35`
- `ICT_OPTIONS_MAX_DELTA_ABS`, default `0.75`
- `ICT_OPTIONS_MAX_MONEYNESS_PCT`, default `0.08`
