import { useCallback, useEffect, useState } from 'react'
import { Activity, TrendingUp, TrendingDown, Target, Shield, Zap, Clock } from 'lucide-react'
import type { TradeSignal } from '../types/market'

export default function SignalLogPanel() {
  const [signals, setSignals] = useState<TradeSignal[]>([])
  const [loading, setLoading] = useState(true)

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch('/signals/journal?limit=100')
      if (res.ok) setSignals(await res.json())
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => void fetchSignals(), 0)
    const interval = setInterval(fetchSignals, 15000)
    return () => { clearTimeout(initial); clearInterval(interval) }
  }, [fetchSignals])

  if (loading) return <p className="empty-state">Loading signals...</p>

  const open = signals.filter((s) => s.status === 'open' || s.status === 'pending')
  const closed = signals.filter((s) => s.status !== 'open' && s.status !== 'pending')

  return (
    <div className="signal-log-panel">
      <div className="signal-log-hdr">
        <Activity size={13} />
        <span>Signal Log</span>
        {open.length > 0 && <span className="signal-log-count">{open.length} active</span>}
      </div>

      {signals.length === 0 && (
        <div className="signal-log-empty">
          <Shield size={20} className="signal-log-empty-icon" />
          <p>No signals generated yet.</p>
        </div>
      )}

      {open.length > 0 && (
        <div className="signal-log-section">
          <div className="signal-log-section-hdr">Active / Pending</div>
          {open.map((s) => <SignalRow key={s.id} signal={s} />)}
        </div>
      )}

      {closed.length > 0 && (
        <div className="signal-log-section">
          <div className="signal-log-section-hdr">History</div>
          {closed.slice(0, 30).map((s) => <SignalRow key={s.id} signal={s} />)}
        </div>
      )}
    </div>
  )
}

function SignalRow({ signal }: { signal: TradeSignal }) {
  const isBuy = signal.side === 'buy'
  const pnl = signal.exit_price ? ((signal.exit_price - signal.entry) / signal.entry * 100) * (isBuy ? 1 : -1) : null
  const won = pnl !== null && pnl > 0

  return (
    <div className={`signal-row ${isBuy ? 'signal-buy' : 'signal-sell'} ${signal.status}`}>
      <div className="signal-row-icon">
        {isBuy ? <TrendingUp size={13} className="signal-up" /> : <TrendingDown size={13} className="signal-down" />}
      </div>
      <div className="signal-row-body">
        <div className="signal-row-top">
          <span className={`signal-row-side ${isBuy ? 'bullish' : 'bearish'}`}>
            {isBuy ? 'BUY' : 'SELL'}
          </span>
          <span className="signal-row-confidence">{(signal.confidence * 100).toFixed(0)}%</span>
          <span className="signal-row-model">{signal.model}</span>
        </div>
        <div className="signal-row-details">
          <span>Entry: ${signal.entry?.toFixed(2) ?? '--'}</span>
          <span>SL: ${signal.stop_loss?.toFixed(2) ?? '--'}</span>
          <span>TP: ${signal.exit_price?.toFixed(2) ?? '--'}</span>
          <span>RR: {signal.risk_reward?.toFixed(2) ?? '--'}</span>
        </div>
        {signal.reason && <div className="signal-row-reason">{signal.reason}</div>}
        <div className="signal-row-meta">
          <span className={`signal-row-status ${signal.status}`}>{signal.status}</span>
          <span><Clock size={10} /> {new Date(signal.timestamp).toLocaleTimeString()}</span>
          {pnl !== null && (
            <span className={won ? 'signal-pnl-pos' : 'signal-pnl-neg'}>
              {won ? '+' : ''}{pnl.toFixed(2)}%
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
