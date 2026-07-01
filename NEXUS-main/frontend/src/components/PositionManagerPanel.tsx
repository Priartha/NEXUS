import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  DollarSign,
  Activity,
  Target,
  Shield,
  BarChart3,
  StopCircle,
  PlayCircle,
} from 'lucide-react'

interface PositionState {
  balance: number
  peak_balance: number
  drawdown_pct: number
  open_positions: number
  daily_pnl: number
  daily_trades: number
  consecutive_losses: number
  total_closed: number
  leverage: number
  max_positions: number
  daily_loss_limit_pct: number
}

export function PositionManagerPanel() {
  const [state, setState] = useState<PositionState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)
  const [showOpenForm, setShowOpenForm] = useState(false)
  const [openSide, setOpenSide] = useState<'long' | 'short'>('long')
  const [openSize, setOpenSize] = useState('')
  const [openLev, setOpenLev] = useState('1')

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/position/status')
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
    fetchStatus()
    const interval = setInterval(fetchStatus, 10000)
    return () => clearInterval(interval)
  }, [fetchStatus])

  const doAction = async (url: string, body?: any) => {
    setActionMsg(null)
    try {
      const res = await fetch(url, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      })
      const json = await res.json()
      if (res.ok) {
        setActionMsg(json.status === 'ok' ? 'Success' : 'Action completed')
      } else {
        setActionMsg(`Error: ${json.detail ?? json.error ?? 'unknown'}`)
      }
      fetchStatus()
    } catch (e: any) {
      setActionMsg(`Failed: ${e.message}`)
    }
  }

  if (loading && !state) {
    return (
      <div className="position-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading position status...</span>
        </div>
      </div>
    )
  }

  const isPaused = (state?.consecutive_losses ?? 0) >= 3 || (state?.drawdown_pct ?? 0) >= 10
  const isLimited = (state?.drawdown_pct ?? 0) >= (state?.daily_loss_limit_pct ?? 5) * 0.8

  return (
    <div className="position-panel">
      <div className="dsp-header">
        <h2><Target size={14} /> Position Manager</h2>
        <div className="dsp-controls">
          <button className="dsp-btn" onClick={fetchStatus} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {actionMsg && (
        <div className={`dsp-backup-msg ${actionMsg.includes('Failed') || actionMsg.includes('Error') ? 'error' : 'success'}`}>
          {actionMsg.includes('Failed') || actionMsg.includes('Error') ? <AlertTriangle size={12} /> : null}
          <span>{actionMsg}</span>
        </div>
      )}

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchStatus}>Retry</button>
        </div>
      )}

      {state && (
        <>
          <div className="dsp-summary">
            <div className={`dsp-stat ${isPaused ? 'negative' : ''}`}>
              <div className="dsp-stat-icon"><Shield size={16} /></div>
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Status</span>
                <span className="dsp-stat-value">{isPaused ? 'RISK ALERT' : 'Active'}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-icon"><DollarSign size={16} /></div>
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Balance</span>
                <span className="dsp-stat-value">${state.balance.toFixed(2)}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-icon"><Activity size={16} /></div>
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Daily P&L</span>
                <span className={`dsp-stat-value ${state.daily_pnl >= 0 ? 'positive' : 'negative'}`}>
                  ${state.daily_pnl.toFixed(2)}
                </span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-icon"><BarChart3 size={16} /></div>
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Drawdown</span>
                <span className={`dsp-stat-value ${isLimited ? 'negative' : 'positive'}`}>
                  {state.drawdown_pct.toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          <div className="dsp-section">
            <h3>Account Summary</h3>
            <div className="position-card">
              <div className="position-details">
                <div className="position-row">
                  <span className="position-label">Open Positions</span>
                  <span className="position-value">{state.open_positions} / {state.max_positions}</span>
                </div>
                <div className="position-row">
                  <span className="position-label">Daily Trades</span>
                  <span className="position-value">{state.daily_trades}</span>
                </div>
                <div className="position-row">
                  <span className="position-label">Total Closed</span>
                  <span className="position-value">{state.total_closed}</span>
                </div>
                <div className="position-row">
                  <span className="position-label">Consecutive Losses</span>
                  <span className={`position-value ${state.consecutive_losses >= 3 ? 'negative' : ''}`}>
                    {state.consecutive_losses}
                  </span>
                </div>
                <div className="position-row">
                  <span className="position-label">Max Leverage</span>
                  <span className="position-value">{state.leverage}x</span>
                </div>
                <div className="position-row">
                  <span className="position-label">Daily Loss Limit</span>
                  <span className="position-value">{state.daily_loss_limit_pct}%</span>
                </div>
                <div className="position-row">
                  <span className="position-label">Peak Balance</span>
                  <span className="position-value">${state.peak_balance.toFixed(2)}</span>
                </div>
              </div>
            </div>
          </div>

          {state.consecutive_losses >= 3 && (
            <div className="dsp-error">
              <AlertTriangle size={12} />
              <span>Risk circuit: {state.consecutive_losses} consecutive losses detected</span>
            </div>
          )}

          {state.drawdown_pct >= state.daily_loss_limit_pct * 0.8 && (
            <div className="dsp-error">
              <AlertTriangle size={12} />
              <span>Drawdown approaching daily loss limit ({state.drawdown_pct.toFixed(1)}% / {state.daily_loss_limit_pct}%)</span>
            </div>
          )}

          <div className="dsp-section">
            <h3>Manual Controls</h3>
            <p style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
              Note: Open/close requires the position manager to have an active price feed.
            </p>
            {!showOpenForm ? (
              <div className="position-actions">
                <button className="dsp-btn" onClick={() => setShowOpenForm(true)}>
                  <PlayCircle size={12} /> Open Position
                </button>
                <button className="dsp-btn danger" onClick={() => doAction('/position/close')}>
                  <StopCircle size={12} /> Close All
                </button>
              </div>
            ) : (
              <div className="position-card">
                <div className="position-input-group">
                  <select
                    value={openSide}
                    onChange={e => setOpenSide(e.target.value as any)}
                    className="position-input"
                  >
                    <option value="long">Long</option>
                    <option value="short">Short</option>
                  </select>
                  <input
                    type="number"
                    placeholder="Size (USD)"
                    value={openSize}
                    onChange={e => setOpenSize(e.target.value)}
                    className="position-input"
                  />
                  <input
                    type="number"
                    placeholder="Leverage"
                    value={openLev}
                    onChange={e => setOpenLev(e.target.value)}
                    className="position-input"
                  />
                </div>
                <div className="position-actions" style={{ marginTop: 8 }}>
                  <button className="dsp-btn" onClick={() => {
                    doAction('/position/open', {
                      side: openSide,
                      size: openSize ? parseFloat(openSize) : undefined,
                      leverage: openLev ? parseFloat(openLev) : 1,
                    })
                    setShowOpenForm(false)
                  }}>
                    Submit
                  </button>
                  <button className="dsp-btn" onClick={() => setShowOpenForm(false)}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
