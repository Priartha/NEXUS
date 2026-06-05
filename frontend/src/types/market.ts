import type { CandlestickData, UTCTimestamp } from 'lightweight-charts'

export type Direction = 'bullish' | 'bearish'
export type ConnectionStatus = 'connecting' | 'open' | 'closed' | 'error'

export interface ApiCandle {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  is_closed: boolean
}

export interface Swing {
  timestamp: number
  price: number
  kind: 'high' | 'low'
  index: number
}

export interface StructureLabel {
  timestamp: number
  price: number
  kind: 'HH' | 'HL' | 'LH' | 'LL' | 'BOS' | 'CHoCH'
  broken_swing_price: number
  direction?: Direction | null
}

export interface FVG {
  id: string
  top: number
  bottom: number
  timestamp: number
  direction: Direction
  is_filled: boolean
  fill_timestamp?: number | null
}

export interface OrderBlock {
  id: string
  top: number
  bottom: number
  timestamp: number
  direction: Direction
  is_breaker: boolean
  breaker_timestamp?: number | null
}

export interface LiquidityLevel {
  id: string
  price: number
  kind: 'equal_high' | 'equal_low'
  touch_count: number
  first_touch_timestamp?: number | null
  last_touch_timestamp?: number | null
  swept: boolean
  sweep_timestamp?: number | null
}

export interface LiquidityEvent {
  id: string
  timestamp: number
  side: 'buy_side' | 'sell_side'
  swept_level: number
  sweep_price: number
  close_price: number
  sweep_depth: number
  displacement: number
  reclaimed: boolean
  engineered_score: number
  reason: string
}

export interface OrderbookImbalance {
  id: string
  timestamp: number
  price_level: number
  imbalance_ratio: number
  side: 'buy' | 'sell'
  strength: number
  duration_ms: number
  status: 'active' | 'reversed' | 'filled'
  reversal_timestamp?: number | null
  reversal_price?: number | null
}

export interface SpreadDynamics {
  id: string
  timestamp: number
  spread: number
  spread_pct: number
  spread_zscore: number
  bid: number
  ask: number
  bid_ask_midpoint: number
  status: 'normal' | 'tight' | 'wide' | 'squeezed'
  anomaly_type?: 'compression' | 'expansion' | 'inversion' | null
}

export interface OrderbookDepthLevel {
  id: string
  timestamp: number
  price_level: number
  level_type: 'bid' | 'ask'
  estimated_size: number
  order_count: number
  depth_tier: number
  saturation: number
  touched_count?: number
  last_touch?: number | null
  filled_count?: number
}

export interface OrderbookAccumulation {
  id: string
  timestamp: number
  price_range_low: number
  price_range_high: number
  side: 'accumulation' | 'distribution'
  confidence: number
  volume_ratio: number
  pattern_duration_ms: number
  candle_touches: number
  status: 'active' | 'completed'
  completion_timestamp?: number | null
  completion_price?: number | null
}

export interface OrderbookData {
  imbalances: OrderbookImbalance[]
  spread_dynamics: SpreadDynamics[]
  depth_levels: OrderbookDepthLevel[]
  accumulations: OrderbookAccumulation[]
}

export interface MarketMetrics {
  timestamp: number
  atr14: number
  ema20: number
  ema50: number
  rsi14: number
  vwap: number
  vwap_distance_pct: number
  volume_zscore: number
  realized_volatility: number
  parkinson_volatility: number
  garman_klass_volatility: number
  displacement_ratio: number
  premium_discount: number
  equilibrium: number
  range_high: number
  range_low: number
  trend_score: number
  volatility_score: number
  institutional_bias: 'bullish' | 'bearish' | 'neutral'
  bias_score: number
  expected_move: number
  expected_move_pct: number
  hurst_exponent: number
  shannon_entropy: number
  garch_volatility: number
  garch_persistence: number
  kalman_trend: number
  kalman_trend_strength: number
  markov_bull_prob: number
  markov_bear_prob: number
  markov_regime_certainty: number
  monte_carlo_var95: number
  monte_carlo_expected_return: number
  monte_carlo_max_drawdown: number
  fourier_dominant_period: number
  fourier_cycle_strength: number
  volume_profile_poc: number
  volume_profile_vah: number
  volume_profile_val: number
  volume_profile_imbalance: number
  return_skewness: number
  return_kurtosis: number
  fractal_dimension: number
  ljung_box_statistic: number
  autocorrelation_lag1: number
}

