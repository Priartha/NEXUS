import { create } from 'zustand'
import {
  type ApiCandle,
  type AiIctDecision,
  type BtcPatternContext,
  type ChartCandle,
  type ConnectionStatus,
  type FVG,
  type LiquidityEvent,
  type LiquidityLevel,
  type MarketMessage,
  type MarketMetrics,
  type MarketQuote,
  type MarketRegime,
  type MarketStats,
  type OrderBlock,
  type OrderbookData,
  type OptionsContext,
  type PaperTradeStats,
  type PriceProjection,
  type PsychologySnapshot,
  type ReadabilitySnapshot,
  type ScalpContext,
  type ScalpRiskSummary,
  type SentimentSnapshot,
  type StructureLabel,
  type Swing,
  type TradeSignal,
  toChartCandle,
} from '../types/market'

interface ChartStore {
  candles: ChartCandle[]
  lastApiCandle: ApiCandle | null
  fvgs: FVG[]
  orderBlocks: OrderBlock[]
  liquidity: LiquidityLevel[]
  liquidityEvents: LiquidityEvent[]
  signals: TradeSignal[]
  swings: Swing[]
  structure: StructureLabel[]
  metrics: MarketMetrics | null
  quote: MarketQuote | null
  regime: MarketRegime | null
  optionsContext: OptionsContext | null
  projection: PriceProjection | null
  sentiment: SentimentSnapshot | null
  aiIct: AiIctDecision | null
  orderbook: OrderbookData | null
  btcPatterns: BtcPatternContext | null
  psychology: PsychologySnapshot | null
  readability: ReadabilitySnapshot | null
  stats: MarketStats | null
  paperTrading: PaperTradeStats | null
  scalpContext: ScalpContext | null
  scalpRisk: ScalpRiskSummary | null
  availableTimeframes: string[]
  selectedTimeframe: string
  symbol: string
  timeframe: string
  connectionStatus: ConnectionStatus
  feedStatus: string
  feedMessage: string
  lastUpdateType: string
  setTimeframe: (timeframe: string) => void
  setConnectionStatus: (status: ConnectionStatus) => void
  applyMessage: (message: MarketMessage) => void
}

function upsertCandle(candles: ChartCandle[], candle: ApiCandle): ChartCandle[] {
  const next = [...candles]
  const chartCandle = toChartCandle(candle)
  const last = next[next.length - 1]

  if (last && last.time === chartCandle.time) {
    next[next.length - 1] = chartCandle
  } else {
    next.push(chartCandle)
  }

  return next
    .sort((left, right) => Number(left.time) - Number(right.time))
    .slice(-700)
}

