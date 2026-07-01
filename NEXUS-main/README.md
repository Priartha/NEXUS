# NEXUS: 
A professional-grade BTCUSD perpetual futures scalping system that blends ICT (Inner Circle Trader) concepts with AI-assisted decision making, 12-source confluence signal fusion, and institutional-grade statistical modeling. Built for traders who demand real-time edge detection, rigorous backtesting, and autonomous market analysis.

# Key Features:

Feature	Detail
Unified Scalping Engine v3.0	Fuses 12 data sources (orderflow, orderbook, volume profile, regime, patterns, funding, OI, VWAP, wick rejection, liquidity sweeps, liquidations, self-aware agent) into a single confluence-weighted signal with dynamic leverage (1.5x–3.5x)
Self-Aware Trading Agent	Autonomous AI brain with persistent market memory, Bayesian outcome learning, hourly/daily pattern recognition, and pattern reliability scoring — no external API required
9 Statistical Models	Hurst Exponent, Shannon Entropy, GARCH(1,1), Kalman Filter, Markov Regime Switching, Monte Carlo VaR95, Fourier Cycle Detection, Volume Profile, Fractal Dimension
ICT Pattern Stack	Fair Value Gaps, Order Blocks / Breakers, Equal Highs/Lows, Liquidity Sweeps (with engineered scoring), Market Structure (HH/HL/LH/LL/BOS/CHoCH)
Market Regime Detector v2.0	5-phase classification (trending, range, consolidation, accumulation, distribution) using pure price structure — no lagging ADX
Walk-Forward Backtesting	Statistical significance testing (t-test, DSR, Monte Carlo permutation, PBO), overfitting detection, regime-specific attribution
Real-Time WebSocket UI	React 19 + Lightweight Charts with live signal panel, depth analysis, orderflow, funding/OI, risk dashboard, and audio alerts
AI Integration	Optional Gemini/OpenAI for trade decision grading (A+ through NO_TRADE), sentiment analysis, and ICT reasoning
Paper Trading Engine v3.0	Simulated execution with slippage, funding costs, and full risk management integration
Scalp Risk Manager	Strict 1% risk-per-trade, 3% daily loss limit, dynamic ATR-based stops, Kelly/CVaR95 position sizing


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


# The system generates 1-3 signals per day on 5m timeframe. That means:

3-7 days to hit 15 trades (ensemble calibration threshold)
2-3 weeks to hit 50 trades (optimizer + ensemble fully calibrated)
1 month to have statistically significant live performance data


# Timeline to Live Profitability
Phase	Trades Needed	Est. Time	What Happens
Cold start	0-5	Today	System blocking most signals (edge threshold), getting stopped out on noise
Calibration	5-15	2-3 days	Ensemble starts weighting models, optimizer begins tuning, stops widen
Learning	15-30	1-2 weeks	Self-optimizer adjusts min_confidence/edge per regime, ensemble learns which model dominates in which regime
Stabilization	30-50	2-3 weeks	Walk-forward optimization kicks in, adaptive parameters settle, win rate should approach historical 62.7%  