export interface PriceProjection {
  timestamp: number
  direction: 'bullish' | 'bearish' | 'neutral'
  probability: number
  expected_move: number
  expected_high: number
  expected_low: number
  invalidation: number
  score: number
  reason: string
}

export interface MarketQuote {
  symbol: string
  timestamp: number
  source: 'ob_l1' | 'trades' | 'ticker' | 'v2/ticker'
  bid?: number | null
  ask?: number | null
  mid?: number | null
  last_trade?: number | null
  mark_price?: number | null
  spot_price?: number | null
  bid_qty?: number | null
  ask_qty?: number | null
  latency_ms?: number | null
}

export interface MarketRegime {
  timestamp: number
  phase: 'trending' | 'range_bound' | 'consolidation' | 'accumulation' | 'distribution'
  confidence: number
  range_high: number
  range_low: number
  range_mid: number
  width_pct: number
  atr_compression: number
  efficiency_ratio: number
  volume_state: 'compressed' | 'normal' | 'expanding'
  bias: 'bullish' | 'bearish' | 'neutral'
  reason: string
}

export interface SentimentHeadline {
  title: string
  source: string
  url: string
  published_at?: number | null
  score: number
}

export interface SentimentSnapshot {
  label: 'loading' | 'bullish' | 'bearish' | 'neutral' | 'unavailable'
  score: number
  confidence: number
  source_count: number
  updated_at?: number | null
  headlines: SentimentHeadline[]
  provider: 'gemini' | 'openai' | 'local_keyword'
  model?: string | null
  summary: string
  drivers: string[]
  risk_flags: string[]
  error?: string | null
}

export interface AiIctDecision {
  timestamp: number
  timeframe: string
  provider: 'gemini' | 'deterministic'
  model?: string | null
  direction: 'bullish' | 'bearish' | 'neutral'
  grade: 'A+' | 'A' | 'B' | 'C' | 'NO_TRADE'
  readiness: 'premium' | 'qualified' | 'watchlist' | 'avoid'
  confidence: number
  setup_score: number
  entry?: number | null
  stop_loss?: number | null
  take_profit?: number | null
  risk_reward?: number | null
  invalidation?: number | null
  primary_signal_id?: string | null
  summary: string
  confirmations: string[]
  blockers: string[]
  calculations: string[]
  guarantee: string
  updated_at?: number | null
  error?: string | null
}

export interface TradeSignal {
  id: string
  timestamp: number
  side: 'buy' | 'sell'
  entry: number
  stop_loss: number
  trailing_stop?: number | null
  trailing_mode?: string
  exit_price: number
  risk_reward: number
  confidence: number
  reason: string
  status: 'pending' | 'open' | 'target_hit' | 'stopped'
  exit_timestamp?: number | null
  institutional_score: number
  liquidity_score: number
  bias_score: number
  expected_move: number
  win_probability?: number
  kelly_fraction?: number
  suggested_risk_fraction?: number
  cvar95_loss?: number
  risk_of_ruin?: number
  model: string
  garch_volatility?: number
  markov_regime?: string
  markov_certainty?: number
  monte_carlo_var95?: number
  signal_decay?: number
  bayesian_fused?: boolean
  bayesian_signal_count?: number
}

export interface BtcPattern {
  id: string
  timestamp: number
  name: string
  direction: Direction | 'neutral'
  confidence: number
  score: number
  description: string
  candle_count: number
  completed: boolean
  completion_timestamp?: number | null
  completion_price?: number | null
}

