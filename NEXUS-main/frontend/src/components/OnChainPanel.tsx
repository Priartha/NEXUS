import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  Activity,
  DollarSign,
  TrendingUp,
  Users,
  GitCommit,
  BarChart3,
} from 'lucide-react'

interface OnChainSnapshot {
  timestamp: number
  mvrv_z_score: number
  exchange_flow_balance: number
  sopr: number
  whale_tx_count: number
  active_addresses: number
  transaction_count: number
  hash_rate: number
}

interface OnChainSignal {
  direction: string
  strength: number
  reasons: string[]
  snapshot: {
    mvrv_zscore: number
    exchange_net_flow: number
    whale_tx_count: number
    sopr: number
  }
}

interface OnChainMetrics {
  signal: OnChainSignal
  history: OnChainSnapshot[]
  sources_loaded: string[]
  state: {
    last_refresh: number
    cached: boolean
    history_length: number
    use_fallback: boolean
    glassnode_configured: boolean
  }
}

export function OnChainPanel() {
  const [metrics, setMetrics] = useState<OnChainMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch('/onchain/metrics')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setMetrics(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchMetrics()
    const interval = setInterval(fetchMetrics, 60000)
    return () => clearInterval(interval)
  }, [fetchMetrics])

  if (loading && !metrics) {
    return (
      <div className="onchain-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading on-chain data...</span>
        </div>
      </div>
    )
  }

  const MetricCard = ({ label, value, icon, suffix = '', color = '#f59e0b' }: {
    label: string; value: number | null; icon: React.ReactNode; suffix?: string; color?: string
  }) => (
    <div className="dsp-stat">
      <div className="dsp-stat-icon" style={{ color }}>{icon}</div>
      <div className="dsp-stat-info">
        <span className="dsp-stat-label">{label}</span>
        <span className="dsp-stat-value">
          {value !== null ? `${value.toFixed?.(4) ?? value}${suffix}` : '--'}
        </span>
      </div>
    </div>
  )

  return (
    <div className="onchain-panel">
      <div className="dsp-header">
        <h2><Activity size={14} /> On-Chain Metrics</h2>
        <div className="dsp-controls">
          <span className="dsp-badge">{metrics?.sources_loaded?.length ?? 0} sources</span>
          <button className="dsp-btn" onClick={fetchMetrics} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchMetrics}>Retry</button>
        </div>
      )}

      {metrics && (
        <>
          {metrics.signal && (
            <div className="dsp-summary">
              <div className="dsp-stat">
                <div className="dsp-stat-info">
                  <span className="dsp-stat-label">Signal Direction</span>
                  <span className="dsp-stat-value" style={{
                    color: metrics.signal.direction === 'bullish' ? '#22c55e' : metrics.signal.direction === 'bearish' ? '#ef4444' : '#f59e0b',
                  }}>
                    {metrics.signal.direction.toUpperCase()}
                  </span>
                </div>
              </div>
              <div className="dsp-stat">
                <div className="dsp-stat-info">
                  <span className="dsp-stat-label">Signal Strength</span>
                  <span className="dsp-stat-value">{(metrics.signal.strength * 100).toFixed(0)}%</span>
                </div>
              </div>
              <div className="dsp-stat">
                <div className="dsp-stat-info">
                  <span className="dsp-stat-label">Data Source</span>
                  <span className="dsp-stat-value" style={{ fontSize: 10 }}>
                    {metrics.state?.use_fallback ? 'Fallback' : 'Glassnode'}
                  </span>
                </div>
              </div>
              <div className="dsp-stat">
                <div className="dsp-stat-info">
                  <span className="dsp-stat-label">History</span>
                  <span className="dsp-stat-value">{metrics.history.length} samples</span>
                </div>
              </div>
            </div>
          )}

          {metrics.signal?.snapshot && (
            <div className="dsp-section">
              <h3>Latest Snapshot</h3>
              <div className="dsp-summary">
                <MetricCard
                  label="MVRV Z-Score"
                  value={metrics.signal.snapshot.mvrv_zscore}
                  icon={<DollarSign size={16} />}
                  color={metrics.signal.snapshot.mvrv_zscore > 3 ? '#ef4444' : metrics.signal.snapshot.mvrv_zscore < 0.5 ? '#22c55e' : '#f59e0b'}
                />
                <MetricCard
                  label="SOPR"
                  value={metrics.signal.snapshot.sopr}
                  icon={<TrendingUp size={16} />}
                  color={metrics.signal.snapshot.sopr > 1 ? '#22c55e' : '#ef4444'}
                />
                <MetricCard
                  label="Whale TX"
                  value={metrics.signal.snapshot.whale_tx_count}
                  icon={<Users size={16} />}
                />
                <MetricCard
                  label="Exch. Net Flow"
                  value={metrics.signal.snapshot.exchange_net_flow}
                  icon={<GitCommit size={16} />}
                  color={metrics.signal.snapshot.exchange_net_flow > 0 ? '#ef4444' : '#22c55e'}
                />
              </div>
            </div>
          )}

          {metrics.signal?.reasons && metrics.signal.reasons.length > 0 && (
            <div className="dsp-section">
              <h3>Signal Reasons</h3>
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 10, lineHeight: 1.6, color: 'var(--text-muted)' }}>
                {metrics.signal.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          {metrics.history.length > 0 && (
            <div className="dsp-section">
              <h3>Network Activity (Latest)</h3>
              <div className="dsp-summary">
                <MetricCard
                  label="Active Addresses"
                  value={metrics.history[0].active_addresses}
                  icon={<Users size={16} />}
                />
                <MetricCard
                  label="Transactions"
                  value={metrics.history[0].transaction_count}
                  icon={<BarChart3 size={16} />}
                />
                <MetricCard
                  label="Hash Rate"
                  value={metrics.history[0].hash_rate}
                  icon={<Activity size={16} />}
                  suffix=" EH/s"
                />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
