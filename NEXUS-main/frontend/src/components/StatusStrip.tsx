import { memo, type ReactNode } from 'react'
import { Activity, Target, Gauge, BrainCircuit, TrendingUp, TrendingDown, Orbit, Compass, Brain } from 'lucide-react'
import { useChartStore } from '../store/chartStore'

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      <span className="metric-icon">{icon}</span>
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </div>
  )
}

export const StatusStrip = memo(function StatusStrip() {
  const feedStatus = useChartStore((s) => s.feedStatus)
  const btcPatterns = useChartStore((s) => s.btcPatterns)
  const regime = useChartStore((s) => s.regime)
  const psychology = useChartStore((s) => s.psychology)
  const readability = useChartStore((s) => s.readability)
  const scalpContext = useChartStore((s) => s.scalpContext)
  const btcPatternsSafe = btcPatterns ?? null

  const primarySignal = scalpContext?.signals?.[0] ?? null
  const blockers = scalpContext?.trade_blocked_reasons ?? []
  const finalAction = primarySignal
    ? primarySignal.signal_type.includes('LONG') ? 'LONG' : primarySignal.signal_type.includes('SHORT') ? 'SHORT' : 'WAIT'
    : blockers.length > 0 ? 'BLOCKED' : 'WAIT'
  const priceRsiText = scalpContext?.rsi_3 != null ? `RSI(3): ${scalpContext.rsi_3.toFixed(1)}` : '--'
  const scalpSignalStatus = primarySignal
    ? `${primarySignal.signal_type} | RR 1:${primarySignal.risk_reward.toFixed(2)}`
    : '--'
  const patternCount = btcPatternsSafe?.patterns?.length ?? 0
  const patternSignal = btcPatternsSafe?.pattern_signal ?? 'neutral'

  return (
    <section className="status-strip">
      <Metric icon={<Activity size={16} />} label="Feed" value={(feedStatus ?? 'unknown').replaceAll('_', ' ')} />
      <Metric icon={<Target size={16} />} label="Signal" value={finalAction} />
      <Metric icon={<Gauge size={16} />} label="Price RSI" value={priceRsiText} />
      <Metric icon={<BrainCircuit size={16} />} label="Signal" value={scalpSignalStatus} />
      {btcPatternsSafe && (
        <Metric
          icon={patternSignal === 'bullish' ? <TrendingUp size={16} /> : patternSignal === 'bearish' ? <TrendingDown size={16} /> : <Orbit size={16} />}
          label="Patterns"
          value={`${patternCount} detected`}
        />
      )}
      {regime && (
        <Metric icon={<Compass size={16} />} label="Regime" value={regime.phase.replaceAll('_', ' ')} />
      )}
      {psychology && (
        <Metric icon={<Brain size={16} />} label="Psychology" value={psychology.fear_greed_label.replaceAll('_', ' ')} />
      )}
      {readability && (
        <Metric icon={<Gauge size={16} />} label="Readability" value={readability.grade} />
      )}
    </section>
  )
})