export interface BtcInvestorBehavior {
  id: string
  timestamp: number
  behavior_type: string
  side: Direction
  confidence: number
  intensity: number
  description: string
  price_level: number
  volume_ratio: number
  is_active: boolean
}

export interface BtcPatternContext {
  timestamp: number
  killzone?: string | null
  session: string
  weekday: number
  hour: number
  is_weekend: boolean
  halving_phase: string
  volatility_regime: string
  fractal_clusters: string[]
  patterns: BtcPattern[]
  investor_behaviors: BtcInvestorBehavior[]
  bullish_pattern_score: number
  bearish_pattern_score: number
  pattern_signal: 'bullish' | 'bearish' | 'neutral'
}

export interface PsychologySignal {
  id: string
  timestamp: number
  type: string
  side: 'bullish' | 'bearish' | 'neutral'
  intensity: number
  confidence: number
  description: string
  price_level: number
  reason: string
}

export interface PsychologySnapshot {
  timestamp: number
  fear_greed_score: number
  fear_greed_label: 'extreme_fear' | 'fear' | 'neutral' | 'greed' | 'extreme_greed'
  retail_participation: number
  smart_money_activity: number
  emotional_state: 'panic' | 'cautious' | 'balanced' | 'euphoric' | 'exhausted'
  trap_risk: number
  conviction_score: number
  psychological_levels: number[]
  active_signals: PsychologySignal[]
  summary: string
}

export interface TrendQuality {
  timestamp: number
  smoothness: number
  consistency: number
  pullback_quality: number
  acceleration: number
  is_choppy: boolean
  reliability: number
}

export interface RangeQuality {
  timestamp: number
  boundary_clarity: number
  bounce_consistency: number
  internal_structure: number
  is_breaking_out: boolean
  breakout_quality: number
  reliability: number
}

export interface ReadabilitySnapshot {
  timestamp: number
  overall_score: number
  grade: 'A+' | 'A' | 'B+' | 'B' | 'C+' | 'C' | 'D' | 'F'
  candle_clarity: number
  trend_quality: TrendQuality | null
  range_quality: RangeQuality | null
  noise_level: number
  structure_reliability: number
  tradeability: 'excellent' | 'good' | 'fair' | 'poor' | 'avoid'
  dominant_pattern: 'trending' | 'ranging' | 'chopping' | 'breaking_out' | 'unknown'
  key_observations: string[]
}

export interface MarketStats {
  closed_candles: number
  active_fvgs: number
  active_order_blocks: number
  active_liquidity: number
  liquidity_events: number
  signals: number
  scalp_signals?: number
  scalp_blocked?: number
  btc_patterns?: number
  btc_behaviors?: number
  fear_greed?: string
  readability_grade?: string
  tradeability?: string
  ob_imbalances?: number
  ob_spread_anomalies?: number
  ob_accumulations?: number
  ensemble?: {
    total_trades: number
    win_rate: number
    total_pnl_pct: number
    avg_pnl_per_trade: number
    model_weights: Record<string, number>
    regime_weights: Record<string, Record<string, number>>
  }
  self_optimizer?: {
    total_attempts: number
    kept_attempts: number
    current_params: Record<string, number>
    regime_performance: Record<string, { trades: number; win_rate: number; total_pnl: number }>
    signal_quality?: Record<string, {
      quality_score: number
      win_rate: number
      avg_pnl: number
      trades: number
    }>
    active_learning?: boolean
  }
  anomaly_detector?: {
    observations: number
    anomaly_count: number
    baseline_return_mean: number
    baseline_return_std: number
    current_volatility: number
  }
  system_health?: {
    self_heal: Record<string, { alive: boolean; last_ok_ago: number; restarts: number; last_error: string }>
    panel_freshness: Record<string, { age_seconds: number; threshold: number; is_stale: boolean }>
  }
}

