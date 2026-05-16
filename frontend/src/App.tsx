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
  Layers,
  BarChart2,
  Waves,
  Flame,
  Compass,
  Shield,
  Cpu,
  GitBranch,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  Sparkles,
  Radar,
  Timer,
  Percent,
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
  const fvgs = useChartStore((state) => state.fvgs)
  const orderBlocks = useChartStore((state) => state.orderBlocks)
  const liquidity = useChartStore((state) => state.liquidity)
  const swings = useChartStore((state) => state.swings)
  const signals = useChartStore((state) => state.signals)

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
  const neutralCount = patterns.filter((p) => p.direction === 'neutral').length
  const avgConfidence = patterns.length
    ? patterns.reduce((s, p) => s + p.confidence, 0) / patterns.length
    : 0
  const avgScore = patterns.length
    ? patterns.reduce((s, p) => s + p.score, 0) / patterns.length
    : 0
  const bestPattern = patterns.length
    ? patterns.reduce((a, b) => (a.confidence > b.confidence ? a : b))
    : null
  const activeFvgs = fvgs.filter((f) => !f.is_filled)
  const activeOBs = orderBlocks.filter((ob) => ob.status !== 'broken')
  const activeLiquidity = liquidity.filter((l) => !l.swept)
  const sessionColor = SESSION_COLORS[ctx.session ?? ''] ?? '#888'
  const regimeColor = REGIME_COLORS[regime?.phase ?? ''] ?? '#888'
  const obImbalances = orderbook?.imbalances ?? []
  const obAccumulations = orderbook?.accumulations ?? []
  const obSpreadDynamics = orderbook?.spread_dynamics ?? []
  const obDepthLevels = orderbook?.depth_levels ?? []

  const [patternFilter, setPatternFilter] = useState<'all' | 'bullish' | 'bearish' | 'neutral'>('all')
  const [patternView, setPatternView] = useState<'cards' | 'grid'>('cards')

  const filteredPatterns = useMemo(() => {
    const sorted = [...patterns].sort((a, b) => b.score - a.score)
    if (patternFilter === 'all') return sorted
    return sorted.filter((p) => p.direction === patternFilter)
  }, [patterns, patternFilter])

  const patternBias = useMemo(() => {
    if (bullishCount === 0 && bearishCount === 0) return 'neutral'
    const total = bullishCount + bearishCount
    const bullRatio = bullishCount / total
    if (bullRatio > 0.65) return 'bullish'
    if (bullRatio < 0.35) return 'bearish'
    return 'neutral'
  }, [bullishCount, bearishCount])

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
            value={`${patterns.length} detected`}
          />
        )}
        {regime && (
          <Metric
            icon={<Compass size={16} />}
            label="Regime"
            value={regime.phase.replaceAll('_', ' ')}
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
            {(['signals', 'patterns', 'options', 'depth', 'institutional', 'risk', 'momentum', 'alerts', 'trades', 'backtest'] as const).map((view) => (
              <button
                key={view}
                className={panelView === view ? 'active' : ''}
                onClick={() => setPanelView(view)}
              >
                {view === 'signals' && 'Signals'}
                {view === 'patterns' && (
                  <>
                    <Layers size={11} />
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

          {/* ─── PATTERNS TAB - COMPLETELY REDESIGNED ─ */}
          {panelView === 'patterns' && (
            <div className="panel-content">
              {/* Pattern Overview Dashboard */}
              <section className="pattern-overview">
                <div className="pattern-overview-header">
                  <h2><Radar size={14} /> Pattern Intelligence</h2>
                  <div className="pattern-view-toggles">
                    <button
                      className={`pattern-view-btn ${patternView === 'cards' ? 'active' : ''}`}
                      onClick={() => setPatternView('cards')}
                      title="Card view"
                    >
                      <Layers size={12} />
                    </button>
                    <button
                      className={`pattern-view-btn ${patternView === 'grid' ? 'active' : ''}`}
                      onClick={() => setPatternView('grid')}
                      title="Grid view"
                    >
                      <BarChart2 size={12} />
                    </button>
                  </div>
                </div>

                {/* Quick Stats Row */}
                <div className="pattern-quick-stats">
                  <div className="pq-stat">
                    <div className="pq-stat-icon"><Layers size={14} /></div>
                    <div className="pq-stat-info">
                      <span className="pq-stat-value">{patterns.length}</span>
                      <span className="pq-stat-label">Patterns</span>
                    </div>
                  </div>
                  <div className="pq-stat">
                    <div className="pq-stat-icon"><Eye size={14} /></div>
                    <div className="pq-stat-info">
                      <span className="pq-stat-value">{behaviors.length}</span>
                      <span className="pq-stat-label">Behaviors</span>
                    </div>
                  </div>
                  <div className="pq-stat">
                    <div className="pq-stat-icon"><Zap size={14} /></div>
                    <div className="pq-stat-info">
                      <span className="pq-stat-value">{activeFvgs.length}</span>
                      <span className="pq-stat-label">Active FVGs</span>
                    </div>
                  </div>
                  <div className="pq-stat">
                    <div className="pq-stat-icon"><Shield size={14} /></div>
                    <div className="pq-stat-info">
                      <span className="pq-stat-value">{activeOBs.length}</span>
                      <span className="pq-stat-label">Order Blocks</span>
                    </div>
                  </div>
                </div>

                {/* Bias Meter */}
                <div className="pattern-bias-meter">
                  <div className="bias-label">
                    <span>Pattern Bias</span>
                    <span className={`bias-badge ${patternBias}`}>
                      {patternBias === 'bullish' ? <ArrowUpRight size={12} /> : patternBias === 'bearish' ? <ArrowDownRight size={12} /> : <Minus size={12} />}
                      {patternBias.toUpperCase()}
                    </span>
                  </div>
                  <div className="bias-bar">
                    <div className="bias-fill-bullish" style={{ width: `${patterns.length > 0 ? (bullishCount / patterns.length) * 100 : 33}%` }} />
                    <div className="bias-fill-neutral" style={{ width: `${patterns.length > 0 ? (neutralCount / patterns.length) * 100 : 34}%` }} />
                    <div className="bias-fill-bearish" style={{ width: `${patterns.length > 0 ? (bearishCount / patterns.length) * 100 : 33}%` }} />
                  </div>
                  <div className="bias-legend">
                    <span className="legend-item"><span className="legend-dot bullish" /> Bullish ({bullishCount})</span>
                    <span className="legend-item"><span className="legend-dot neutral" /> Neutral ({neutralCount})</span>
                    <span className="legend-item"><span className="legend-dot bearish" /> Bearish ({bearishCount})</span>
                  </div>
                </div>

                {/* Scores Summary */}
                <div className="pattern-scores-row">
                  <div className="score-chip bullish">
                    <span className="score-chip-label">Bull Score</span>
                    <span className="score-chip-value">{ctx.bullish_pattern_score.toFixed(3)}</span>
                  </div>
                  <div className="score-chip bearish">
                    <span className="score-chip-label">Bear Score</span>
                    <span className="score-chip-value">{ctx.bearish_pattern_score.toFixed(3)}</span>
                  </div>
                  <div className="score-chip">
                    <span className="score-chip-label">Avg Conf</span>
                    <span className="score-chip-value">{(avgConfidence * 100).toFixed(0)}%</span>
                  </div>
                  <div className="score-chip">
                    <span className="score-chip-label">Avg Score</span>
                    <span className="score-chip-value">{(avgScore * 100).toFixed(0)}%</span>
                  </div>
                </div>

                {/* Context Grid */}
                <div className="context-grid">
                  <div className="context-item">
                    <span className="ctx-label">Session</span>
                    <strong className="ctx-value" style={{ color: sessionColor }}>{ctx.session}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Regime</span>
                    <strong className="ctx-value" style={{ color: regimeColor }}>{regime?.phase.replaceAll('_', ' ') ?? '--'}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Volatility</span>
                    <strong className="ctx-value">{ctx.volatility_regime}</strong>
                  </div>
                  <div className="context-item">
                    <span className="ctx-label">Signal</span>
                    <strong className={`ctx-value ${patternSignal}`}>{patternSignal}</strong>
                  </div>
                </div>

                {isDemo && (
                  <div className="demo-notice">
                    <Zap size={11} /> No live data — showing example patterns. Connect backend for real analysis.
                  </div>
                )}
              </section>

              {/* ICT Pattern Zones */}
              {(activeFvgs.length > 0 || activeOBs.length > 0 || activeLiquidity.length > 0) && (
                <section className="pattern-zones-section">
                  <h2><GitBranch size={13} /> ICT Pattern Zones</h2>

                  {/* FVG Zone */}
                  {activeFvgs.length > 0 && (
                    <div className="zone-group">
                      <div className="zone-group-header">
                        <span className="zone-group-icon fvg-icon"><Zap size={11} /></span>
                        <span className="zone-group-title">Fair Value Gaps</span>
                        <span className="zone-group-count">{activeFvgs.length}</span>
                      </div>
                      <div className="zone-items">
                        {activeFvgs.slice(-4).reverse().map((fvg) => (
                          <div key={fvg.id} className={`zone-item ${fvg.direction}`}>
                            <div className="zone-item-head">
                              <span className="zone-item-dir">{fvg.direction === 'bullish' ? '▲ Bull FVG' : '▼ Bear FVG'}</span>
                              <span className="zone-item-range">${formatPrice(fvg.bottom)} - ${formatPrice(fvg.top)}</span>
                            </div>
                            <div className="zone-item-bar">
                              <div className={`zone-item-fill ${fvg.direction}`} style={{ width: `${Math.min(100, ((fvg.top - fvg.bottom) / (fvg.top || 1)) * 10000)}%` }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Order Block Zone */}
                  {activeOBs.length > 0 && (
                    <div className="zone-group">
                      <div className="zone-group-header">
                        <span className="zone-group-icon ob-icon"><Shield size={11} /></span>
                        <span className="zone-group-title">Order Blocks</span>
                        <span className="zone-group-count">{activeOBs.length}</span>
                      </div>
                      <div className="zone-items">
                        {activeOBs.slice(-4).reverse().map((ob) => (
                          <div key={ob.id} className={`zone-item ${ob.direction}`}>
                            <div className="zone-item-head">
                              <span className="zone-item-dir">{ob.direction === 'bullish' ? '▲ Bull OB' : '▼ Bear OB'}{ob.is_breaker ? ' [BREAKER]' : ''}</span>
                              <span className="zone-item-range">${formatPrice(ob.bottom)} - ${formatPrice(ob.top)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Liquidity Zone */}
                  {activeLiquidity.length > 0 && (
                    <div className="zone-group">
                      <div className="zone-group-header">
                        <span className="zone-group-icon liq-icon"><Target size={11} /></span>
                        <span className="zone-group-title">Liquidity Levels</span>
                        <span className="zone-group-count">{activeLiquidity.length}</span>
                      </div>
                      <div className="zone-items">
                        {activeLiquidity.slice(-4).reverse().map((liq) => (
                          <div key={liq.id} className={`zone-item ${liq.kind === 'equal_high' ? 'bearish' : 'bullish'}`}>
                            <div className="zone-item-head">
                              <span className="zone-item-dir">{liq.kind === 'equal_high' ? '▼ EQH' : '▲ EQL'}</span>
                              <span className="zone-item-range">${formatPrice(liq.price)} ({liq.touch_count} touches)</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>
              )}

              {/* Fractal Clusters */}
              {ctx.fractal_clusters.length > 0 && (
                <section>
                  <h2><Waves size={13} /> Fractal Clusters</h2>
                  <div className="cluster-pills">
                    {ctx.fractal_clusters.map((c) => (
                      <span key={c} className="pill fractal-pill">{c.replace('near_pivot_', '$')}</span>
                    ))}
                  </div>
                </section>
              )}

              {/* Movement Patterns */}
              {filteredPatterns.length > 0 && (
                <section>
                  <div className="section-header-with-filter">
                    <h2><Flame size={13} /> Movement Patterns</h2>
                    <div className="pattern-filter-btns">
                      {(['all', 'bullish', 'bearish', 'neutral'] as const).map((f) => (
                        <button
                          key={f}
                          className={`filter-btn ${patternFilter === f ? 'active' : ''} ${f}`}
                          onClick={() => setPatternFilter(f)}
                        >
                          {f === 'all' ? 'All' : f === 'bullish' ? '▲ Bull' : f === 'bearish' ? '▼ Bear' : '— Neutral'}
                        </button>
                      ))}
                    </div>
                  </div>

                  {patternView === 'cards' ? (
                    <div className="card-list pattern-card-list">
                      {filteredPatterns.map((p) => (
                        <div key={p.id} className={`pattern-card ${p.direction} ${p.completed ? 'completed' : ''}`}>
                          <div className="pattern-card-header">
                            <div className="pattern-card-icon">
                              {p.direction === 'bullish' ? <TrendingUp size={14} /> : p.direction === 'bearish' ? <TrendingDown size={14} /> : <Orbit size={14} />}
                            </div>
                            <div className="pattern-card-info">
                              <span className="pattern-card-name">{p.name.replaceAll('_', ' ')}</span>
                              <span className="pattern-card-meta">
                                <span className={`pattern-card-dir ${p.direction}`}>{p.direction}</span>
                                {p.completed && <span className="pattern-card-completed">completed</span>}
                              </span>
                            </div>
                            <div className="pattern-card-scores">
                              <div className="pattern-score-badge">
                                <span className="psb-label">Score</span>
                                <span className="psb-value">{(p.score * 100).toFixed(0)}%</span>
                              </div>
                            </div>
                          </div>
                          <div className="pattern-card-progress">
                            <div className="pattern-progress-track">
                              <div className={`pattern-progress-fill ${p.direction}`} style={{ width: `${p.confidence * 100}%` }} />
                            </div>
                            <span className="pattern-conf-label">{(p.confidence * 100).toFixed(0)}% confidence</span>
                          </div>
                          <p className="pattern-card-desc">{p.description}</p>
                          {p.candle_count > 0 && (
                            <div className="pattern-card-footer">
                              <span><Timer size={10} /> {p.candle_count} candles</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="pattern-grid-view">
                      {filteredPatterns.map((p) => (
                        <div key={p.id} className={`pattern-grid-card ${p.direction}`}>
                          <div className="pgc-icon">
                            {p.direction === 'bullish' ? <TrendingUp size={16} /> : p.direction === 'bearish' ? <TrendingDown size={16} /> : <Orbit size={16} />}
                          </div>
                          <div className="pgc-name">{p.name.replaceAll('_', ' ')}</div>
                          <div className="pgc-score">{(p.score * 100).toFixed(0)}%</div>
                          <div className="pgc-conf">{(p.confidence * 100).toFixed(0)}%</div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              )}

              {/* Investor Behaviors */}
              {topBehaviors.length > 0 && (
                <section>
                  <h2><Cpu size={13} /> Investor Behavior</h2>
                  <div className="card-list">
                    {topBehaviors.map((b) => (
                      <div key={b.id} className={`behavior-card ${b.side} ${b.is_active ? 'active' : ''}`}>
                        <div className="behavior-card-header">
                          <div className="behavior-card-icon">
                            {b.side === 'bullish' ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                          </div>
                          <div className="behavior-card-info">
                            <span className="behavior-card-type">{b.behavior_type.replaceAll('_', ' ')}</span>
                            <span className="behavior-card-meta">
                              <span className={`behavior-side-badge ${b.side}`}>{b.side}</span>
                              {b.is_active && <span className="behavior-active-badge">active</span>}
                            </span>
                          </div>
                          <div className="behavior-card-confidence">
                            <div className="behavior-conf-ring" style={{ '--conf': b.confidence } as React.CSSProperties}>
                              <span>{(b.confidence * 100).toFixed(0)}%</span>
                            </div>
                          </div>
                        </div>
                        <div className="behavior-card-progress">
                          <div className="behavior-progress-track">
                            <div className={`behavior-progress-fill ${b.side}`} style={{ width: `${b.confidence * 100}%` }} />
                          </div>
                          <span className="behavior-intensity-label">Intensity: {(b.intensity * 100).toFixed(0)}%</span>
                        </div>
                        <p className="behavior-card-desc">{b.description}</p>
                        {b.price_level != null && (
                          <div className="behavior-card-footer">
                            <span><Target size={10} /> ${formatPrice(b.price_level)}</span>
                            {b.volume_ratio != null && <span><BarChart2 size={10} /> {b.volume_ratio.toFixed(1)}× vol</span>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {patterns.length === 0 && behaviors.length === 0 && (
                <section>
                  <p className="empty-state">No active patterns detected. Waiting for sufficient candle data.</p>
                </section>
              )}
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
          <div className={`panel-content ${panelView === 'trades' ? '' : 'panel-hidden'}`}>
            <section>
              <PaperTradingPanel />
            </section>
          </div>

          {/* ─── ALERTS TAB ─────────────────────────── */}
          {panelView === 'alerts' && (
            <div className="panel-content">
              <section>
                <AlertsPanel />
              </section>
            </div>
          )}

          {/* ─── BACKTEST TAB ────────────────────────── */}
          <div className={`panel-content ${panelView === 'backtest' ? '' : 'panel-hidden'}`}>
            <section>
              <BacktestPanel />
            </section>
          </div>

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
