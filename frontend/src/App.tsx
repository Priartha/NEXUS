import { useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  Clock,
  Eye,
  Gauge,
  Orbit,
  RefreshCw,
  Target,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'
import './App.css'
import { Chart } from './components/Chart'
import DepthHeatmap from './components/DepthHeatmap'
import { InstitutionalMetricsPanel } from './components/InstitutionalMetricsPanel'
import { MomentumPanel } from './components/MomentumPanel'
import { RiskAnalyticsPanel } from './components/RiskAnalyticsPanel'
import { BtcHeadlinesCorner } from './components/BtcHeadlinesCorner'

import AlertsPanel from './components/AlertsPanel'
import BacktestPanel from './components/BacktestPanel'
import PaperTradingPanel from './components/PaperTradingPanel'
import { useAudioAlerts } from './hooks/useAudioAlerts'
import { useMarketSocket } from './hooks/useMarketSocket'
import { useChartStore } from './store/chartStore'
import {
  DEMO_PATTERNS,
  formatPrice,
  formatTimestamp,
} from './types/market'

type PanelView = 'signals' | 'patterns' | 'options' | 'depth' | 'volume' | 'alerts' | 'backtest' | 'trades' | 'institutional' | 'risk' | 'momentum'

const SESSION_COLORS: Record<string, string> = {
  asian: '#8ab4f8',
  london: '#f59f43',
  ny: '#1fe3a3',
  ny_close: '#ff5b6b',
}

const REGIME_COLORS: Record<string, string> = {
  accumulation: '#1fe3a3',
  distribution: '#ff5b6b',
  consolidation: '#8ab4f8',
  range_bound: '#f59f43',
  trending: '#ffffff',
}

function App() {
  const { reconnect } = useMarketSocket()
  useAudioAlerts()
  const candles = useChartStore((state) => state.candles)
  const lastApiCandle = useChartStore((state) => state.lastApiCandle)
  const liquidityEvents = useChartStore((state) => state.liquidityEvents)
  const metrics = useChartStore((state) => state.metrics)
  const quote = useChartStore((state) => state.quote)
  const regime = useChartStore((state) => state.regime)
  const projection = useChartStore((state) => state.projection)
  const sentiment = useChartStore((state) => state.sentiment)
  const aiIct = useChartStore((state) => state.aiIct)
  const optionsContext = useChartStore((state) => state.optionsContext)
  const btcPatterns = useChartStore((state) => state.btcPatterns)
  const availableTimeframes = useChartStore((state) => state.availableTimeframes)
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const setTimeframe = useChartStore((state) => state.setTimeframe)
  const symbol = useChartStore((state) => state.symbol)
  const timeframe = useChartStore((state) => state.timeframe)
  const connectionStatus = useChartStore((state) => state.connectionStatus)
  const feedStatus = useChartStore((state) => state.feedStatus)
  const feedMessage = useChartStore((state) => state.feedMessage)
  const stats = useChartStore((state) => state.stats)
  const orderbook = useChartStore((state) => state.orderbook)

  const ctx = btcPatterns ?? DEMO_PATTERNS
  const patterns = ctx.patterns
  const behaviors = ctx.investor_behaviors
  const patternSignal = ctx.pattern_signal
  const isDemo = !btcPatterns

  const latest = candles.at(-1)
  const previous = candles.at(-2)
  const displayPrice = quote?.mid ?? quote?.last_trade ?? quote?.mark_price ?? latest?.close
  const refPrice = previous?.close ?? latest?.open ?? displayPrice
  const change = displayPrice && refPrice ? displayPrice - refPrice : 0
  const changePct = refPrice && Number.isFinite(refPrice) && refPrice !== 0 ? (change / refPrice) * 100 : 0
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
  const optionContract = aiIct?.option_contract ?? null
  const momentumText = aiIct?.momentum_score != null
    ? `${(aiIct.momentum_score * 100).toFixed(0)}%`
    : '--'
  const optionExecutionStatus = optionContract?.qualified
    ? 'qualified'
    : 'watchlist'
  const selectedRiskReward: number | 'best' = 'best'
  const [panelView, setPanelView] = useState<PanelView>('signals')
  const [panelOpen, setPanelOpen] = useState(true)
  const latestLiquidityEvent = liquidityEvents.at(-1)

  const topPatterns = useMemo(
    () => [...patterns].sort((a, b) => b.score - a.score).slice(0, 5),
    [patterns],
  )
  const topBehaviors = useMemo(
    () => [...behaviors].sort((a, b) => b.confidence - a.confidence).slice(0, 4),
    [behaviors],
  )
  const bullishCount = patterns.filter((p) => p.direction === 'bullish').length
  const bearishCount = patterns.filter((p) => p.direction === 'bearish').length
  const avgConfidence = patterns.length
    ? patterns.reduce((s, p) => s + p.confidence, 0) / patterns.length
    : 0
  const bestPattern = patterns.length
    ? patterns.reduce((a, b) => (a.confidence > b.confidence ? a : b))
    : null
  const sessionColor = SESSION_COLORS[ctx.session ?? ''] ?? '#888'
  const regimeColor = REGIME_COLORS[regime?.phase ?? ''] ?? '#888'
  const obImbalances = orderbook?.imbalances ?? []
  const obAccumulations = orderbook?.accumulations ?? []
  const obSpreadDynamics = orderbook?.spread_dynamics ?? []
  const obDepthLevels = orderbook?.depth_levels ?? []

  // ─── Fallback SR from recent candles ────────────────
  const fallbackSR = useMemo(() => {
    const recent = candles.slice(-48)
    if (recent.length < 5) return null
    const high = Math.max(...recent.map((c) => c.high))
    const low = Math.min(...recent.map((c) => c.low))
    const close = recent[recent.length - 1].close
    const pivot = (high + low + close) / 3
    return {
      resistance: +(high - (pivot - low) + pivot).toFixed(1),
      support: +(low - (high - pivot) + pivot).toFixed(1),
      projected_high: +(pivot + (high - low)).toFixed(1),
      projected_low: +(pivot - (high - low)).toFixed(1),
    }
  }, [candles])

  const srResistance = regime?.range_high ?? projection?.expected_high ?? fallbackSR?.resistance
  const srSupport = regime?.range_low ?? projection?.expected_low ?? fallbackSR?.support
  const srProjectedHigh = projection?.expected_high ?? fallbackSR?.projected_high
  const srProjectedLow = projection?.expected_low ?? fallbackSR?.projected_low

  return (
    <main className="terminal">
      {/* ─── TOPBAR ────────────────────────────────── */}
      <header className="topbar">
        <div className="identity">
          <div className="logo-icon">
            <BarChart3 size={22} />
          </div>
          <div>
            <h1>NEXUS</h1>
            <p>{symbol} / {timeframe}</p>
          </div>
        </div>

        <div className="market-readout">
          <span className="last-price">{formatPrice(displayPrice)}</span>
          <span className={`change ${change >= 0 ? 'positive' : 'negative'}`}>
            {change >= 0 ? '+' : ''}{formatPrice(change)} ({changePct.toFixed(2)}%)
          </span>
          {ctx && (
            <span className="session-badge" style={{ borderColor: sessionColor, color: sessionColor }}>
              {ctx.session}
            </span>
          )}
          <span className="quote-source">{quote?.source ?? 'candle'}</span>
        </div>

        <div className="toolbar">
          <div className="timeframe-control">
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
            <span className="status-dot" />
            <span>{connected ? 'Live' : connectionStatus}</span>
          </div>
          <button type="button" className="icon-button" onClick={reconnect} title="Reconnect">
            <RefreshCw size={15} />
          </button>
        </div>
      </header>

      {/* ─── STATUS STRIP ──────────────────────────── */}
      <section className="status-strip">
        <Metric icon={<Activity size={16} />} label="Feed" value={feedStatus.replaceAll('_', ' ')} />
        <Metric icon={<Target size={16} />} label="Signal" value={finalAction} />
        <Metric icon={<Gauge size={16} />} label="Momentum" value={momentumText} />
        <Metric icon={<BrainCircuit size={16} />} label="Option" value={optionContract?.symbol ?? 'WAIT'} />
        {ctx && (
          <Metric
            icon={patternSignal === 'bullish' ? <TrendingUp size={16} /> : patternSignal === 'bearish' ? <TrendingDown size={16} /> : <Orbit size={16} />}
            label="Patterns"
            value={`${patternSignal} (${patterns.length})`}
          />
        )}
        {ctx && (
          <Metric
            icon={<Clock size={16} />}
            label="Phase"
            value={ctx.halving_phase.replaceAll('_', ' ')}
          />
        )}
      </section>

      {/* ─── HERO SIGNAL ───────────────────────────── */}
      <section className="hero-strip">
        <div className={`hero-card ${finalSideClass}`}>
          <div className="hero-title">
            <div className="hero-signal-group">
              <span className="hero-label">PRIMARY SIGNAL</span>
              <strong className="hero-action">{finalAction}</strong>
            </div>
            <div className="hero-grade">
              <span className="hero-grade-value">{aiIct?.grade ?? '--'}</span>
              <span className="hero-grade-label">{aiIct?.readiness ?? '--'}</span>
            </div>
          </div>
          {aiIct && (
            <div className="confidence-gauge">
              <div className="cg-track">
                <div className={`cg-fill ${finalSideClass}`} style={{ width: `${(aiIct.confidence * 100).toFixed(0)}%` }} />
              </div>
              <div className="cg-labels">
                <span>Confidence</span>
                <span>{confidenceText}</span>
              </div>
            </div>
          )}
          <p className="hero-summary">{signalSummary}</p>
          <div className="hero-meta">
            <span>Model: {aiIct?.model ?? aiIct?.provider ?? 'NEXUS'}</span>
            <span>{optionExecutionStatus}</span>
            {aiIct?.momentum_score != null && <span>Momentum: {momentumText}</span>}
          </div>
        </div>
      </section>

      {feedMessage ? <div className="feed-alert">{feedMessage}</div> : null}

      {/* ─── WORKSPACE ─────────────────────────────── */}
      <section className={`workspace ${panelOpen ? '' : 'panel-closed'}`}>
        <div className="chart-region">
          <Chart targetRiskReward={selectedRiskReward} />
          <button
            type="button"
            className="panel-toggle"
            onClick={() => setPanelOpen((v) => !v)}
            title={panelOpen ? 'Close panel' : 'Open panel'}
          >
            {panelOpen ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>

        {panelOpen && (
        <aside className="side-panel">
          <div className="panel-switch">
            {(['signals', 'patterns', 'options', 'depth', 'institutional', 'risk', 'momentum', 'alerts'] as const).map((view) => (
              <button
                key={view}
                className={panelView === view ? 'active' : ''}
                onClick={() => setPanelView(view)}
              >
                {view === 'signals' && 'Signals'}
                {view === 'patterns' && (
                  <>
                    Pats
                    {patterns.length > 0 && <span className="badge-count">{patterns.length}</span>}
                  </>
                )}
                {view === 'options' && (
                  <>
                    Opts
                    {optionContract && <span className="badge-dot" />}
                  </>
                )}
                {view === 'depth' && 'Depth'}
                {view === 'alerts' && 'Alerts'}
                {view === 'institutional' && 'Inst.'}
                {view === 'risk' && 'Risk'}
                {view === 'momentum' && 'Momentum'}
              </button>
            ))}
            <div className="panel-switch-sep" />
            {(['trades', 'backtest'] as const).map((view) => (
              <button
                key={view}
                className={`lab-tab ${panelView === view ? 'active' : ''}`}
                onClick={() => setPanelView(view)}
              >
                {view === 'trades' && 'Paper'}
                {view === 'backtest' && 'BT'}
              </button>
            ))}
          </div>

          {/* ─── SIGNALS TAB ────────────────────────── */}
          {panelView === 'signals' && (
            <div className="panel-content">
              <section>
                <h2>Session</h2>
                <dl className="facts">
                  <div><dt>Open</dt><dd>{formatPrice(latest?.open)}</dd></div>
                  <div><dt>High</dt><dd>{formatPrice(latest?.high)}</dd></div>
                  <div><dt>Low</dt><dd>{formatPrice(latest?.low)}</dd></div>
                  <div><dt>Volume</dt><dd>{formatPrice(lastApiCandle?.volume ?? latest?.volume)}</dd></div>
                  <div><dt>Updated</dt><dd>{formatTimestamp(lastApiCandle?.timestamp)}</dd></div>
                </dl>
              </section>

              <section>
                <h2><Gauge size={13} /> Signal Math</h2>
                <dl className="facts compact">
                  <div><dt>ATR14</dt><dd>{formatPrice(metrics?.atr14)}</dd></div>
                  <div><dt>VWAP</dt><dd>{formatPrice(metrics?.vwap)}</dd></div>
                  <div><dt>RSI14</dt><dd>{metrics ? metrics.rsi14.toFixed(1) : '--'}</dd></div>
                  <div><dt>Expected Move</dt><dd>{formatPrice(metrics?.expected_move)}</dd></div>
                  <div><dt>Bias</dt><dd>{metrics?.institutional_bias ?? '--'}</dd></div>
                  <div><dt>Liquidity</dt><dd>{latestLiquidityEvent ? `${(latestLiquidityEvent.engineered_score * 100).toFixed(0)}%` : '--'}</dd></div>
                  <div><dt>Sentiment</dt><dd>{sentiment?.label ?? '--'} {sentiment ? `${(sentiment.confidence * 100).toFixed(0)}%` : ''}</dd></div>
                  <div><dt>Expected Range</dt><dd>{formatPrice(projection?.expected_low)} - {formatPrice(projection?.expected_high)}</dd></div>
                </dl>
                <div className="signal-notes">
                  {regime?.reason && <p className="note">{regime.reason}</p>}
                  {sentiment?.summary && <p className="note">{sentiment.summary}</p>}
                </div>
              </section>

              {regime && (
                <section>
                  <h2><Activity size={13} /> Regime Detail</h2>
                  <dl className="facts compact">
                    <div><dt>Volume State</dt><dd>{regime.volume_state}</dd></div>
                    <div><dt>Efficiency</dt><dd>{regime.efficiency_ratio.toFixed(2)}</dd></div>
                    <div><dt>ATR Compression</dt><dd>{regime.atr_compression.toFixed(2)}</dd></div>
                    <div><dt>Width %</dt><dd>{(regime.width_pct * 100).toFixed(1)}%</dd></div>
                    <div><dt>Range High</dt><dd>{formatPrice(regime.range_high)}</dd></div>
                    <div><dt>Range Low</dt><dd>{formatPrice(regime.range_low)}</dd></div>
                    <div><dt>Bias</dt><dd>{regime.bias}</dd></div>
                    <div><dt>Confidence</dt><dd>{(regime.confidence * 100).toFixed(0)}%</dd></div>
                  </dl>
                </section>
              )}

              {(srResistance || srSupport) && (
                <section>
                  <h2><Target size={13} /> Support & Resistance</h2>
                  <div className="sr-grid">
                    <div className="sr-item resistance">
                      <span className="sr-label">Resistance</span>
                      <strong className="sr-value">${formatPrice(srResistance)}</strong>
                    </div>
                    <div className="sr-item">
                      <span className="sr-label">Projected High</span>
                      <strong className="sr-value">${formatPrice(srProjectedHigh)}</strong>
                    </div>
                    <div className="sr-item">
                      <span className="sr-label">Projected Low</span>
                      <strong className="sr-value">${formatPrice(srProjectedLow)}</strong>
                    </div>
                    <div className="sr-item support">
                      <span className="sr-label">Support</span>
                      <strong className="sr-value">${formatPrice(srSupport)}</strong>
                    </div>
                  </div>
                </section>
              )}

              {latestLiquidityEvent && (
                <section>
                  <h2><Zap size={13} /> Liquidity Event</h2>
                  <dl className="facts compact">
                    <div><dt>Side</dt><dd>{latestLiquidityEvent.side.replace('_', ' ')}</dd></div>
                    <div><dt>Depth</dt><dd>{formatPrice(latestLiquidityEvent.sweep_depth)}</dd></div>
                    <div><dt>Displacement</dt><dd>{(latestLiquidityEvent.displacement * 100).toFixed(0)}%</dd></div>
                    <div><dt>Engineered</dt><dd>{(latestLiquidityEvent.engineered_score * 100).toFixed(0)}%</dd></div>
                    <div><dt>Reclaimed</dt><dd>{latestLiquidityEvent.reclaimed ? 'Yes' : 'No'}</dd></div>
                    <div><dt>Sweep Price</dt><dd>{formatPrice(latestLiquidityEvent.sweep_price)}</dd></div>
                  </dl>
                  {latestLiquidityEvent.reason && (
                    <p className="note" style={{ marginTop: 6 }}>{latestLiquidityEvent.reason}</p>
                  )}
                </section>
              )}



              {aiIct && aiIct.entry != null && aiIct.stop_loss != null && aiIct.direction !== 'neutral' && (
                <section>
                  <h2><Target size={13} /> Trade Levels</h2>
                  <div className="trade-levels">
                    <div className="tl-entry">
                      <span className="tl-label">Entry</span>
                      <strong className="tl-value">${formatPrice(aiIct.entry)}</strong>
                    </div>
                    <div className="tl-stop">
                      <span className="tl-label">Stop Loss</span>
                      <strong className="tl-value">${formatPrice(aiIct.stop_loss)}</strong>
                    </div>
                    {aiIct.take_profit != null && (
                      <div className="tl-target">
                        <span className="tl-label">TP</span>
                        <strong className="tl-value">${formatPrice(aiIct.take_profit)}</strong>
                      </div>
                    )}
                    <div className="tl-risk">
                      <span className="tl-label">Risk</span>
                      <strong className="tl-value">${formatPrice(Math.abs(aiIct.entry - aiIct.stop_loss))}</strong>
                    </div>
                  </div>
                </section>
              )}
            </div>
          )}

          {/* ─── PATTERNS TAB ───────────────────────── */}
          {panelView === 'patterns' && (
            <div className="panel-content">
              <section>
                <h2><Zap size={13} /> Pattern Context</h2>

                <div className="context-grid">
                  <div className="context-item">
                    <span className="ctx-label">Session</span>
                    <strong className="ctx-value" style={{ color: sessionColor }}>{ctx.session}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Phase</span>
                    <strong className="ctx-value" style={{ color: regimeColor }}>{regime?.phase ?? '--'}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Halving</span>
                    <strong className="ctx-value">{ctx.halving_phase.replaceAll('_', ' ')}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Volatility</span>
                    <strong className="ctx-value">{ctx.volatility_regime}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Signal</span>
                    <strong className={`ctx-value ${patternSignal}`}>{patternSignal}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Scores</span>
                    <strong className="ctx-value">
                      <span className="bullish">+{ctx.bullish_pattern_score.toFixed(3)}</span>
                      {' / '}
                      <span className="bearish">-{ctx.bearish_pattern_score.toFixed(3)}</span>
                    </strong>
                  </div>
                </div>

                {isDemo && (
                  <div className="demo-notice">
                    <Zap size={11} /> No live data — showing example patterns. Connect backend for real analysis.
                  </div>
                )}

                {patterns.length > 0 && (
                  <div className="pattern-summary">
                    <div className="summary-item">
                      <span className="ctx-label">Total</span>
                      <strong>{patterns.length} patterns</strong>
                    </div>
                    <div className="summary-item">
                      <span className="ctx-label">Bias</span>
                      <strong><span className="bullish">▲ {bullishCount}</span> / <span className="bearish">▼ {bearishCount}</span></strong>
                    </div>
                    <div className="summary-item">
                      <span className="ctx-label">Avg Conf</span>
                      <strong>{(avgConfidence * 100).toFixed(0)}%</strong>
                    </div>
                    <div className="summary-item">
                      <span className="ctx-label">Behaviors</span>
                      <strong>{stats?.btc_behaviors ?? behaviors.length}</strong>
                    </div>
                    {bestPattern && (
                      <div className="summary-item wide">
                        <span className="ctx-label">Best</span>
                        <strong>{bestPattern.name.replaceAll('_', ' ')} ({(bestPattern.confidence * 100).toFixed(0)}%)</strong>
                      </div>
                    )}
                  </div>
                )}

                {ctx.fractal_clusters.length > 0 && (
                  <div className="cluster-section">
                    <span className="ctx-label">Fractal Clusters</span>
                    <div className="cluster-pills">
                      {ctx.fractal_clusters.map((c) => (
                        <span key={c} className="pill">{c.replace('near_pivot_', '$')}</span>
                      ))}
                    </div>
                  </div>
                )}

                {topPatterns.length > 0 && (
                  <div className="list-section">
                    <h3><TrendingUp size={11} /> Movement Patterns ({patterns.length})</h3>
                    <div className="card-list">
                      {topPatterns.map((p) => (
                        <div key={p.id} className={`card ${p.direction}`}>
                          <div className="card-head">
                            <span className={`dir-icon ${p.direction}`}>
                              {p.direction === 'bullish' ? '▲' : '▼'}
                            </span>
                            <span className="card-title">{p.name.replaceAll('_', ' ')}</span>
                            <span className="card-score">{(p.score * 100).toFixed(0)}%</span>
                          </div>
                          <div className="progress-track">
                            <div className={`progress-fill ${p.direction}`} style={{ width: `${p.confidence * 100}%` }} />
                          </div>
                          <p className="card-desc">{p.description}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {topBehaviors.length > 0 && (
                  <div className="list-section">
                    <h3><Eye size={11} /> Investor Behavior ({behaviors.length})</h3>
                    <div className="card-list">
                      {topBehaviors.map((b) => (
                        <div key={b.id} className={`card behavior ${b.side}`}>
                          <div className="card-head">
                            <span className={`dir-icon ${b.side}`}>
                              {b.side === 'bullish' ? '▲' : '▼'}
                            </span>
                            <span className={`card-title ${b.side}`}>{b.behavior_type.replaceAll('_', ' ')}</span>
                            <span className="card-conf">{(b.confidence * 100).toFixed(0)}%</span>
                          </div>
                          <div className="progress-track">
                            <div className={`progress-fill ${b.side}`} style={{ width: `${b.confidence * 100}%` }} />
                          </div>
                          <p className="card-desc">{b.description}</p>
                          {b.price_level != null && (
                            <div className="behavior-price">
                              <span>Level: ${formatPrice(b.price_level)}</span>
                              {b.volume_ratio != null && <span>Vol: {b.volume_ratio.toFixed(1)}×</span>}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {patterns.length === 0 && behaviors.length === 0 && (
                  <p className="empty-state">No active patterns detected. Waiting for sufficient candle data.</p>
                )}
              </section>
            </div>
          )}

          {/* ─── OPTIONS TAB ────────────────────────── */}
          {panelView === 'options' && (
            <div className="panel-content">
              <section>
                <h2>Option Contracts</h2>
                <div className="option-grid">
                  <div className="option-card call">
                    <div className="option-head">
                      <strong>CALL</strong>
                      <span className="option-score">Score: {optionContract?.score != null ? (optionContract.score * 100).toFixed(0) : '--'}%</span>
                    </div>
                    {optionContract ? (
                      <>
                        <div className="option-detail"><span className="od-label">Contract</span><span className="od-value">{optionContract.symbol}</span></div>
                        <div className="option-detail"><span className="od-label">Delta / Gamma</span><span className="od-value">{optionContract.delta?.toFixed(2)} / {optionContract.gamma?.toFixed(6)}</span></div>
                        <div className="option-detail"><span className="od-label">Strike / Spot</span><span className="od-value">${formatPrice(optionContract.strike_price)} / ${formatPrice(optionContract.spot_price)}</span></div>
                        <div className="option-detail"><span className="od-label">Mid / Spread</span><span className="od-value">${formatPrice(optionContract.mid_price)} / {optionContract.spread_pct != null ? (optionContract.spread_pct * 100).toFixed(1) : '--'}%</span></div>
                        <div className="option-detail"><span className="od-label">Volume / OI</span><span className="od-value">{formatPrice(optionContract.volume)} / {formatPrice(optionContract.open_interest)}</span></div>
                      </>
                    ) : (
                      <p className="empty-state">No qualified CALL contract</p>
                    )}
                  </div>

                  <div className="option-card put">
                    <div className="option-head">
                      <strong>PUT</strong>
                      <span className="option-score">Score: {optionsContext?.put_candidate?.score != null ? (optionsContext.put_candidate.score * 100).toFixed(0) : '--'}%</span>
                    </div>
                    {optionsContext?.put_candidate ? (
                      <>
                        <div className="option-detail"><span className="od-label">Contract</span><span className="od-value">{optionsContext.put_candidate.symbol}</span></div>
                        <div className="option-detail"><span className="od-label">Delta / Gamma</span><span className="od-value">{optionsContext.put_candidate.delta?.toFixed(2)} / {optionsContext.put_candidate.gamma?.toFixed(6)}</span></div>
                        <div className="option-detail"><span className="od-label">Strike / Spot</span><span className="od-value">${formatPrice(optionsContext.put_candidate.strike_price)} / ${formatPrice(optionsContext.put_candidate.spot_price)}</span></div>
                        <div className="option-detail"><span className="od-label">Mid / Spread</span><span className="od-value">${formatPrice(optionsContext.put_candidate.mid_price)} / {optionsContext.put_candidate.spread_pct != null ? (optionsContext.put_candidate.spread_pct * 100).toFixed(1) : '--'}%</span></div>
                      </>
                    ) : (
                      <p className="empty-state">No qualified PUT contract</p>
                    )}
                  </div>
                </div>

                {aiIct?.blockers && aiIct.blockers.length > 0 && (
                  <div className="blockers-section">
                    <h3><AlertTriangle size={11} /> Blockers</h3>
                    <div className="chip-list">
                      {aiIct.blockers.map((b, i) => (
                        <span key={i} className="chip blocker">{b}</span>
                      ))}
                    </div>
                  </div>
                )}

                {aiIct?.confirmations && aiIct.confirmations.length > 0 && (
                  <div className="confirmations-section">
                    <h3>Confirmations</h3>
                    <div className="chip-list">
                      {aiIct.confirmations.map((c, i) => (
                        <span key={i} className="chip confirmation">{c}</span>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}

          {/* ─── TRADES (Paper Trading) TAB ──────────── */}
          {panelView === 'trades' && (
            <div className="panel-content">
              <section>
                <PaperTradingPanel />
              </section>
            </div>
          )}

          {/* ─── ALERTS TAB ─────────────────────────── */}
          {panelView === 'alerts' && (
            <div className="panel-content">
              <section>
                <AlertsPanel />
              </section>
            </div>
          )}

          {/* ─── BACKTEST TAB ────────────────────────── */}
          {panelView === 'backtest' && (
            <div className="panel-content">
              <section>
                <BacktestPanel />
              </section>
            </div>
          )}

          {/* ─── DEPTH TAB ──────────────────────────── */}
          {panelView === 'institutional' && (
            <div className="panel-content">
              <InstitutionalMetricsPanel />
            </div>
          )}

          {panelView === 'risk' && (
            <div className="panel-content">
              <RiskAnalyticsPanel />
            </div>
          )}

          {panelView === 'momentum' && (
            <div className="panel-content">
              <MomentumPanel />
            </div>
          )}

          {panelView === 'depth' && (
            <div className="panel-content">
              <section>
                <h2><Activity size={13} /> Orderbook Imbalances</h2>
                {obImbalances.length > 0 ? (
                  <div className="depth-list">
                    {obImbalances.slice(-8).reverse().map((imb) => (
                      <div key={imb.id} className={`depth-row ${imb.side === 'buy' ? 'bullish' : 'bearish'}`}>
                        <div className="depth-head">
                          <span className="depth-side">{imb.side === 'buy' ? 'BUY' : 'SELL'}</span>
                          <span className="depth-price">${formatPrice(imb.price_level)}</span>
                          <span className={`depth-strength ${imb.side}`}>
                            {(imb.strength * 100).toFixed(0)}%
                          </span>
                        </div>
                        <div className="progress-track">
                          <div className={`progress-fill ${imb.side === 'buy' ? 'bullish' : 'bearish'}`} style={{ width: `${Math.min(100, imb.imbalance_ratio * 100)}%` }} />
                        </div>
                        <div className="depth-meta">
                          <span>Ratio: {imb.imbalance_ratio.toFixed(2)}</span>
                          <span>Dur: {(imb.duration_ms / 1000).toFixed(0)}s</span>
                          <span>Status: {imb.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="empty-state">Waiting for orderbook data...</p>
                )}
              </section>

              {obAccumulations.length > 0 && (
                <section>
                  <h2><Target size={13} /> Accumulation / Distribution</h2>
                  <div className="depth-list">
                    {obAccumulations.slice(-5).reverse().map((acc) => (
                      <div key={acc.id} className={`depth-row ${acc.side === 'accumulation' ? 'bullish' : 'bearish'}`}>
                        <div className="depth-head">
                          <span className="depth-side">{acc.side === 'accumulation' ? 'ACCUMULATION' : 'DISTRIBUTION'}</span>
                          <span className="depth-conf">{(acc.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <div className="progress-track">
                          <div className={`progress-fill ${acc.side === 'accumulation' ? 'bullish' : 'bearish'}`} style={{ width: `${acc.confidence * 100}%` }} />
                        </div>
                        <div className="depth-meta">
                          <span>Range: ${formatPrice(acc.price_range_low)} - ${formatPrice(acc.price_range_high)}</span>
                          <span>Vol Ratio: {acc.volume_ratio.toFixed(1)}×</span>
                          <span>Status: {acc.status}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {obSpreadDynamics.length > 0 && (
                <section>
                  <h2>Spread Dynamics</h2>
                  <dl className="facts compact">
                    {obSpreadDynamics.slice(-4).reverse().map((sd) => (
                      <div key={sd.id}>
                        <dt>{sd.anomaly_type ?? sd.status}</dt>
                        <dd>{sd.spread_pct != null ? `${(sd.spread_pct * 100).toFixed(2)}%` : `${formatPrice(sd.spread)}`}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}

              {obDepthLevels.length > 0 && (
                <section>
                  <h2>Depth Heatmap</h2>
                  <DepthHeatmap depthLevels={obDepthLevels} />
                </section>
              )}

              {stats && (
                <section>
                  <h2>Stats</h2>
                  <dl className="facts compact">
                    <div><dt>Imbalances</dt><dd>{stats.ob_imbalances ?? 0}</dd></div>
                    <div><dt>Spread Anomalies</dt><dd>{stats.ob_spread_anomalies ?? 0}</dd></div>
                    <div><dt>Accumulations</dt><dd>{stats.ob_accumulations ?? 0}</dd></div>
                  </dl>
                </section>
              )}
            </div>
          )}
        </aside>
        )}
      </section>

      {/* ─── BTC LIVE HEADLINES ────────────────────── */}
      <BtcHeadlinesCorner />
    </main>
  )
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

export default App