export interface InstitutionalMetrics {
  hurst_exponent: number
  hurst_regime: 'mean_reverting' | 'trending' | 'random'
  shannon_entropy: number
  entropy_factor: number
  garch_volatility: number
  garch_persistence: number
  kalman_trend: number
  kalman_trend_strength: number
  kalman_prediction_error: number
  markov_bull_prob: number
  markov_bear_prob: number
  markov_transition_prob: number
  markov_regime_certainty: number
  monte_carlo_var95: number
  monte_carlo_expected_return: number
  monte_carlo_max_drawdown: number
  monte_carlo_p5: number
  monte_carlo_p50: number
  monte_carlo_p95: number
  fourier_dominant_period: number
  fourier_cycle_strength: number
  volume_profile_poc: number
  volume_profile_vah: number
  volume_profile_val: number
  volume_profile_imbalance: number
  return_skewness: number
  return_kurtosis: number
  fractal_dimension: number
  ljung_box_statistic: number
  autocorrelation_lag1: number
  momentum_macd: number
  momentum_macd_signal: number
  momentum_macd_histogram: number
  momentum_roc: number
  momentum_tsi: number
}

export interface MarketMessage {
  update_type: 'snapshot' | 'tick' | 'close' | 'status' | 'sentiment' | 'ai_ict' | 'quote' | 'futures_context'
  symbol?: string
  timeframe?: string
  quote?: MarketQuote | null
  candle?: ApiCandle | null
  candles?: ApiCandle[]
  swings?: Swing[]
  structure?: StructureLabel[]
  fvgs?: FVG[]
  order_blocks?: OrderBlock[]
  liquidity?: LiquidityLevel[]
  liquidity_events?: LiquidityEvent[]
  signals?: TradeSignal[]
  metrics?: MarketMetrics | null
  projection?: PriceProjection | null
  regime?: MarketRegime | null
  psychology?: PsychologySnapshot | null
  readability?: ReadabilitySnapshot | null
  btc_patterns?: BtcPatternContext | null
  sentiment?: SentimentSnapshot | null
  ai_ict?: AiIctDecision | null
  orderbook?: OrderbookData | null
  scalp?: ScalpContext | null
  scalp_risk?: ScalpRiskSummary | null
  stats?: MarketStats
  status?: string
  message?: string
  retry_in_seconds?: number
  available_timeframes?: string[]
  paper_trading?: PaperTradeStats
}

export type ChartCandle = CandlestickData<UTCTimestamp> & {
  volume: number
  isClosed: boolean
}

export interface PaperTradeStats {
  total_trades: number
  closed_trades: number
  winning_trades: number
  losing_trades: number
  total_pnl: number
  win_rate: number
}

export interface PaperTrade {
  id: string
  signal_id?: string
  symbol: string
  timeframe: string
  side: 'buy' | 'sell'
  entry_price: number
  stop_loss: number
  take_profit: number
  quantity: number
  status: 'open' | 'closed'
  opened_at: number
  closed_at?: number | null
  exit_price?: number | null
  pnl?: number | null
  pnl_pct?: number | null
  risk_reward?: number | null
  confidence?: number | null
  reason?: string | null
  close_reason?: string | null
}

export interface BacktestRun {
  id: string
  symbol: string
  timeframe: string
  start_date: number
  end_date: number
  candle_count: number
  initial_balance: number
  final_balance: number
  created_at?: number
  total_pnl: number
  total_pnl_pct: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  profit_factor: number
  max_drawdown: number
  max_drawdown_pct: number
  sharpe_ratio: number
  trades?: BacktestTrade[]
  equity_curve?: EquityPoint[]
}

export interface BacktestTrade {
  id: string
  timestamp: number
  side: string
  entry_price: number
  stop_loss: number
  exit_price: number
  exit_timestamp?: number | null
  pnl?: number | null
  pnl_pct?: number | null
  risk_reward?: number | null
  confidence?: number | null
  reason?: string | null
  status: string
}

