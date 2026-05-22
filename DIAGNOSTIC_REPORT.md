# NEXUS Signal Engine - Futures Profitability Optimization

## Futures Backend Optimizations

### 1. Increased Leverage (10x → 20-25x)
- `futures_leverage`: 10 → 20
- `scalp_max_leverage`: 10 → 25
- Higher leverage enables larger position sizes with same risk

### 2. Optimized Risk Parameters
- `scalp_max_risk_pct`: 1% → 2% (more capital per trade)
- `scalp_min_rrr`: 1.5 → 2.0 (better R:R requirement)
- `scalp_max_hold_minutes`: 15 → 25 (allow trades to develop)

### 3. Relaxed Signal Thresholds (More Opportunities)
- `scalp_min_confluence_score`: 0.45 → 0.35
- `scalp_min_directional_edge`: 0.08 → 0.04
- `scalp_min_trend_strength`: 0.001 → 0.0005
- `scalp_min_volume_impulse`: 0.80 → 0.55

### 4. Disabled Restrictive Filters
- `scalp_require_mtf_alignment`: true → false
- `scalp_require_candle_confirmation`: true → false
- These were blocking too many valid signals

### 5. Dynamic Risk Management (Signal Builder)
- High score signals get tighter stops + wider targets
- Score 0.75+: SL=1.0 ATR, TP=10 ATR (10:1 R:R)
- Score 0.35: SL=2.5 ATR, TP=4 ATR (1.6:1 R:R)
- Leverage scales with score (up to 25x)

### 6. Funding Rate Optimization
- Default funding: +0.0001 → -0.0001 (negative = we earn)
- Realistic BTC perpetual funding range: -0.01% to +0.01% per 8h

### 7. Additional Settings
- `futures_max_positions`: 2 → 3
- `scalp_max_entry_distance_pct`: 0.0015 → 0.003 (wider entry range)
- `scalp_partial_exit_pct`: 0.60 → 0.50 (take profit earlier)

---

## Frontend UI Optimization

### Design Language
- **Theme**: Futuristic dark cyberpunk with neon accents
- **Primary Font**: Space Grotesk (geometric, modern)
- **Monospace Font**: Fira Code (for data/numbers)
- **Color Palette**:
  - Neon Green (#00ff88) - Bullish signals, success
  - Neon Red (#ff3366) - Bearish signals, danger
  - Electric Blue (#4488ff) - Neutral, info
  - Cyber Yellow (#ffcc00) - Warnings, alerts

### Key UI Changes

#### 1. Topbar (Futures Terminal Style)
- Glowing logo with animated pulse
- Market readout with glass morphism
- Enhanced connection status indicator

#### 2. Status Strip
- Glass morphism cards with backdrop blur
- Neon icon glow effects
- Smooth hover transitions with lift effect

#### 3. Hero Signal Card
- Enhanced gradient border effects
- Backdrop blur for depth
- Larger action text with glow

#### 4. Scalping Panel (Futures-Optimized)
- Dark glass sections with subtle borders
- Neon-accented section titles
- Signal cards with left border indicator
- Blockers section with red glow effect

### CSS Variables
```css
--accent-green: #00ff88;      /* Primary bullish */
--accent-red: #ff3366;        /* Primary bearish */
--accent-blue: #4488ff;       /* Neutral/info */
--accent-yellow: #ffcc00;      /* Warnings */
--glass-bg: rgba(13,13,24,0.85);
--font-display: 'Space Grotesk';
--font-mono: 'Fira Code';
```

### Animation Effects
- Logo pulse animation (2s cycle)
- Status dot glow animation
- Card hover lift with shadow
- Section reveal animations

## Files Modified

### Backend
1. `backend/config.py` - All futures-related settings
2. `backend/analysis/unified_scalp.py` - Dynamic risk management, volume thresholds
3. `backend/analysis/backtest.py` - Use settings for funding/leverage

### Frontend
1. `frontend/src/index.css` - CSS variables and base styles
2. `frontend/src/App.css` - Component styling
3. `frontend/src/components/SignalLogPanel.tsx` - Fixed unused imports

## Expected Results
- More signals generated due to relaxed thresholds
- Better risk/reward on high-quality signals
- Lower cost basis with negative funding
- Higher profit potential with increased leverage
- Modern, futuristic trading terminal UI
