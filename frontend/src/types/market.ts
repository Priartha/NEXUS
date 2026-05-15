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

export interface OptionContract {
  symbol: string
  product_id?: number | null
  contract_type: 'call_options' | 'put_options' | string
  side: 'call' | 'put'
  strike_price: number
  expiry?: string | null
  expiry_timestamp?: number | null
  spot_price?: number | null
  mark_price?: number | null
  best_bid?: number | null
  best_ask?: number | null
  mid_price?: number | null
  spread_pct?: number | null
  bid_iv?: number | null
  ask_iv?: number | null
  volume?: number | null
  open_interest?: number | null
  delta?: number | null
  gamma?: number | null
  theta?: number | null
  vega?: number | null
  rho?: number | null
  score: number
  qualified: boolean
  reason: string
}

export interface OptionsContext {
  timestamp: number
  underlying: string
  momentum_score: number
  bullish_momentum_score: number
  bearish_momentum_score: number
  minimum_momentum_score: number
  momentum_state: 'high' | 'low'
  call_candidate?: OptionContract | null
  put_candidate?: OptionContract | null
  blockers: string[]
  source_count: number
  error?: string | null
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
  option_contract?: OptionContract | null
  momentum_score?: number | null
  options_score?: number | null
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

export interface MarketStats {
  closed_candles: number
  active_fvgs: number
  active_order_blocks: number
  active_liquidity: number
  liquidity_events: number
  signals: number
  btc_patterns?: number
  btc_behaviors?: number
  ob_imbalances?: number
  ob_spread_anomalies?: number
  ob_accumulations?: number
}

export interface MarketMessage {
  update_type: 'snapshot' | 'tick' | 'close' | 'status' | 'sentiment' | 'ai_ict' | 'quote' | 'options_context'
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
  options_context?: OptionsContext | null
  btc_patterns?: BtcPatternContext | null
  sentiment?: SentimentSnapshot | null
  ai_ict?: AiIctDecision | null
  orderbook?: OrderbookData | null
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

export interface MtfSnapshot {
  candles: ApiCandle[]
  fvgs: FVG[]
  order_blocks: OrderBlock[]
  liquidity: LiquidityLevel[]
  structure: StructureLabel[]
  swings: Swing[]
  metrics: MarketMetrics | null
  regime: MarketRegime | null
  current_price: number | null
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
  if (!timestampMs) return '--'
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    day: '2-digit',
  }).format(new Date(timestampMs))
}