export interface EquityPoint {
  timestamp: number
  account_balance: number
  drawdown: number
  drawdown_pct: number
}

export interface Alert {
  id: string
  timestamp: number
  type: string
  severity: string
  symbol?: string | null
  title: string
  message?: string | null
  data?: unknown
  acknowledged: number
}

export const DEMO_PATTERNS: BtcPatternContext = {
  timestamp: Date.now(),
  session: 'ny',
  weekday: 2,
  hour: 14,
  is_weekend: false,
  halving_phase: 'pre_halving_run',
  volatility_regime: 'low',
  fractal_clusters: ['near_pivot_80950', 'near_pivot_80780'],
  pattern_signal: 'neutral',
  bullish_pattern_score: 0.18,
  bearish_pattern_score: 0.15,
  patterns: [
    {
      id: 'demo_halving',
      timestamp: Date.now() - 60000,
      name: 'halving_cycle_pre_halving_run',
      direction: 'bullish',
      confidence: 0.58,
      score: 0.21,
      description: 'Pre-halving run-up: BTC typically sees parabolic move 6-12 months before halving',
      candle_count: 20,
      completed: false,
    },
    {
      id: 'demo_double_dist',
      timestamp: Date.now() - 120000,
      name: 'double_distribution_top',
      direction: 'bearish',
      confidence: 0.62,
      score: 0.15,
      description: 'Double distribution: equal highs near 80950, BTC often breaks down after retesting resistance twice',
      candle_count: 40,
      completed: false,
    },
    {
      id: 'demo_fractal_support',
      timestamp: Date.now() - 180000,
      name: 'fractal_support_bounce',
      direction: 'bullish',
      confidence: 0.55,
      score: 0.12,
      description: 'Fractal support: price near historical swing lows, BTC tends to bounce from fractal levels',
      candle_count: 40,
      completed: false,
    },
  ],
  investor_behaviors: [
    {
      id: 'demo_stop_hunt',
      timestamp: Date.now() - 90000,
      behavior_type: 'stop_hunt_reversal',
      side: 'bullish',
      confidence: 0.61,
      intensity: 0.32,
      description: 'Stop hunt + reversal: sell-side swept then reclaimed, classic smart money stop hunt',
      price_level: 80850,
      volume_ratio: 1.2,
      is_active: true,
    },
    {
      id: 'demo_distribution',
      timestamp: Date.now() - 150000,
      behavior_type: 'smart_money_distribution',
      side: 'bearish',
      confidence: 0.52,
      intensity: 0.25,
      description: 'Smart money distribution: institutions selling into retail buying pressure',
      price_level: 80900,
      volume_ratio: 0.8,
      is_active: true,
    },
  ],
}

export function toChartTime(timestampMs: number): UTCTimestamp {
  return Math.floor(timestampMs / 1000) as UTCTimestamp
}

export function toChartCandle(candle: ApiCandle): ChartCandle {
  return {
    time: toChartTime(candle.timestamp),
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    volume: candle.volume,
    isClosed: candle.is_closed,
  }
}

export function formatPrice(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '--'
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatTimestamp(timestampMs?: number | null): string {
  if (timestampMs == null || timestampMs === 0) return '--'
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: '2-digit',
  }).format(new Date(timestampMs))
}

export interface ScalpOrderFlow {
  timestamp: number
  delta: number
  cvd: number
  cvd_slope: number
  volume_delta_ratio: number
  absorption_ratio: number
  aggressive_buy_volume: number
  aggressive_sell_volume: number
  footprint_imbalance: number
}

export interface ScalpFunding {
  timestamp: number
  current_rate: number
  projected_8h: number
  annualized_rate: number
  next_reset_ms: number
  is_extreme: boolean
  contrarian_bias: string
}

