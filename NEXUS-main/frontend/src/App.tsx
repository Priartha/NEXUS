import { Component, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  AlertTriangle,
  Brain,
  BrainCircuit,
  Compass,
  Gauge,
  Orbit,
  RefreshCw,
  Settings,
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
import { AnalyticsPanel } from './components/AnalyticsPanel'
import { StrategyConfigPanel } from './components/StrategyConfigPanel'
import { ForwardTestPanel } from './components/ForwardTestPanel'
import { BtcHeadlinesCorner } from './components/BtcHeadlinesCorner'
import { MultiExchangePanel } from './components/MultiExchangePanel'
import { ModelDashboard } from './components/ModelDashboard'
import { DbStatusPanel } from './components/DbStatusPanel'
import { AlertConfigPanel } from './components/AlertConfigPanel'
import { PsychologyPanel } from './components/PsychologyPanel'
import { ScalpingPanel } from './components/ScalpingPanel'
import { VolumeAnalysisPanel } from './components/VolumeAnalysisPanel'
import SignalLogPanel from './components/SignalLogPanel'
import { AIBrainPanel } from './components/AIBrainPanel'
import { AiLabPanel } from './components/AiLabPanel'
import { PatternsPanel } from './components/PatternsPanel'
import { SESSION_COLORS } from './components/panelConstants'

import AlertsPanel from './components/AlertsPanel'
import BacktestPanel from './components/BacktestPanel'
import PaperTradingPanel from './components/PaperTradingPanel'
import { PositionManagerPanel } from './components/PositionManagerPanel'
import { HMMRegimePanel } from './components/HMMRegimePanel'
import { OnChainPanel } from './components/OnChainPanel'
import { NLPSentimentPanel } from './components/NLPSentimentPanel'
import { NewsDrivenTradePlanPanel } from './components/NewsDrivenTradePlanPanel'
import { TransformerForecastPanel } from './components/TransformerForecastPanel'
import { MLDashboardPanel } from './components/MLDashboardPanel'
import { PanelNav } from './components/PanelNav'
import { useAudioAlerts } from './hooks/useAudioAlerts'
import { useMarketSocket } from './hooks/useMarketSocket'
import { useChartStore } from './store/chartStore'
import { useShallow } from 'zustand/react/shallow'
import {
  DEMO_PATTERNS,
  formatPrice,
  formatTimestamp,
} from './types/market'

export type PanelView = 'signals' | 'patterns' | 'depth' | 'alerts' | 'backtest' | 'trades' | 'institutional' | 'risk' | 'momentum' | 'volume' | 'psychology' | 'analytics' | 'config' | 'forward' | 'multi-exchange' | 'model' | 'db-status' | 'alert-config' | 'scalp' | 'log' | 'brain' | 'ai-lab' | 'position' | 'hmm' | 'onchain' | 'nlp' | 'news' | 'forecast' | 'ml-dash'
type RuntimeGuardProps = {
  children: ReactNode
}

type RuntimeGuardState = {
  hasError: boolean
  error: Error | null
}

class RuntimeGuard extends Component<RuntimeGuardProps, RuntimeGuardState> {
  state: RuntimeGuardState = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error) {
    console.error('NEXUS UI runtime error', error)
  }

  render() {
    if (this.state.hasError) {
      const err = this.state.error as Error | null
      return (
        <main className="terminal">
          <section className="hero-strip">
            <div className="hero-card neutral">
              <div className="hero-title">
                <div className="hero-signal-group">
                  <span className="hero-label">RUNTIME FAULT</span>
                  <strong className="hero-action">RELOAD PAGE</strong>
                </div>
              </div>
              <p className="hero-summary" style={{fontFamily:'monospace',fontSize:11,color:'var(--accent-red)'}}>
                {err?.message ?? 'Unknown error'}
              </p>
              <p style={{fontSize:9,color:'var(--text-muted)',marginTop:4}}>
                {err?.stack?.split('\n').slice(0,3).join(' | ')}
              </p>
            </div>
          </section>
        </main>
      )
    }
    return this.props.children
  }
}

type PanelGuardProps = {
  children: ReactNode
  panelView: PanelView
}

