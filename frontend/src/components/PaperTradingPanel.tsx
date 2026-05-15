import { useCallback, useEffect, useState } from 'react'
import { DollarSign, TrendingUp, TrendingDown, Activity, BarChart3 } from 'lucide-react'
import type { PaperTrade } from '../types/market'
import { useChartStore } from '../store/chartStore'

export default function PaperTradingPanel() {
  const stats = useChartStore((state) => state.paperTrading)
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [loading, setLoading] = useState(true)

  const fetchTrades = useCallback(async () => {
    try {
      const res = await fetch('/paper-trades?status=open')
      setTrades(await res.json())
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => void fetchTrades(), 0)
    const interval = setInterval(fetchTrades, 10000)
    return () => {
      clearTimeout(initial)
      clearInterval(interval)
    }
  }, [fetchTrades])

  return (
    <div className="pt-panel">
      <div className="pt-hdr">
        <BarChart3 size={13} className="pt-hdr-icon" />
        <span>Paper Trading</span>
        {stats && <span className="pt-hdr-count">{stats.total_trades}</span>}
      </div>

      {stats && (
        <div className="pt-stats">
          <div className={`pt-stat ${stats.total_pnl >= 0 ? 'green' : 'red'}`}>
            <DollarSign size={13} />
            <div>
              <span className="pt-stat-label">PnL</span>
              <strong className="pt-stat-val">${stats.total_pnl.toFixed(2)}</strong>
            </div>
          </div>
          <div className={`pt-stat ${stats.win_rate >= 0.5 ? 'green' : 'red'}`}>
            <Activity size={13} />
            <div>
              <span className="pt-stat-label">Win Rate</span>
              <strong className="pt-stat-val">{(stats.win_rate * 100).toFixed(0)}%</strong>
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
        </div>
      )}

      <div className="pt-section-hdr">Open Positions ({trades.length})</div>
      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : trades.length === 0 ? (
        <p className="empty-state">No open positions.</p>
      ) : (
        <div className="pt-trade-list">
          {trades.map((t) => {
            const pnl = t.entry_price ? ((t.stop_loss - t.entry_price) / t.entry_price * 100).toFixed(2) : '0'
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
                  <span>Risk: {pnl}%</span>
                  <span>Qty: {t.quantity?.toFixed(4)}</span>
                  {t.confidence && <span>Conf: {(t.confidence * 100).toFixed(0)}%</span>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
