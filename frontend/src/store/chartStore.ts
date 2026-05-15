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
  type MtfSnapshot,
  type OrderBlock,
  type OrderbookData,
  type OptionsContext,
  type PaperTradeStats,
  type PriceProjection,
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
  stats: MarketStats | null
  paperTrading: PaperTradeStats | null
  mtfConfluence: Record<string, MtfSnapshot> | null
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
  setMtfConfluence: (mtf: Record<string, MtfSnapshot> | null) => void
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
  stats: null,
  paperTrading: null,
  mtfConfluence: null,
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
      mtfConfluence: null,
      feedStatus: state.selectedTimeframe === timeframe ? state.feedStatus : 'switching',
    })),

  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setMtfConfluence: (mtf) => set({ mtfConfluence: mtf }),

  applyMessage: (message) =>
    set((state) => {
      if (message.update_type === 'status') {
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

      if (message.candles) {
        console.log('Applying snapshot:', message.candles.length, 'candles')
        next.candles = message.candles.map(toChartCandle).slice(-700)
      } else if (message.candle) {
        next.candles = upsertCandle(state.candles, message.candle)
      }

      // Update live candle close with latest quote
      if (message.quote && state.candles.length > 0) {
        const lastCandle = state.candles[state.candles.length - 1]
        if (!lastCandle.isClosed) {
          const price = message.quote.last_trade || message.quote.mid || message.quote.mark_price
          if (price && price !== lastCandle.close) {
            console.log('Updating live candle close from', lastCandle.close, 'to', price)
            const updatedCandle = { ...lastCandle, close: price }
            next.candles = [...state.candles.slice(0, -1), updatedCandle]
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
      if (message.orderbook !== undefined) next.orderbook = message.orderbook
      if (message.stats) next.stats = message.stats
      if (message.paper_trading) next.paperTrading = message.paper_trading

      return next
    }),
}))