class PanelGuard extends Component<PanelGuardProps, RuntimeGuardState> {
  state: RuntimeGuardState = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error: Error) {
    console.error(`NEXUS panel runtime error in ${this.props.panelView}`, error)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="panel-content">
          <section>
            <h2><AlertTriangle size={13} /> Panel Error</h2>
            <p className="empty-state">
              The {this.props.panelView} panel failed to render. Switch to another panel and back after the next data refresh.
            </p>
          </section>
        </div>
      )
    }
    return this.props.children
  }
}

function AppShell() {
  const { reconnect } = useMarketSocket()
  useAudioAlerts()
  const {
    candles, lastApiCandle, liquidityEvents, metrics, quote, regime,
    projection, sentiment, aiIct, psychology, readability, btcPatterns,
    availableTimeframes, selectedTimeframe, setTimeframe, connectionStatus,
    feedStatus, feedMessage, stats, orderbook, scalpContext, scalpRisk,
  } = useChartStore(useShallow((state) => ({
    candles: state.candles,
    lastApiCandle: state.lastApiCandle,
    liquidityEvents: state.liquidityEvents,
    metrics: state.metrics,
    quote: state.quote,
    regime: state.regime,
    projection: state.projection,
    sentiment: state.sentiment,
    aiIct: state.aiIct,
    psychology: state.psychology,
    readability: state.readability,
    btcPatterns: state.btcPatterns,
    availableTimeframes: state.availableTimeframes,
    selectedTimeframe: state.selectedTimeframe,
    setTimeframe: state.setTimeframe,
    connectionStatus: state.connectionStatus,
    feedStatus: state.feedStatus,
    feedMessage: state.feedMessage,
    stats: state.stats,
    orderbook: state.orderbook,
    scalpContext: state.scalpContext,
    scalpRisk: state.scalpRisk,
  })))

  const ctx = btcPatterns ?? DEMO_PATTERNS
  const patterns = ctx?.patterns ?? []
  const patternSignal = ctx?.pattern_signal ?? 'neutral'

  const latest = candles.at(-1)
  const previous = candles.at(-2)
  const displayPrice = quote?.mid ?? quote?.last_trade ?? quote?.mark_price ?? latest?.close
  const refPrice = previous?.close ?? latest?.open ?? displayPrice
  const change = displayPrice && refPrice ? displayPrice - refPrice : 0
  const changePct = refPrice && Number.isFinite(refPrice) && refPrice !== 0 ? (change / refPrice) * 100 : 0
  const connected = connectionStatus === 'open'

  // ─── PRIMARY SIGNAL: Unified Scalping Engine ───────────────────
  const primaryScalpSignal = scalpContext?.signals?.[0] ?? null
  const scalpBlockers = scalpContext?.trade_blocked_reasons ?? []

  const scalpAction = primaryScalpSignal
    ? primaryScalpSignal.signal_type.includes('LONG')
      ? 'LONG'
      : primaryScalpSignal.signal_type.includes('SHORT')
        ? 'SHORT'
        : 'WAIT'
    : scalpBlockers.length > 0
      ? 'BLOCKED'
      : 'WAIT'

  const scalpGrade = primaryScalpSignal
    ? primaryScalpSignal.confidence === 'HIGH' ? 'A+' : 'B'
    : scalpBlockers.length > 0 ? 'C' : '--'

  const scalpReadiness = primaryScalpSignal
    ? primaryScalpSignal.confidence === 'HIGH' ? 'SNIPER' : 'QUALIFIED'
    : scalpBlockers.length > 0 ? 'FILTERED' : '--'

  const finalAction = scalpAction
  const signalSummary = primaryScalpSignal
    ? primaryScalpSignal.reason
    : scalpBlockers.length > 0
      ? `Trading blocked: ${scalpBlockers.join('; ')}`
      : aiIct?.summary ?? 'NEXUS scalping engine analyzing order flow, VWAP, funding, OI, and liquidity for sniper entry.'

  const finalSideClass = finalAction === 'LONG'
    ? 'bullish'
    : finalAction === 'SHORT'
      ? 'bearish'
      : 'neutral'

  const priceRsiText = scalpContext?.rsi_3 != null
    ? `RSI(3): ${scalpContext.rsi_3.toFixed(1)}`
    : '--'
  const scalpSignalStatus = primaryScalpSignal
    ? `${primaryScalpSignal.signal_type} | RR 1:${primaryScalpSignal.risk_reward.toFixed(2)}`
    : '--'
  const scalpRiskStatus = scalpRisk
    ? `Risk ${scalpRisk.total_open}/${scalpRisk.max_positions} | loss ${scalpRisk.daily_loss_pct.toFixed(2)}%/${scalpRisk.max_daily_loss_pct.toFixed(2)}%`
    : 'Risk --'
  const trendBlocked = scalpBlockers.some((r) => r.startsWith('Blocked:') && r.includes('against'))
  const sentimentOverride = sentiment && sentiment.score > 0.3 && sentiment.confidence > 0.3
  const selectedRiskReward: number | 'best' = 'best'
  const [panelView, setPanelView] = useState<PanelView>('signals')
  const latestLiquidityEvent = liquidityEvents.at(-1)

  const sessionColor = SESSION_COLORS[ctx?.session ?? ''] ?? '#888'

  const obImbalances = orderbook?.imbalances ?? []
  const obAccumulations = orderbook?.accumulations ?? []
  const obSpreadDynamics = orderbook?.spread_dynamics ?? []
  const obDepthLevels = orderbook?.depth_levels ?? []

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
            <img src="/logo.svg" alt="NEXUS" className="logo-img" />
          </div>
        </div>

        <div className="market-readout">
          <span className="last-price">{formatPrice(displayPrice)}</span>
          <span className={`change ${change >= 0 ? 'positive' : 'negative'}`}>
            {change >= 0 ? '+' : ''}{formatPrice(change)} ({changePct.toFixed(2)}%)
          </span>
          {ctx && (
            <span className="session-badge" style={{ borderColor: sessionColor, color: sessionColor }}>
              {ctx?.session ?? '--'}
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
        <Metric icon={<Activity size={16} />} label="Feed" value={(feedStatus ?? 'unknown').replaceAll('_', ' ')} />
        <Metric icon={<Target size={16} />} label="Signal" value={finalAction} />
        <Metric icon={<Gauge size={16} />} label="Price RSI" value={priceRsiText} />
        <Metric icon={<BrainCircuit size={16} />} label="Signal" value={scalpSignalStatus} />
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
            value={`${regime.phase.replaceAll('_', ' ')} / ${regime.volume_state}`}
          />
        )}
        {psychology && (
          <Metric
            icon={<Brain size={16} />}
            label="Psychology"
            value={psychology.fear_greed_label.replaceAll('_', ' ')}
          />
        )}
        {readability && (
          <Metric
            icon={<Gauge size={16} />}
            label="Readability"
            value={readability.grade}
          />
        )}
      </section>

      {/* ─── HERO SIGNAL ───────────────────────────── */}
      <section className="hero-strip">
        <div className={`hero-card ${finalSideClass}`}>
          <div className="hero-title">
            <div className="hero-signal-group">
              <span className="hero-label">SCALP SIGNAL</span>
              <strong className="hero-action">{finalAction}</strong>
              {regime && (
                <span className={`hero-volume-badge ${regime.volume_state}`}>
                  VOL {regime.volume_state.toUpperCase()}
                </span>
              )}
              {sentimentOverride && (
                <span className={`hero-sentiment-badge ${sentiment.label === 'bullish' ? 'bullish' : sentiment.label === 'bearish' ? 'bearish' : 'neutral'}`}>
                  SENTIMENT {sentiment.label.toUpperCase()}
                </span>
              )}
              {trendBlocked && (
                <span className="hero-trend-blocked">
                  TREND BLOCKED
                </span>
              )}
            </div>
            <div className="hero-grade">
              <span className="hero-grade-value">{scalpGrade}</span>
              <span className="hero-grade-label">{scalpReadiness}</span>
            </div>
          </div>
          <div className="confidence-gauge">
            <div className="cg-track">
              <div className={`cg-fill ${finalSideClass}`} style={{ width: primaryScalpSignal ? Math.min(100, (primaryScalpSignal.score || 0.5) * 100) + '%' : '0%' }} />
            </div>
            <div className="cg-labels">
              <span>Confidence</span>
              <span>{primaryScalpSignal ? (primaryScalpSignal.confidence === 'HIGH' ? '80%' : '65%') : '--'}</span>
            </div>
          </div>
          <p className="hero-summary">{signalSummary}</p>
          <div className="hero-meta">
            <span>Model: UNIFIED-SCALP-V2</span>
            <span>{scalpSignalStatus}</span>
            <span>{scalpRiskStatus}</span>
            {primaryScalpSignal && (
              <>
                <span>Entry: ${primaryScalpSignal.entry_zone_low.toLocaleString()}–${primaryScalpSignal.entry_zone_high.toLocaleString()}</span>
                <span>SL: ${primaryScalpSignal.sl_level.toLocaleString()}</span>
                <span>T1: ${primaryScalpSignal.target_1.toLocaleString()}</span>
                <span>T2: ${primaryScalpSignal.target_2.toLocaleString()}</span>
                {primaryScalpSignal.leverage > 0 && <span>Lev: {primaryScalpSignal.leverage}x</span>}
                <span>Max: {primaryScalpSignal.max_hold_minutes}m</span>
              </>
            )}
            <span>{priceRsiText}</span>
          </div>
        </div>
      </section>

      {feedMessage ? <div className="feed-alert">{feedMessage}</div> : null}

      {/* ─── WORKSPACE ─────────────────────────────── */}
      <section className="workspace">
        <div className="chart-region">
          <Chart targetRiskReward={selectedRiskReward} />
        </div>

        <aside className="side-panel">
          <PanelNav panelView={panelView} setPanelView={setPanelView} />

          <div className="panel-main">
          <PanelGuard key={panelView} panelView={panelView}>
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
                    <div><dt>Phase</dt><dd>{regime.phase.replaceAll('_', ' ')}</dd></div>
                    <div><dt>Bias</dt><dd className={regime.bias === 'bullish' ? 'bullish' : regime.bias === 'bearish' ? 'bearish' : ''}>{regime.bias} {sentimentOverride ? <span className="bias-source sentiment">(sentiment)</span> : <span className="bias-source technical">(technical)</span>}</dd></div>
                    <div><dt>Confidence</dt><dd>{(regime.confidence * 100).toFixed(0)}%</dd></div>
                    <div><dt>Volume State</dt><dd className={`vol-${regime.volume_state}`}>{regime.volume_state}</dd></div>
                    <div><dt>Efficiency</dt><dd>{regime.efficiency_ratio.toFixed(2)}</dd></div>
                    <div><dt>ATR Compression</dt><dd>{regime.atr_compression.toFixed(2)}</dd></div>
                    <div><dt>Width %</dt><dd>{(regime.width_pct * 100).toFixed(1)}%</dd></div>
                    <div><dt>Range High</dt><dd>{formatPrice(regime.range_high)}</dd></div>
                    <div><dt>Range Low</dt><dd>{formatPrice(regime.range_low)}</dd></div>
                    {primaryScalpSignal && (
                      <div><dt>Trend Aligned</dt><dd className={(primaryScalpSignal.signal_type.includes('LONG') && regime.bias === 'bullish') || (primaryScalpSignal.signal_type.includes('SHORT') && regime.bias === 'bearish') ? 'bullish' : 'trend-blocked'}>{(primaryScalpSignal.signal_type.includes('LONG') && regime.bias === 'bullish') || (primaryScalpSignal.signal_type.includes('SHORT') && regime.bias === 'bearish') ? 'YES' : 'BLOCKED'}</dd></div>
                    )}
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

              <section>
                <h2><Settings size={13} /> Active Strategy</h2>
                <dl className="facts compact">
                  <div><dt>Stop Loss</dt><dd>0.5× ATR</dd></div>
                  <div><dt>Breakeven</dt><dd>@ 0.5R</dd></div>
                  <div><dt>TP1 / TP2</dt><dd>{(() => { if (!regime) return '1.0R / 1.5R'; if (regime.phase === 'range_bound') return '0.5R / 1.0R'; if (regime.phase === 'consolidation') return '0.3R / 0.6R'; if (regime.phase === 'trending') return '1.0R / 2.0R'; return '0.7R / 1.4R'; })()}</dd></div>
                  <div><dt>Regime Context</dt><dd>{regime ? `TP tightened for ${regime.phase.replaceAll('_', ' ')}` : '--'}</dd></div>
                  <div><dt>Trend Alignment</dt><dd>{regime && regime.bias !== 'neutral' ? `Longs only in ${regime.bias === 'bullish' ? 'bullish' : 'bearish'} bias` : 'No active bias'}</dd></div>
                  <div><dt>Max Hold</dt><dd>12 bars (1h)</dd></div>
                  <div><dt>ADX Filter</dt><dd>Yes (&gt;20)</dd></div>
                  <div><dt>Limit Orders</dt><dd>Yes</dd></div>
                  <div><dt>Min Confidence</dt><dd>55%</dd></div>
                  <div><dt>Cooldown</dt><dd>12 candles</dd></div>
                </dl>
              </section>
            </div>
          )}

          {/* ─── PATTERNS TAB ─ */}
          {panelView === 'patterns' && <PatternsPanel />}

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

          {panelView === 'volume' && (
            <div className="panel-content">
              <VolumeAnalysisPanel />
            </div>
          )}

          {panelView === 'scalp' && (
            <div className="panel-content">
              <ScalpingPanel />
            </div>
          )}

          {panelView === 'brain' && (
            <div className="panel-content">
              <AIBrainPanel 
                aiIntelligence={scalpContext?.ai_intelligence}
              />
            </div>
          )}

          {panelView === 'ai-lab' && (
            <div className="panel-content">
              <AiLabPanel />
            </div>
          )}

          {panelView === 'psychology' && (
            <div className="panel-content">
              <PsychologyPanel />
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

          {panelView === 'analytics' && (
            <div className="panel-content analytics-panel-content">
              <AnalyticsPanel />
            </div>
          )}

          {panelView === 'forward' && (
            <div className="panel-content forward-test-panel-content">
              <ForwardTestPanel />
            </div>
          )}

          {panelView === 'config' && (
            <div className="panel-content strategy-config-panel-content">
              <StrategyConfigPanel />
            </div>
          )}

          {panelView === 'multi-exchange' && (
            <div className="panel-content">
              <MultiExchangePanel />
            </div>
          )}

          {panelView === 'model' && (
            <div className="panel-content">
              <ModelDashboard />
            </div>
          )}

          {panelView === 'db-status' && (
            <div className="panel-content">
              <DbStatusPanel />
            </div>
          )}

          {panelView === 'alert-config' && (
            <div className="panel-content">
              <AlertConfigPanel />
            </div>
          )}
          {panelView === 'log' && (
            <div className="panel-content">
              <SignalLogPanel />
            </div>
          )}

          {panelView === 'position' && (
            <div className="panel-content">
              <PositionManagerPanel />
            </div>
          )}

          {panelView === 'ml-dash' && (
            <div className="panel-content">
              <MLDashboardPanel />
            </div>
          )}

          {panelView === 'hmm' && (
            <div className="panel-content">
              <HMMRegimePanel />
            </div>
          )}

          {panelView === 'nlp' && (
            <div className="panel-content">
              <NLPSentimentPanel />
            </div>
          )}

          {panelView === 'news' && (
            <div className="panel-content">
              <NewsDrivenTradePlanPanel />
            </div>
          )}

          {panelView === 'forecast' && (
            <div className="panel-content">
              <TransformerForecastPanel />
            </div>
          )}

          {panelView === 'onchain' && (
            <div className="panel-content">
              <OnChainPanel />
            </div>
          )}

          </PanelGuard>
          </div>
        </aside>
      </section>

      {/* ─── BTC LIVE HEADLINES ────────────────────── */}
      <BtcHeadlinesCorner />
    </main>
  )
}

function App() {
  return (
    <RuntimeGuard>
      <AppShell />
    </RuntimeGuard>
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
