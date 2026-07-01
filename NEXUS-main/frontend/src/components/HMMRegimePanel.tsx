import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, AlertTriangle, TrendingUp, TrendingDown, Minus, Activity, Play } from 'lucide-react'

interface HMMState {
  is_trained: boolean
  n_regimes: number
  regime_names: Record<string, string>
  version: number
  history_length: number
  last_train_ts: number
  recent_regimes: string[]
}

function getCurrentRegimeName(s: HMMState): string | null {
  if (!s.recent_regimes || s.recent_regimes.length === 0) return null
  const last = s.recent_regimes[s.recent_regimes.length - 1]
  return s.regime_names?.[last] ?? last ?? null
}

function getRegimeDistribution(s: HMMState): Record<string, number> {
  if (!s.recent_regimes || s.recent_regimes.length === 0) return {}
  const counts: Record<string, number> = {}
  for (const r of s.recent_regimes) {
    counts[r] = (counts[r] ?? 0) + 1
  }
  const dist: Record<string, number> = {}
  const total = s.recent_regimes.length
  for (const [k, v] of Object.entries(counts)) {
    dist[s.regime_names?.[k] ?? k] = v / total
  }
  return dist
}

export function HMMRegimePanel() {
  const [state, setState] = useState<HMMState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [trainMsg, setTrainMsg] = useState<string | null>(null)
  const [training, setTraining] = useState(false)

  const fetchState = useCallback(async () => {
    try {
      const res = await fetch('/hmm/regime')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setState(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchState()
    const interval = setInterval(fetchState, 30000)
    return () => clearInterval(interval)
  }, [fetchState])

  const triggerTrain = async () => {
    setTraining(true)
    setTrainMsg(null)
    try {
      const res = await fetch('/hmm/train', { method: 'POST' })
      const json = await res.json()
      setTrainMsg(json.status === 'ok' ? 'Training complete' : `Error: ${json.detail}`)
      fetchState()
    } catch (e: any) {
      setTrainMsg(`Failed: ${e.message}`)
    } finally {
      setTraining(false)
    }
  }

  const getRegimeIcon = (regime: string) => {
    if (regime.includes('bull')) return <TrendingUp size={14} />
    if (regime.includes('bear')) return <TrendingDown size={14} />
    return <Minus size={14} />
  }

  const getRegimeColor = (regime: string) => {
    if (regime.includes('bull')) return '#22c55e'
    if (regime.includes('bear')) return '#ef4444'
    return '#f59e0b'
  }

  if (loading && !state) {
    return (
      <div className="hmm-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading regime data...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="hmm-panel">
      <div className="dsp-header">
        <h2><Activity size={14} /> HMM Regime Classifier</h2>
        <div className="dsp-controls">
          <button className="dsp-btn" onClick={triggerTrain} disabled={training} title="Train Now">
            <Play size={12} /> {training ? 'Training...' : 'Train'}
          </button>
          <button className="dsp-btn" onClick={fetchState} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {trainMsg && (
        <div className="dsp-info" style={{ padding: '6px 12px', fontSize: 12, color: '#8ab4f8', background: 'rgba(138, 180, 248, 0.08)', borderRadius: 6, marginBottom: 8 }}>
          {trainMsg}
        </div>
      )}

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchState}>Retry</button>
        </div>
      )}

      {state && (
        <>
          <div className="dsp-summary">
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Status</span>
                <span className={`dsp-stat-value ${state.is_trained ? 'positive' : 'negative'}`}>
                  {state.is_trained ? 'Trained' : 'Not Trained'}
                </span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Regimes</span>
                <span className="dsp-stat-value">{state.n_regimes}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">History</span>
                <span className="dsp-stat-value">{state.history_length}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Version</span>
                <span className="dsp-stat-value">v{state.version}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Auto-Training</span>
                <span className="dsp-stat-value" style={{ color: '#8ab4f8' }}>Every 60m</span>
              </div>
            </div>
          </div>

          {Object.keys(state.regime_names).length > 0 && (
            <div className="dsp-section">
              <h3>Regime Definitions</h3>
              <div className="regime-probs">
                {Object.entries(state.regime_names).map(([key, name]) => {
                  const friendlyName = name.replace('_trend', '').replace('_', ' ')
                  const color = friendlyName.includes('bull') ? '#22c55e' : friendlyName.includes('bear') ? '#ef4444' : '#f59e0b'
                  return (
                    <div key={key} className="regime-prob-row">
                      <span className="regime-prob-label" style={{ color }}>
                        {getRegimeIcon(friendlyName)} {friendlyName}
                      </span>
                      <span className="regime-prob-value" style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        ID: {key}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {state.recent_regimes && state.recent_regimes.length > 0 && (
            <div className="dsp-section">
              <h3>Current Regime</h3>
              <div className="dsp-summary">
                <div className="dsp-stat">
                  <div className="dsp-stat-info">
                    <span className="dsp-stat-label">Detected</span>
                    <span className="dsp-stat-value" style={{ color: getRegimeColor(getCurrentRegimeName(state) ?? 'range') }}>
                      {getCurrentRegimeName(state) ?? 'unknown'}
                    </span>
                  </div>
                </div>
              </div>

              <h3 style={{ marginTop: 12 }}>Regime Distribution</h3>
              <div className="regime-probs">
                {Object.entries(getRegimeDistribution(state)).map(([name, prob]) => {
                  const friendlyName = name.replace('_trend', '').replace('_', ' ')
                  const color = friendlyName.includes('bull') ? '#22c55e' : friendlyName.includes('bear') ? '#ef4444' : '#f59e0b'
                  return (
                    <div key={name} className="regime-prob-row">
                      <span className="regime-prob-label" style={{ color }}>
                        {getRegimeIcon(friendlyName)} {friendlyName}
                      </span>
                      <div className="regime-prob-bar-bg">
                        <div className="regime-prob-bar" style={{ width: `${(prob * 100).toFixed(1)}%`, backgroundColor: color }} />
                      </div>
                      <span className="regime-prob-value">{(prob * 100).toFixed(1)}%</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {(!state.recent_regimes || state.recent_regimes.length === 0) && state.is_trained && (
            <div className="dsp-section">
              <h3>No Regime Data</h3>
              <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Model is trained ({state.history_length} samples) but no regimes detected yet.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
