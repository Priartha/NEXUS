import { useState, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Gauge,
  RefreshCw,
  Target,
  Wifi,
  WifiOff,
} from 'lucide-react'
import './App.css'
import { Chart } from './components/Chart'
import { useMarketSocket } from './hooks/useMarketSocket'
import { useChartStore } from './store/chartStore'
import { formatPrice, formatTimestamp } from './types/market'

function App() {
  const { reconnect } = useMarketSocket()
  const candles = useChartStore((state) => state.candles)
  const lastApiCandle = useChartStore((state) => state.lastApiCandle)
  const liquidityEvents = useChartStore((state) => state.liquidityEvents)
  const metrics = useChartStore((state) => state.metrics)
  const quote = useChartStore((state) => state.quote)
  const regime = useChartStore((state) => state.regime)
  const projection = useChartStore((state) => state.projection)
  const sentiment = useChartStore((state) => state.sentiment)
  const aiIct = useChartStore((state) => state.aiIct)
  const availableTimeframes = useChartStore((state) => state.availableTimeframes)
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const setTimeframe = useChartStore((state) => state.setTimeframe)
  const symbol = useChartStore((state) => state.symbol)
  const timeframe = useChartStore((state) => state.timeframe)
  const connectionStatus = useChartStore((state) => state.connectionStatus)
  const feedStatus = useChartStore((state) => state.feedStatus)
  const feedMessage = useChartStore((state) => state.feedMessage)
  const latest = candles.at(-1)
  const previous = candles.at(-2)
  const displayPrice = quote?.mid ?? quote?.last_trade ?? quote?.mark_price ?? latest?.close
  const quoteLatency = quote?.latency_ms != null ? `${quote.latency_ms} ms` : '--'
  const change = displayPrice && previous ? displayPrice - previous.close : 0
  const changePct = latest && previous ? (change / previous.close) * 100 : 0
  const connected = connectionStatus === 'open'
  const finalAction = aiIct?.grade === 'NO_TRADE' || aiIct?.direction === 'neutral'
    ? 'WAIT'
    : aiIct?.direction === 'bullish'
      ? 'BUY'
      : aiIct?.direction === 'bearish'
        ? 'SELL'
        : '--'
  const signalSummary = aiIct?.summary ?? 'NEXUS is aligning market structure, liquidity, and option flow into one definitive signal.'
  const finalSideClass = finalAction === 'BUY' ? 'bullish' : finalAction === 'SELL' ? 'bearish' : 'neutral'
  const confidenceText = aiIct ? `${(aiIct.confidence * 100).toFixed(0)}%` : '--'
  const latestLiquidityEvent = liquidityEvents.at(-1)
  const optionContract = aiIct?.option_contract ?? null
  const momentumText = aiIct?.momentum_score != null
    ? `${(aiIct.momentum_score * 100).toFixed(0)}%`
    : '--'
  const displayRiskRewardLabel = aiIct?.risk_reward != null
    ? `BEST (1:${aiIct.risk_reward.toFixed(0)})`
    : 'BEST'
  const optionExecutionStatus = optionContract?.qualified
    ? 'qualified'
    : 'watchlist'
  const [selectedRiskReward] = useState<number | 'best'>(3)

  return (
    <main className="terminal">
      <header className="topbar">
        <div className="identity">
          <BarChart3 size={28} aria-hidden="true" />
          <div>
            <h1>NEXUS</h1>
            <p>{symbol} / {timeframe} · Market intelligence</p>
          </div>
        </div>

        <div className="market-readout">
          <span className="last-price">{formatPrice(displayPrice)}</span>
          <span className={change >= 0 ? 'change positive' : 'change negative'}>
            {change >= 0 ? '+' : ''}{formatPrice(change)} ({changePct.toFixed(2)}%)
          </span>
          <span className="quote-source">{quote?.source ?? 'candle'} / {quoteLatency}</span>
        </div>

        <div className="toolbar">
          <div className="timeframe-control" aria-label="Timeframe">
            {availableTimeframes.map((option) => (
              <button
                key={option}
                type="button"
                className={option === selectedTimeframe ? 'active' : ''}
                onClick={() => setTimeframe(option)}
              >
                {option}
              </button>
            ))}
          </div>
          <div className={`connection-pill ${connected ? 'connected' : 'offline'}`}>
            {connected ? <Wifi size={16} aria-hidden="true" /> : <WifiOff size={16} aria-hidden="true" />}
            <span>{connected ? 'Live' : connectionStatus}</span>
          </div>
          <button type="button" className="icon-button" onClick={reconnect} title="Reconnect market stream">
            <RefreshCw size={17} aria-hidden="true" />
            <span>Reconnect</span>
          </button>
        </div>
      </header>

      <section className="status-strip">
        <Metric icon={<Activity size={17} />} label="Feed" value={feedStatus.replaceAll('_', ' ')} />
        <Metric icon={<Target size={17} />} label="Final signal" value={finalAction} />
        <Metric icon={<Gauge size={17} />} label="Momentum" value={momentumText} />
        <Metric icon={<BrainCircuit size={17} />} label="Option" value={optionContract?.symbol ?? 'WAIT'} />
        <Metric icon={<Gauge size={17} />} label="R:R" value={displayRiskRewardLabel} />
      </section>

      <section className="hero-strip">
        <div className={`hero-card ${finalSideClass}`}>
          <div className="hero-title">
            <div>
              <span>Signal</span>
              <strong>{finalAction}</strong>
            </div>
            <span>{aiIct?.grade ?? '--'} · {aiIct?.readiness ?? '--'}</span>
          </div>
          <p>{signalSummary}</p>
          <div className="hero-meta">
            <span>Confidence: {confidenceText}</span>
            <span>Model: {aiIct?.model ?? aiIct?.provider ?? 'NEXUS'}</span>
            <span>{optionExecutionStatus}</span>
          </div>
        </div>
      </section>

      {feedMessage ? <div className="feed-alert">{feedMessage}</div> : null}

      <section className="workspace">
        <div className="chart-region">
          <Chart targetRiskReward={selectedRiskReward} />
        </div>

        <aside className="side-panel">
          <section>
            <h2>Session</h2>
            <dl className="facts">
              <div>
                <dt>Open</dt>
                <dd>{formatPrice(latest?.open)}</dd>
              </div>
              <div>
                <dt>High</dt>
                <dd>{formatPrice(latest?.high)}</dd>
              </div>
              <div>
                <dt>Low</dt>
                <dd>{formatPrice(latest?.low)}</dd>
              </div>
              <div>
                <dt>Volume</dt>
                <dd>{formatPrice(lastApiCandle?.volume ?? latest?.volume)}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{formatTimestamp(lastApiCandle?.timestamp)}</dd>
              </div>
            </dl>
          </section>

          <section className="signal-math-section">
            <div className="signal-math-header">
              <h2><Gauge size={15} aria-hidden="true" /> Signal Math</h2>
              <span className="math-badge">Balanced</span>
            </div>
            <div className="signal-math-grid">
              <dl className="facts compact model-metrics">
                <div>
                  <dt>ATR14</dt>
                  <dd>{formatPrice(metrics?.atr14)}</dd>
                </div>
                <div>
                  <dt>VWAP</dt>
                  <dd>{formatPrice(metrics?.vwap)}</dd>
                </div>
                <div>
                  <dt>RSI14</dt>
                  <dd>{metrics ? metrics.rsi14.toFixed(1) : '--'}</dd>
                </div>
                <div>
                  <dt>Expected Move</dt>
                  <dd>{formatPrice(metrics?.expected_move)}</dd>
                </div>
                <div>
                  <dt>Bias</dt>
                  <dd>{metrics?.institutional_bias ?? '--'}</dd>
                </div>
                <div>
                  <dt>Liquidity</dt>
                  <dd>{latestLiquidityEvent ? `${(latestLiquidityEvent.engineered_score * 100).toFixed(0)}%` : '--'}</dd>
                </div>
                <div>
                  <dt>Sentiment</dt>
                  <dd>{sentiment?.label ?? '--'} {sentiment ? `${(sentiment.confidence * 100).toFixed(0)}%` : ''}</dd>
                </div>
                <div>
                  <dt>Expected Range</dt>
                  <dd>{formatPrice(projection?.expected_low)} - {formatPrice(projection?.expected_high)}</dd>
                </div>
              </dl>
              <div className="signal-math-notes">
                <p className="risk-note">{regime?.reason ?? ''}</p>
                <p className="risk-note">{sentiment?.summary ?? ''}</p>
              </div>
            </div>
          </section>
        </aside>
      </section>
    </main>
  )
}

interface MetricProps {
  icon: ReactNode
  label: string
  value: string
}

function Metric({ icon, label, value }: MetricProps) {
  return (
    <div className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

export default App
