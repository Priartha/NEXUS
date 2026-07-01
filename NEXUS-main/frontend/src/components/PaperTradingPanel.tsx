import { useCallback, useEffect, useState } from 'react'
import { DollarSign, TrendingUp, TrendingDown, Activity, BarChart3, Play, Square, RefreshCw, CheckCircle2 } from 'lucide-react'
import type { PaperTrade } from '../types/market'
import { useChartStore } from '../store/chartStore'

export default function PaperTradingPanel() {
  const stats = useChartStore((state) => state.paperTrading)
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [closedTrades, setClosedTrades] = useState<PaperTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const [openRes, closedRes, statusRes] = await Promise.allSettled([
        fetch('/paper-trades?status=open'),
        fetch('/paper-trades?status=closed'),
        fetch('/paper-trades/status'),
      ])
      if (openRes.status === 'fulfilled') setTrades(await openRes.value.json())
      if (closedRes.status === 'fulfilled') setClosedTrades(await closedRes.value.json())
      if (statusRes.status === 'fulfilled' && statusRes.value.ok) {
        const status = await statusRes.value.json()
        setActive(Boolean(status?.enabled))
      }
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [fetchData])

  const togglePaperTrading = async () => {
    try {
      const res = await fetch('/paper-trades/toggle', { method: 'POST' })
      if (res.ok) {
        const status = await res.json()
        setActive(Boolean(status?.enabled))
      }
      fetchData()
    } catch { /* ignore */ }
  }

  const resetData = async () => {
    try {
      await fetch('/paper-trades/reset', { method: 'POST' })
      setTrades([])
      setClosedTrades([])
      fetchData()
    } catch { /* ignore */ }
  }

  const totalPnl = stats?.total_pnl ?? 0
  const winRate = stats?.win_rate ?? 0
  const totalTrades = stats?.total_trades ?? 0

  const verdict = (() => {
    if (totalTrades < 3) return null
    if (winRate >= 0.50 && totalPnl > 0) return { label: 'WINNING', color: '#36c7a5' }
    if (winRate < 0.35 || totalPnl < -100) return { label: 'LOSING', color: '#f1616d' }
    return { label: 'BREAK EVEN', color: '#f59f43' }
  })()

  const recentClosed = closedTrades.slice(-10).reverse()

  return (
    <div className="pt-panel">
      <div className="pt-hdr">
        <BarChart3 size={13} className="pt-hdr-icon" />
        <span>Paper Trading</span>
        <span className={`pt-status-dot ${active ? 'active' : 'inactive'}`} />
      </div>

      <div className="pt-controls">
        <button className={`pt-toggle-btn ${active ? 'active' : ''}`} onClick={togglePaperTrading}>
          {active ? <Square size={12} /> : <Play size={12} />}
          {active ? 'Stop' : 'Start'}
        </button>
        <button className="pt-refresh-btn" onClick={fetchData} title="Refresh">
          <RefreshCw size={12} />
        </button>
        <button className="pt-reset-btn" onClick={resetData} title="Reset all data">
          Reset
        </button>
      </div>

      {stats && (
        <div className="pt-stats">
          <div className={`pt-stat ${totalPnl >= 0 ? 'green' : 'red'}`}>
            <DollarSign size={13} />
            <div>
              <span className="pt-stat-label">PnL</span>
              <strong className="pt-stat-val">${totalPnl.toFixed(2)}</strong>
            </div>
          </div>
          <div className={`pt-stat ${winRate >= 0.5 ? 'green' : 'red'}`}>
            <Activity size={13} />
            <div>
              <span className="pt-stat-label">Win Rate</span>
              <strong className="pt-stat-val">{(winRate * 100).toFixed(0)}%</strong>
            </div>
          </div>
          <div className="pt-stat">
            <TrendingUp size={13} />
            <div>
              <span className="pt-stat-label">Wins</span>
              <strong className="pt-stat-val green">{stats.winning_trades}</strong>
            </div>
          </div>
          <div className="pt-stat">
            <TrendingDown size={13} />
            <div>
              <span className="pt-stat-label">Losses</span>
              <strong className="pt-stat-val red">{stats.losing_trades}</strong>
            </div>
          </div>
          <div className="pt-stat">
            <CheckCircle2 size={13} />
            <div>
              <span className="pt-stat-label">Closed</span>
              <strong className="pt-stat-val">{stats.closed_trades}</strong>
            </div>
          </div>
        </div>
      )}

      {verdict && (
        <div className="pt-verdict" style={{ borderColor: verdict.color }}>
          <span style={{ color: verdict.color, fontWeight: 700 }}>{verdict.label}</span>
          <span className="pt-verdict-sub">{totalTrades} trades · ${totalPnl.toFixed(0)} PnL</span>
        </div>
      )}

      <div className="pt-section-hdr">Open Positions ({trades.length})</div>
      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : trades.length === 0 ? (
        <p className="empty-state">No open positions. {active ? 'Waiting for signals...' : 'Start paper trading to begin.'}</p>
      ) : (
        <div className="pt-trade-list">
          {trades.map((t) => {
            const pnlPct = t.pnl_pct != null ? Number(t.pnl_pct).toFixed(2) : (t.entry_price ? ((t.stop_loss - t.entry_price) / t.entry_price * 100).toFixed(2) : '0')
            return (
              <div key={t.id} className={`pt-trade ${t.side === 'buy' ? 'green' : 'red'}`}>
                <div className="pt-trade-head">
                  <span className="pt-trade-side">{t.side.toUpperCase()}</span>
                  <span className="pt-trade-sym">{t.symbol}</span>
                  <span className="pt-trade-tf">{t.timeframe}</span>
                </div>
                <div className="pt-trade-body">
                  <span>Entry ${t.entry_price?.toFixed(2)}</span>
                  <span>SL ${t.stop_loss?.toFixed(2)}</span>
                  <span>TP ${t.take_profit?.toFixed(2)}</span>
                </div>
                <div className="pt-trade-meta">
                  <span>Risk: {pnlPct}%</span>
                  <span>Qty: {t.quantity?.toFixed(4)}</span>
                  {t.confidence && <span>Conf: {(t.confidence * 100).toFixed(0)}%</span>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {recentClosed.length > 0 && (
        <>
          <div className="pt-section-hdr">Recent Closed Trades ({closedTrades.length})</div>
          <div className="pt-closed-list">
            {recentClosed.map((t, i) => {
              const pnl = t.pnl ?? 0
              return (
                <div key={i} className={`pt-closed-row ${pnl >= 0 ? 'green' : 'red'}`}>
                  <span className="pt-c-status">CLOSED</span>
                  <span className="pt-c-side">{t.side?.toUpperCase()}</span>
                  <span className="pt-c-entry">${t.entry_price?.toFixed(0)}</span>
                  <span className="pt-c-exit">${t.exit_price?.toFixed(0)}</span>
                  <span className="pt-c-pnl">{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}</span>
                  <span className="pt-c-reason">{t.close_reason}</span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
