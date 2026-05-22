import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, TrendingUp, TrendingDown, Target, Crosshair, Zap, Shield } from 'lucide-react'

interface SignalLogEntry {
  id: string
  timestamp: number
  symbol: string
  timeframe: string
  side: string
  entry: number
  stop_loss: number
  exit_price: number | null
  risk_reward: number
  confidence: string
  reason: string
  status: string
  exit_timestamp: number | null
}

export default function SignalLogPanel() {
  const [signals, setSignals] = useState<SignalLogEntry[]>([])
  const [loading, setLoading] = useState(true)

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch('/signals/journal?limit=200')
      setSignals(await res.json())
    } catch { } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchSignals()
    const interval = setInterval(fetchSignals, 15000)
    return () => clearInterval(interval)
  }, [fetchSignals])

  const stats = useMemo(() => {
    const total = signals.length
    const longs = signals.filter(s => s.side?.toLowerCase().includes('long')).length
    const shorts = signals.filter(s => s.side?.toLowerCase().includes('short')).length
    const highConf = signals.filter(s => s.confidence === 'HIGH').length
    const medConf = signals.filter(s => s.confidence === 'MEDIUM').length
    const lowConf = signals.filter(s => s.confidence === 'LOW').length
    const open = signals.filter(s => s.status === 'open').length
    const closed = signals.filter(s => s.status === 'closed' || s.status === 'filled').length
    const avgRR = signals.length > 0 ? signals.reduce((s, sig) => s + sig.risk_reward, 0) / signals.length : 0
    return { total, longs, shorts, highConf, medConf, lowConf, open, closed, avgRR }
  }, [signals])

  const getSideColor = (side: string) => {
    if (side?.toLowerCase().includes('long')) return '#22c55e'
    if (side?.toLowerCase().includes('short')) return '#ef4444'
    return '#94a3b8'
  }

  const getConfColor = (conf: string) =>
    conf === 'HIGH' ? '#22c55e' : conf === 'MEDIUM' ? '#f59e0b' : '#94a3b8'

  const getStatusColor = (status: string) =>
    status === 'open' ? '#3b82f6' : status === 'closed' || status === 'filled' ? '#22c55e' : status === 'canceled' ? '#ef4444' : '#94a3b8'

  const formatTime = (ts: number) => {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
  }

  if (loading) {
    return (
      <div className="scalping-panel">
        <div className="scalping-empty">Loading signal log...</div>
      </div>
    )
  }

  return (
    <div className="scalping-panel">
      {/* Summary Stats */}
      <div className="scalping-section">
        <h3 className="scalping-section-title">
          <Activity size={14} /> Signal Summary
        </h3>
        <div className="scalping-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          <div className="scalping-metric">
            <span className="scalping-label">Total</span>
            <span className="scalping-value">{stats.total}</span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label">L/S</span>
            <span className="scalping-value">
              <span style={{ color: '#22c55e' }}>{stats.longs}</span>/
              <span style={{ color: '#ef4444' }}>{stats.shorts}</span>
            </span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label">Avg RRR</span>
            <span className="scalping-value">{stats.avgRR.toFixed(2)}</span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label">Open</span>
            <span className="scalping-value" style={{ color: getStatusColor('open') }}>{stats.open}</span>
          </div>
        </div>
      </div>

      {/* Confidence Breakdown */}
      <div className="scalping-section">
        <h3 className="scalping-section-title">
          <Shield size={14} /> Confidence Distribution
        </h3>
        <div className="scalping-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <div className="scalping-metric">
            <span className="scalping-label" style={{ color: '#22c55e' }}>HIGH</span>
            <span className="scalping-value">{stats.highConf}</span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label" style={{ color: '#f59e0b' }}>MEDIUM</span>
            <span className="scalping-value">{stats.medConf}</span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label" style={{ color: '#94a3b8' }}>LOW</span>
            <span className="scalping-value">{stats.lowConf}</span>
          </div>
        </div>
      </div>

      {/* Signal Feed */}
      <div className="scalping-section">
        <h3 className="scalping-section-title">
          <Crosshair size={14} /> Recent Signals
        </h3>
        <div style={{ maxHeight: 400, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {signals.length === 0 && (
            <div className="scalping-empty">No signals recorded yet</div>
          )}
          {signals.slice(0, 80).map((sig) => (
            <div key={sig.id} style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
              borderRadius: 6, fontSize: 11, background: 'rgba(255,255,255,0.03)',
              borderLeft: `3px solid ${getSideColor(sig.side)}`,
            }}>
              <span style={{ color: '#64748b', minWidth: 48, fontSize: 10 }}>{formatTime(sig.timestamp)}</span>
              <span style={{ color: getSideColor(sig.side), fontWeight: 700, minWidth: 40 }}>
                {sig.side?.includes('LONG') ? 'LONG' : sig.side?.includes('SHORT') ? 'SHORT' : sig.side}
              </span>
              <span style={{ color: getConfColor(sig.confidence), minWidth: 44 }}>
                {sig.confidence}
              </span>
              <span style={{ color: '#94a3b8', minWidth: 32 }}>
                1:{sig.risk_reward.toFixed(1)}
              </span>
              <span style={{
                color: getStatusColor(sig.status), minWidth: 40, fontSize: 9,
                textTransform: 'uppercase', letterSpacing: '0.05em',
              }}>
                {sig.status}
              </span>
              <span style={{ color: '#64748b', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {sig.reason?.slice(0, 80)}{sig.reason?.length > 80 ? '...' : ''}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
