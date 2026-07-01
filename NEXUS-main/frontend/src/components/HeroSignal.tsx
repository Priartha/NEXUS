import { memo } from 'react'
import { TrendingUp, TrendingDown, Activity } from 'lucide-react'
import { useChartStore } from '../store/chartStore'

function V4Badge({ label, value, type }: { label: string; value: string; type: 'bullish' | 'bearish' | 'neutral' }) {
  return (
    <span className={`v4-badge ${type}`} title={`${label}: ${value}`}>
      {type === 'bullish' ? <TrendingUp size={10} /> : type === 'bearish' ? <TrendingDown size={10} /> : <Activity size={10} />}
      <span className="v4-badge-label">{label}</span>
      <span className="v4-badge-value">{value}</span>
    </span>
  )
}

export const HeroSignal = memo(function HeroSignal() {
  const scalpContext = useChartStore((s) => s.scalpContext)
  const scalpRisk = useChartStore((s) => s.scalpRisk)
  const aiIct = useChartStore((s) => s.aiIct)

  const primarySignal = scalpContext?.signals?.[0] ?? null
  const blockers = scalpContext?.trade_blocked_reasons ?? []
  const priceRsiText = scalpContext?.rsi_3 != null ? `RSI(3): ${scalpContext.rsi_3.toFixed(1)}` : '--'

  const finalAction = primarySignal
    ? primarySignal.signal_type.includes('LONG') ? 'LONG' : primarySignal.signal_type.includes('SHORT') ? 'SHORT' : 'WAIT'
    : blockers.length > 0 ? 'BLOCKED' : 'WAIT'

  const scalpGrade = primarySignal
    ? primarySignal.confidence === 'HIGH' ? 'A+' : 'B'
    : blockers.length > 0 ? 'C' : '--'
  const scalpReadiness = primarySignal
    ? primarySignal.confidence === 'HIGH' ? 'SNIPER' : 'QUALIFIED'
    : blockers.length > 0 ? 'FILTERED' : '--'

  const signalSummary = primarySignal
    ? primarySignal.reason
    : blockers.length > 0
      ? `Trading blocked: ${blockers.join('; ')}`
      : aiIct?.summary ?? 'NEXUS scalping engine analyzing order flow, VWAP, funding, OI, and liquidity for sniper entry.'

  const finalSideClass = finalAction === 'LONG' ? 'bullish' : finalAction === 'SHORT' ? 'bearish' : 'neutral'
  const scalpSignalStatus = primarySignal
    ? `${primarySignal.signal_type} | RR 1:${primarySignal.risk_reward.toFixed(2)}`
    : '--'
  const scalpRiskStatus = scalpRisk
    ? `Risk ${scalpRisk.total_open}/${scalpRisk.max_positions} | loss ${scalpRisk.daily_loss_pct.toFixed(2)}%/${scalpRisk.max_daily_loss_pct.toFixed(2)}%`
    : 'Risk --'

  // Extract V4 signal quality info from reasons
  const reasons = primarySignal?.reason?.split(' | ') ?? []
  const divergenceBadge = reasons.find((r) => r.includes('divergence') || r.includes('Divergence'))
  const msbBadge = reasons.find((r) => r.includes('BoS') || r.includes('MSS') || r.includes('Structure'))
  const kellyBadge = reasons.find((r) => r.includes('Kelly'))
  const patternBadge = reasons.find((r) => r.includes('pin bar') || r.includes('engulfing') || r.includes('Momentum candle'))
  const fvgBadge = reasons.find((r) => r.includes('FVG') || r.includes('Fvg'))
  const obBadge = reasons.find((r) => r.includes('OB') || r.includes('Order Block'))

  const hasV4Badges = divergenceBadge || msbBadge || kellyBadge || patternBadge || fvgBadge || obBadge

  return (
    <section className="hero-strip">
      <div className={`hero-card ${finalSideClass}`}>
        <div className="hero-title">
          <div className="hero-signal-group">
            <span className="hero-label">SCALP SIGNAL V4</span>
            <strong className="hero-action">{finalAction}</strong>
          </div>
          <div className="hero-grade">
            <span className="hero-grade-value">{scalpGrade}</span>
            <span className="hero-grade-label">{scalpReadiness}</span>
          </div>
        </div>
        <div className="confidence-gauge">
          <div className="cg-track">
            <div className={`cg-fill ${finalSideClass}`} style={{ width: primarySignal ? (primarySignal.confidence === 'HIGH' ? '80' : '65') + '%' : '0%' }} />
          </div>
          <div className="cg-labels">
            <span>Confidence</span>
            <span>{primarySignal ? (primarySignal.confidence === 'HIGH' ? '80%' : '65%') : '--'}</span>
          </div>
        </div>
        {hasV4Badges && (
          <div className="v4-badges">
            {divergenceBadge && <V4Badge label="Div" value={divergenceBadge} type={divergenceBadge.toLowerCase().includes('bullish') ? 'bullish' : 'bearish'} />}
            {msbBadge && <V4Badge label="Structure" value={msbBadge} type={msbBadge.toLowerCase().includes('bullish') ? 'bullish' : 'bearish'} />}
            {patternBadge && <V4Badge label="Pattern" value={patternBadge} type={patternBadge.toLowerCase().includes('bullish') ? 'bullish' : 'bearish'} />}
            {fvgBadge && <V4Badge label="FVG" value={fvgBadge} type="neutral" />}
            {obBadge && <V4Badge label="OB" value={obBadge} type="neutral" />}
            {kellyBadge && <V4Badge label="Kelly" value={kellyBadge.replace('Kelly: ', '').replace(' at risk', '%')} type="neutral" />}
          </div>
        )}
        <p className="hero-summary">{signalSummary}</p>
        <div className="hero-meta">
          <span>Model: UNIFIED-SCALP-V4</span>
          <span>{scalpSignalStatus}</span>
          <span>{scalpRiskStatus}</span>
          {primarySignal && (
            <>
              <span>Entry: ${primarySignal.entry_zone_low.toLocaleString()}–${primarySignal.entry_zone_high.toLocaleString()}</span>
              <span>SL: ${primarySignal.sl_level.toLocaleString()}</span>
              <span>T1: ${primarySignal.target_1.toLocaleString()}</span>
              <span>T2: ${primarySignal.target_2.toLocaleString()}</span>
              {primarySignal.leverage > 0 && <span>Lev: {primarySignal.leverage}x</span>}
              <span>Max: {primarySignal.max_hold_minutes}m</span>
            </>
          )}
          <span>{priceRsiText}</span>
        </div>
      </div>
    </section>
  )
})