export interface ScalpFundingRate {
  timestamp: number
  current_rate: number
  annualized: number
  funding_apr: number
  predicted_8h: number
  time_to_next: number
  is_extreme: boolean
  bias: string
}

export interface ScalpOpenInterest {
  timestamp: number
  current_oi: number
  oi_change_pct: number
  oi_delta: number
  oi_trend: string
  momentum_confirmation: boolean
}

export interface ScalpLiquidationLevel {
  price: number
  size: number
  side: string
  distance_pct: number
  cluster_strength: number
}

export interface ScalpVWAP {
  timestamp: number
  vwap: number
  upper_band_1sd: number
  lower_band_1sd: number
  upper_band_2sd: number
  lower_band_2sd: number
  price_deviation_pct: number
  is_compressed: boolean
}

export interface ScalpVolumeProfile {
  timestamp: number
  poc: number
  vah: number
  val: number
  value_area_width_pct: number
}

export interface ScalpLiquiditySweep {
  timestamp: number
  level: number
  side: string
  sweep_type: string
  reclaimed: boolean
  strength: number
  entry_trigger: boolean
}

export interface ScalpSignal {
  id: string
  timestamp: number
  signal_type: string
  entry_zone_low: number
  entry_zone_high: number
  sl_level: number
  target_1: number
  target_2: number
  leverage: number
  reason: string
  risk_reward: number
  confidence: string
  time_limit_ms: number
  max_hold_minutes: number
  status: string
  entry_triggered: boolean
  score: number
  expected_move: number
  side: string
  entry: number
  stop_loss: number
  exit_price: number
  model: string
  partial_exit_pct: number
  funding_impact_pct: number
  enriched_features?: Record<string, unknown> | null
}

export interface ScalpWickRejection {
  active_upper_wick_candles: number
  active_lower_wick_candles: number
  max_upper_wick_ratio: number
  max_lower_wick_ratio: number
  avg_upper_wick_ratio: number
  avg_lower_wick_ratio: number
  bearish_rejection_active: boolean
  bullish_rejection_active: boolean
  rejection_strength: number
  description: string
}

export interface ScalpContext {
  timestamp: number
  order_flow: ScalpOrderFlow | null
  funding: ScalpFunding | null
  funding_rate: ScalpFundingRate | null
  open_interest: ScalpOpenInterest | null
  liquidation_levels: ScalpLiquidationLevel[]
  vwap: ScalpVWAP | null
  volume_profile: ScalpVolumeProfile | null
  liquidity_sweeps: ScalpLiquiditySweep[]
  signals: ScalpSignal[]
  trade_blocked_reasons: string[]
  rsi_3: number
  spot_volume_ok: boolean
  macro_event_block: boolean
  futures_leverage: number
  estimated_funding_cost_8h: number
  wick_rejection: ScalpWickRejection | null
  ai_brain_active?: boolean
  ai_intelligence?: AiAgentStatus | null
  common_sense_warnings?: string[]
}

export interface AiAgentStatus {
  decisions: number
  accuracy: number
  memory_stats: {
    total_trades: number
    winning_trades: number
    win_rate: number
    total_pnl: number
    avg_pnl_per_trade: number
    patterns_learned: number
    market_hours_learned: number
  }
  patterns_learned: number
  market_hours_knowledge: number
}

export interface ScalpRiskSummary {
  current_balance: number
  initial_balance: number
  peak_balance?: number
  drawdown_pct?: number
  daily_pnl: number
  daily_trades: number
  daily_wins: number
  daily_losses: number
  daily_win_rate: number
  daily_loss_pct: number
  max_daily_loss_pct: number
  daily_loss_hit: boolean
  consecutive_losses: number
  max_consecutive_losses: number
  open_futures: number
  total_open: number
  max_positions: number
  max_risk_per_trade_pct: number
  max_leverage: number
  min_rrr: number
  max_hold_minutes: number
  total_trades?: number
  total_win_rate?: number
  kelly_fraction?: number
}
