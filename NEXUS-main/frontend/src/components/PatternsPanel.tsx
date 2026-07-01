import { memo, useMemo, useState } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  BarChart2,
  Cpu,
  Eye,
  Flame,
  GitBranch,
  Layers,
  Minus,
  Orbit,
  Radar,
  Shield,
  Target,
  Timer,
  TrendingDown,
  TrendingUp,
  Waves,
  Zap,
} from 'lucide-react'
import { useChartStore } from '../store/chartStore'
import {
  DEMO_PATTERNS,
  formatPrice,
} from '../types/market'
import { REGIME_COLORS, SESSION_COLORS } from './panelConstants'

type PatternFilter = 'all' | 'bullish' | 'bearish' | 'neutral'
type PatternView = 'cards' | 'grid'

const MAX_RENDERED_PATTERNS = 50

export const PatternsPanel = memo(function PatternsPanel() {
  const btcPatterns = useChartStore((state) => state.btcPatterns)
  const fvgs = useChartStore((state) => state.fvgs)
  const orderBlocks = useChartStore((state) => state.orderBlocks)
  const liquidity = useChartStore((state) => state.liquidity)
  const regime = useChartStore((state) => state.regime)

  const behaviors = useMemo(() => btcPatterns?.investor_behaviors ?? [], [btcPatterns])
  const ctx = btcPatterns ?? DEMO_PATTERNS
  const patterns = ctx?.patterns ?? []
  const patternSignal = ctx?.pattern_signal ?? 'neutral'
  const isDemo = !btcPatterns
  const activeFvgs = useMemo(() => fvgs.filter((f) => !f.is_filled), [fvgs])
  const activeOBs = useMemo(() => orderBlocks.filter((ob) => !ob.is_breaker), [orderBlocks])
  const activeLiquidity = useMemo(() => liquidity.filter((l) => !l.swept), [liquidity])

  const [patternFilter, setPatternFilter] = useState<PatternFilter>('all')
  const [patternView, setPatternView] = useState<PatternView>('cards')

  const stats = useMemo(() => {
    let bullish = 0
    let bearish = 0
    let neutral = 0
    let confSum = 0
    let scoreSum = 0
    for (const p of patterns) {
      if (p.direction === 'bullish') bullish++
      else if (p.direction === 'bearish') bearish++
      else neutral++
      confSum += p.confidence
      scoreSum += p.score
    }
    const n = patterns.length
    return {
      bullishCount: bullish,
      bearishCount: bearish,
      neutralCount: neutral,
      avgConfidence: n ? confSum / n : 0,
      avgScore: n ? scoreSum / n : 0,
    }
  }, [patterns])

  const filteredPatterns = useMemo(() => {
    const sorted = [...patterns].sort((a, b) => b.score - a.score)
    const filtered = patternFilter === 'all' ? sorted : sorted.filter((p) => p.direction === patternFilter)
    return filtered.slice(0, MAX_RENDERED_PATTERNS)
  }, [patterns, patternFilter])

  const topBehaviors = useMemo(
    () => [...behaviors].sort((a, b) => b.confidence - a.confidence).slice(0, 4),
    [behaviors],
  )

  const patternBias = useMemo(() => {
    if (stats.bullishCount === 0 && stats.bearishCount === 0) return 'neutral'
    const total = stats.bullishCount + stats.bearishCount
    const bullRatio = stats.bullishCount / total
    if (bullRatio > 0.65) return 'bullish'
    if (bullRatio < 0.35) return 'bearish'
    return 'neutral'
  }, [stats.bullishCount, stats.bearishCount])

  const sessionColor = SESSION_COLORS[ctx?.session ?? ''] ?? '#888'
  const regimeColor = REGIME_COLORS[regime?.phase ?? ''] ?? '#888'

  return (
    <div className="panel-content">
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

        <div className="pattern-bias-meter">
          <div className="bias-label">
            <span>Pattern Bias</span>
            <span className={`bias-badge ${patternBias}`}>
              {patternBias === 'bullish' ? <ArrowUpRight size={12} /> : patternBias === 'bearish' ? <ArrowDownRight size={12} /> : <Minus size={12} />}
              {patternBias.toUpperCase()}
            </span>
          </div>
          <div className="bias-bar">
            <div className="bias-fill-bullish" style={{ width: `${patterns.length > 0 ? (stats.bullishCount / patterns.length) * 100 : 33}%` }} />
            <div className="bias-fill-neutral" style={{ width: `${patterns.length > 0 ? (stats.neutralCount / patterns.length) * 100 : 34}%` }} />
            <div className="bias-fill-bearish" style={{ width: `${patterns.length > 0 ? (stats.bearishCount / patterns.length) * 100 : 33}%` }} />
          </div>
          <div className="bias-legend">
            <span className="legend-item"><span className="legend-dot bullish" /> Bullish ({stats.bullishCount})</span>
            <span className="legend-item"><span className="legend-dot neutral" /> Neutral ({stats.neutralCount})</span>
            <span className="legend-item"><span className="legend-dot bearish" /> Bearish ({stats.bearishCount})</span>
          </div>
        </div>

        <div className="pattern-scores-row">
          <div className="score-chip bullish">
            <span className="score-chip-label">Bull Score</span>
            <span className="score-chip-value">{(ctx?.bullish_pattern_score ?? 0).toFixed(3)}</span>
          </div>
          <div className="score-chip bearish">
            <span className="score-chip-label">Bear Score</span>
            <span className="score-chip-value">{(ctx?.bearish_pattern_score ?? 0).toFixed(3)}</span>
          </div>
          <div className="score-chip">
            <span className="score-chip-label">Avg Conf</span>
            <span className="score-chip-value">{(stats.avgConfidence * 100).toFixed(0)}%</span>
          </div>
          <div className="score-chip">
            <span className="score-chip-label">Avg Score</span>
            <span className="score-chip-value">{(stats.avgScore * 100).toFixed(0)}%</span>
          </div>
        </div>

        <div className="context-grid">
          <div className="context-item">
            <span className="ctx-label">Session</span>
            <strong className="ctx-value" style={{ color: sessionColor }}>{ctx?.session ?? '--'}</strong>
          </div>
          <div className="context-item">
            <span className="ctx-label">Regime</span>
            <strong className="ctx-value" style={{ color: regimeColor }}>{regime?.phase.replaceAll('_', ' ') ?? '--'}</strong>
          </div>
          <div className="context-item">
            <span className="ctx-label">Volatility</span>
            <strong className="ctx-value">{ctx?.volatility_regime ?? '--'}</strong>
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

      {(activeFvgs.length > 0 || activeOBs.length > 0 || activeLiquidity.length > 0) && (
        <section className="pattern-zones-section">
          <h2><GitBranch size={13} /> ICT Pattern Zones</h2>

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

      {(ctx?.fractal_clusters?.length ?? 0) > 0 && (
        <section>
          <h2><Waves size={13} /> Fractal Clusters</h2>
          <div className="cluster-pills">
            {ctx!.fractal_clusters.map((c) => (
              <span key={c} className="pill fractal-pill">{c.replace('near_pivot_', '$')}</span>
            ))}
          </div>
        </section>
      )}

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
  )
})