export const useChartStore = create<ChartStore>((set) => ({
  candles: [],
  lastApiCandle: null,
  fvgs: [],
  orderBlocks: [],
  liquidity: [],
  liquidityEvents: [],
  signals: [],
  swings: [],
  structure: [],
  metrics: null,
  quote: null,
  regime: null,
  optionsContext: null,
  projection: null,
  sentiment: null,
  aiIct: null,
  orderbook: null,
  btcPatterns: null,
  psychology: null,
  readability: null,
  stats: null,
  paperTrading: null,
  scalpContext: null,
  scalpRisk: null,
  availableTimeframes: ['1m', '5m', '15m', '1h'],
  selectedTimeframe: '5m',
  symbol: 'BTCUSD',
  timeframe: '5m',
  connectionStatus: 'connecting',
  feedStatus: 'booting',
  feedMessage: '',
  lastUpdateType: 'snapshot',

  setTimeframe: (timeframe) =>
    set((state) => ({
      selectedTimeframe: timeframe,
      timeframe,
      candles: [],
      lastApiCandle: null,
      fvgs: [],
      orderBlocks: [],
      liquidity: [],
      liquidityEvents: [],
      signals: [],
      swings: [],
      structure: [],
      metrics: null,
      projection: null,
      aiIct: null,
      quote: null,
      regime: null,
      optionsContext: null,
      orderbook: null,
      stats: null,
      psychology: null,
      readability: null,
      feedStatus: state.selectedTimeframe === timeframe ? state.feedStatus : 'switching',
    })),

  setConnectionStatus: (status) => set({ connectionStatus: status }),

  applyMessage: (message) =>
    set((state) => {
      const msg = message as unknown as Record<string, unknown>
      const updateType = msg.update_type as string

      if (updateType === 'status') {
        return {
          sentiment: message.sentiment ?? state.sentiment,
          aiIct: message.ai_ict ?? state.aiIct,
          feedStatus: message.status ?? state.feedStatus,
          feedMessage: message.message ?? '',
          symbol: message.symbol ?? state.symbol,
          timeframe: message.timeframe ?? state.timeframe,
          selectedTimeframe: message.timeframe ?? state.selectedTimeframe,
          availableTimeframes: message.available_timeframes ?? state.availableTimeframes,
          lastUpdateType: message.update_type,
        }
      }

      const next: Partial<ChartStore> = {
        symbol: message.symbol ?? state.symbol,
        timeframe: message.timeframe ?? state.timeframe,
        selectedTimeframe: message.timeframe ?? state.selectedTimeframe,
        availableTimeframes: message.available_timeframes ?? state.availableTimeframes,
        lastUpdateType: message.update_type,
        feedStatus:
          message.update_type === 'tick'
            ? 'live_tick'
            : message.update_type === 'sentiment' || message.update_type === 'ai_ict' || message.update_type === 'quote' || message.update_type === 'options_context'
              ? state.feedStatus
              : 'analysis_ready',
        feedMessage: '',
      }

      // Handle snapshot candles
      const rawCandles = msg.candles as ApiCandle[] | undefined
      if (rawCandles && rawCandles.length > 0) {
        console.log(`[Store] Applying ${rawCandles.length} candles from ${updateType}`)
        next.candles = rawCandles.map(toChartCandle).slice(-700)
      } else if (message.candle) {
        // Single candle update (tick/close)
        if (state.candles.length === 0) {
          console.log('[Store] Single candle but no history, skipping')
        } else {
          next.candles = upsertCandle(state.candles, message.candle)
        }
      }

      // Update live candle close with latest quote - use next.candles if available
      const currentCandles = next.candles ?? state.candles
      if (message.quote && currentCandles.length > 0) {
        const lastCandle = currentCandles[currentCandles.length - 1]
        if (!lastCandle.isClosed) {
          const price = message.quote.last_trade || message.quote.mid || message.quote.mark_price
          if (price && price !== lastCandle.close) {
            const updatedCandle = { ...lastCandle, close: price }
            next.candles = [...currentCandles.slice(0, -1), updatedCandle]
          }
        }
      }

      if (message.candle) next.lastApiCandle = message.candle
      if (message.quote !== undefined) next.quote = message.quote
      if (message.fvgs) next.fvgs = message.fvgs
      if (message.order_blocks) next.orderBlocks = message.order_blocks
      if (message.liquidity) next.liquidity = message.liquidity
      if (message.liquidity_events) next.liquidityEvents = message.liquidity_events
      if (message.signals) next.signals = message.signals
      if (message.swings) next.swings = message.swings
      if (message.structure) next.structure = message.structure
      if (message.metrics !== undefined) next.metrics = message.metrics
      if (message.projection !== undefined) next.projection = message.projection
      if (message.regime !== undefined) next.regime = message.regime
      if (message.options_context !== undefined) next.optionsContext = message.options_context
      if (message.sentiment !== undefined) next.sentiment = message.sentiment
      if (message.ai_ict !== undefined) next.aiIct = message.ai_ict
      if (message.btc_patterns !== undefined) next.btcPatterns = message.btc_patterns
      if (message.psychology !== undefined) next.psychology = message.psychology
      if (message.readability !== undefined) next.readability = message.readability
      if (message.orderbook !== undefined) next.orderbook = message.orderbook
      if (message.stats) next.stats = message.stats
      if (message.paper_trading) next.paperTrading = message.paper_trading
      if (message.scalp !== undefined) next.scalpContext = message.scalp
      if (message.scalp_risk !== undefined) next.scalpRisk = message.scalp_risk

      return next
    }),
}))
