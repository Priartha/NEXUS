import { useMemo } from 'react'
import { useChartStore } from '../store/chartStore'
import { Brain, TrendingUp, TrendingDown, AlertTriangle, Users, Shield, Gauge, Target, Activity, BarChart3 } from 'lucide-react'

export function PsychologyPanel() {
  const psychology = useChartStore((state) => state.psychology)
  const readability = useChartStore((state) => state.readability)
  const metrics = useChartStore((state) => state.metrics)

  const fgData = useMemo(() => {
    if (!psychology) return null

    const score = psychology.fear_greed_score ?? 0
    const label = psychology.fear_greed_label ?? 'neutral'
    const retail = psychology.retail_participation ?? 0.5
    const smartMoney = psychology.smart_money_activity ?? 0
    const emotional = psychology.emotional_state ?? 'balanced'
    const trapRisk = psychology.trap_risk ?? 0.5
    const conviction = psychology.conviction_score ?? 0.5
    const levels = psychology.psychological_levels ?? []
    const signals = psychology.active_signals ?? []
    const summary = psychology.summary ?? ''

    return {
      score,
      label,
      retail,
      smartMoney,
      emotional,
      trapRisk,
      conviction,
      levels,
      signals,
      summary,
    }
  }, [psychology])

  const readData = useMemo(() => {
    if (!readability) return null

    const overall = readability.overall_score ?? 0.5
    const grade = readability.grade ?? 'C'
    const candleClarity = readability.candle_clarity ?? 0.5
    const noise = readability.noise_level ?? 0.5
    const structureRel = readability.structure_reliability ?? 0.5
    const tradeability = readability.tradeability ?? 'fair'
    const pattern = readability.dominant_pattern ?? 'unknown'
    const observations = readability.key_observations ?? []

    const trendQ = readability.trend_quality
    const rangeQ = readability.range_quality

    return {
      overall,
      grade,
      candleClarity,
      noise,
      structureRel,
      tradeability,
      pattern,
      observations,
      trendQ,
      rangeQ,
    }
  }, [readability])

  if (!fgData && !readData) {
    return (
      <div className="inst-panel">
        <div className="inst-empty">Waiting for psychology & readability data...</div>
      </div>
    )
  }

  const getFGColor = (score: number) => {
    if (score <= -0.6) return '#ef4444'
    if (score <= -0.2) return '#f97316'
    if (score <= 0.2) return '#f59e0b'
    if (score <= 0.6) return '#22c55e'
    return '#10b981'
  }

  const getFGIcon = (label: string) => {
    if (label === 'extreme_fear') return <TrendingDown size={14} />
    if (label === 'extreme_greed') return <TrendingUp size={14} />
    return <Activity size={14} />
  }

  const getEmotionalColor = (state: string) => {
    if (state === 'panic') return '#ef4444'
    if (state === 'euphoric') return '#f97316'
    if (state === 'cautious') return '#f59e0b'
    return '#22c55e'
  }

  const getTradeabilityColor = (t: string) => {
    if (t === 'excellent') return '#22c55e'
    if (t === 'good') return '#10b981'
    if (t === 'fair') return '#f59e0b'
    if (t === 'poor') return '#f97316'
    return '#ef4444'
  }

  const getGradeColor = (g: string) => {
    if (g.startsWith('A')) return '#22c55e'
    if (g.startsWith('B')) return '#10b981'
    if (g.startsWith('C')) return '#f59e0b'
    if (g.startsWith('D')) return '#f97316'
    return '#ef4444'
  }

  return (
    <div className="inst-panel">
      {/* Fear & Greed Gauge */}
      {fgData && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Brain size={14} /> Market Psychology
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Fear/Greed Score</span>
              <span className="inst-value" style={{ color: getFGColor(fgData.score) }}>
                {getFGIcon(fgData.label)} {fgData.score.toFixed(2)}
              </span>
              <span className="inst-badge" style={{ borderColor: getFGColor(fgData.score) }}>
                {fgData.label.replace('_', ' ')}
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Emotional State</span>
              <span className="inst-value" style={{ color: getEmotionalColor(fgData.emotional) }}>
                {fgData.emotional.charAt(0).toUpperCase() + fgData.emotional.slice(1)}
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Conviction Score</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${fgData.conviction * 100}%`, background: fgData.conviction > 0.6 ? '#22c55e' : '#f59e0b' }} />
              </div>
              <span className="inst-value">{(fgData.conviction * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Retail vs Smart Money */}
      {fgData && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Users size={14} /> Market Participants
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Retail Participation</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${fgData.retail * 100}%`, background: fgData.retail > 0.7 ? '#ef4444' : '#f59e0b' }} />
              </div>
              <span className="inst-value">{(fgData.retail * 100).toFixed(1)}%</span>
              <span className="inst-sub">{fgData.retail > 0.7 ? 'High noise' : fgData.retail < 0.3 ? 'Clean moves' : 'Moderate'}</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Smart Money Activity</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${fgData.smartMoney * 100}%`, background: fgData.smartMoney > 0.5 ? '#22c55e' : '#6b7280' }} />
              </div>
              <span className="inst-value">{(fgData.smartMoney * 100).toFixed(1)}%</span>
              <span className="inst-sub">{fgData.smartMoney > 0.5 ? 'Active institutional' : 'Low institutional'}</span>
            </div>
          </div>
        </div>
      )}

      {/* Trap Risk & Psychology Signals */}
      {fgData && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <AlertTriangle size={14} /> Trap Risk & Signals
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Trap Risk</span>
              <span className="inst-value" style={{ color: fgData.trapRisk > 0.7 ? '#ef4444' : '#22c55e' }}>
                {(fgData.trapRisk * 100).toFixed(1)}%
              </span>
              <span className="inst-sub">{fgData.trapRisk > 0.7 ? 'High false breakout risk' : 'Normal'}</span>
            </div>
            {fgData.signals.length > 0 && (
              <div className="inst-metric" style={{ gridColumn: '1 / -1' }}>
                <span className="inst-label">Active Psychology Signals</span>
                {fgData.signals.slice(-5).map((sig: any, idx: number) => (
                  <div key={idx} className="inst-sub" style={{ marginTop: '4px' }}>
                    <span style={{ color: sig.side === 'bullish' ? '#22c55e' : '#ef4444' }}>
                      {sig.side === 'bullish' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                    </span>
                    {' '}{sig.type.replace('_', ' ')}: {sig.description}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Psychological Levels */}
      {fgData && fgData.levels.length > 0 && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Target size={14} /> Psychological Levels
          </h3>
          <div className="inst-grid">
            {fgData.levels.slice(0, 6).map((level: number, idx: number) => {
              const currentPrice = metrics?.vwap ?? 0
              const distance = currentPrice ? ((level - currentPrice) / currentPrice * 100) : 0
              return (
                <div key={idx} className="inst-metric">
                  <span className="inst-label">Level {idx + 1}</span>
                  <span className="inst-value">{level.toFixed(2)}</span>
                  <span className="inst-sub">{distance > 0 ? '+' : ''}{distance.toFixed(2)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Price Action Readability */}
      {readData && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Gauge size={14} /> Price Action Readability
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Readability Grade</span>
              <span className="inst-value" style={{ color: getGradeColor(readData.grade), fontSize: '1.2em' }}>
                {readData.grade}
              </span>
              <span className="inst-sub">Score: {(readData.overall * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Tradeability</span>
              <span className="inst-value" style={{ color: getTradeabilityColor(readData.tradeability) }}>
                {readData.tradeability.charAt(0).toUpperCase() + readData.tradeability.slice(1)}
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Dominant Pattern</span>
              <span className="inst-value">{readData.pattern.replace('_', ' ')}</span>
            </div>
          </div>
        </div>
      )}

      {/* Readability Components */}
      {readData && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <BarChart3 size={14} /> Readability Components
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Candle Clarity</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${readData.candleClarity * 100}%`, background: readData.candleClarity > 0.6 ? '#22c55e' : '#f59e0b' }} />
              </div>
              <span className="inst-value">{(readData.candleClarity * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Noise Level</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${readData.noise * 100}%`, background: readData.noise < 0.3 ? '#22c55e' : readData.noise > 0.7 ? '#ef4444' : '#f59e0b' }} />
              </div>
              <span className="inst-value">{(readData.noise * 100).toFixed(1)}%</span>
              <span className="inst-sub">{readData.noise > 0.7 ? 'High noise' : readData.noise < 0.3 ? 'Clean signals' : 'Moderate'}</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Structure Reliability</span>
              <div className="inst-bar-container">
                <div className="inst-bar" style={{ width: `${readData.structureRel * 100}%`, background: readData.structureRel > 0.6 ? '#22c55e' : '#f59e0b' }} />
              </div>
              <span className="inst-value">{(readData.structureRel * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Trend/Range Quality */}
      {readData && readData.trendQ && readData.pattern === 'trending' && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <TrendingUp size={14} /> Trend Quality
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Smoothness</span>
              <span className="inst-value">{(readData.trendQ.smoothness * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Consistency</span>
              <span className="inst-value">{(readData.trendQ.consistency * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Pullback Quality</span>
              <span className="inst-value">{(readData.trendQ.pullback_quality * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Acceleration</span>
              <span className="inst-value" style={{ color: readData.trendQ.acceleration > 0 ? '#22c55e' : '#ef4444' }}>
                {(readData.trendQ.acceleration * 100).toFixed(1)}%
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Trend Reliability</span>
              <span className="inst-value">{(readData.trendQ.reliability * 100).toFixed(1)}%</span>
            </div>
            {readData.trendQ.is_choppy && (
              <div className="inst-metric">
                <span className="inst-label">Warning</span>
                <span className="inst-value" style={{ color: '#ef4444' }}>Choppy trend</span>
              </div>
            )}
          </div>
        </div>
      )}

      {readData && readData.rangeQ && (readData.pattern === 'ranging' || readData.pattern === 'breaking_out') && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Shield size={14} /> Range Quality
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Boundary Clarity</span>
              <span className="inst-value">{(readData.rangeQ.boundary_clarity * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Bounce Consistency</span>
              <span className="inst-value">{(readData.rangeQ.bounce_consistency * 100).toFixed(1)}%</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Internal Structure</span>
              <span className="inst-value">{(readData.rangeQ.internal_structure * 100).toFixed(1)}%</span>
            </div>
            {readData.rangeQ.is_breaking_out && (
              <>
                <div className="inst-metric">
                  <span className="inst-label">Breakout Quality</span>
                  <span className="inst-value" style={{ color: readData.rangeQ.breakout_quality > 0.6 ? '#22c55e' : '#ef4444' }}>
                    {(readData.rangeQ.breakout_quality * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="inst-metric">
                  <span className="inst-label">Status</span>
                  <span className="inst-value" style={{ color: '#f97316' }}>Breaking Out</span>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Key Observations */}
      {readData && readData.observations.length > 0 && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Brain size={14} /> Key Observations
          </h3>
          <div className="inst-grid">
            <div className="inst-metric" style={{ gridColumn: '1 / -1' }}>
              {readData.observations.map((obs: string, idx: number) => (
                <div key={idx} className="inst-sub" style={{ marginTop: '4px' }}>
                  • {obs}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Summary */}
      {fgData && fgData.summary && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Activity size={14} /> Psychology Summary
          </h3>
          <div className="inst-grid">
            <div className="inst-metric" style={{ gridColumn: '1 / -1' }}>
              <span className="inst-sub">{fgData.summary}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
