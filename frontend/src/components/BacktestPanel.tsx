import { useCallback, useEffect, useState } from 'react'
import { BarChart3, Play, TrendingDown, DollarSign, Target, Zap, AlertTriangle, CheckCircle, XCircle } from 'lucide-react'
import type { BacktestRun } from '../types/market'
import { formatPrice } from '../types/market'

export default function BacktestPanel() {
  const [runs, setRuns] = useState<BacktestRun[]>([])
  const [selectedRun, setSelectedRun] = useState<BacktestRun | null>(null)
  const [running, setRunning] = useState(false)
  const [candleCount, setCandleCount] = useState(500)
  const [positionSize, setPositionSize] = useState(2)
  const [trades, setTrades] = useState<any[]>([])
  const [equityCurve, setEquityCurve] = useState<any[]>([])
  const [showTrades, setShowTrades] = useState(false)

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch('/backtest/runs')
      setRuns(await res.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchRuns()
  }, [fetchRuns])

  const runBacktest = async () => {
    setRunning(true)
    setShowTrades(false)
    setTrades([])
    setEquityCurve([])
    try {
      const res = await fetch('/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candle_count: candleCount, position_size_pct: positionSize / 100 }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        console.error('Backtest failed:', err)
        return
      }
      const result: BacktestRun = await res.json()
      setRuns((prev) => [result, ...prev])
      setSelectedRun(result)
      if (result.trades) setTrades(result.trades)
      if (result.equity_curve) setEquityCurve(result.equity_curve)
    } catch (e) {
      console.error('Backtest error:', e)
    } finally { setRunning(false) }
  }

  const loadRunDetail = async (runId: string) => {
    try {
      const res = await fetch(`/backtest/runs/${runId}`)
      const data = await res.json()
      setSelectedRun(data)
      setTrades(data.trades || [])
      setEquityCurve(data.equity_curve || [])
      setShowTrades(true)
    } catch { /* ignore */ }
  }

  const resetData = async () => {
    try {
      await fetch('/backtest/reset', { method: 'POST' })
      setRuns([])
      setSelectedRun(null)
      setTrades([])
      setEquityCurve([])
      setShowTrades(false)
    } catch { /* ignore */ }
  }

  const verdict = selectedRun ? (() => {
    if (selectedRun.win_rate >= 0.50 && selectedRun.profit_factor != null && selectedRun.profit_factor >= 1.5 && selectedRun.max_drawdown_pct < 0.15) {
      return { label: 'GOOD MODEL', icon: CheckCircle, color: '#36c7a5' }
    }
    if (selectedRun.win_rate < 0.40 || (selectedRun.profit_factor != null && selectedRun.profit_factor < 1.0)) {
      return { label: 'BAD MODEL', icon: XCircle, color: '#f1616d' }
    }
    return { label: 'NEEDS WORK', icon: AlertTriangle, color: '#f59f43' }
  })() : null

  return (
    <div className="bt-panel">
      <div className="bt-panel-hdr">
        <BarChart3 size={14} className="bt-hdr-icon" />
        <span>Strategy Backtest</span>
        <span className="bt-hdr-badge">v2</span>
      </div>

      <div className="bt-controls">
        <div className="bt-ctl-group">
          <label className="bt-ctl-label">Candles</label>
          <input className="bt-ctl-input" type="number" value={candleCount}
            onChange={(e) => setCandleCount(Number(e.target.value))} min={100} max={2000} />
        </div>
        <div className="bt-ctl-group">
          <label className="bt-ctl-label">Risk</label>
          <div className="bt-ctl-unit-wrap">
            <input className="bt-ctl-input" type="number" value={positionSize}
              onChange={(e) => setPositionSize(Number(e.target.value))} min={0.5} max={10} step={0.5} />
            <span className="bt-ctl-unit">%</span>
          </div>
        </div>
        <button className="bt-exec" onClick={runBacktest} disabled={running}>
          {running ? <><span className="bt-spinner" /> Running...</> : <><Play size={11} /> Execute</>}
        </button>
        <button className="bt-reset-btn" onClick={resetData} title="Reset all backtest data">
          Reset
        </button>
      </div>

      {selectedRun && (
        <div className="bt-result">
          {verdict && (
            <div className="bt-verdict" style={{ borderColor: verdict.color }}>
              <verdict.icon size={14} color={verdict.color} />
              <span style={{ color: verdict.color, fontWeight: 700 }}>{verdict.label}</span>
              <span className="bt-verdict-sub">WR {(selectedRun.win_rate * 100).toFixed(0)}% · PF {selectedRun.profit_factor != null ? selectedRun.profit_factor.toFixed(2) : '∞'} · DD {selectedRun.max_drawdown_pct.toFixed(1)}%</span>
            </div>
          )}

          <div className="bt-result-grid">
            <div className={`bt-cell ${selectedRun.total_pnl >= 0 ? 'green' : 'red'}`}>
              <div className="bt-cell-label">PnL</div>
              <div className="bt-cell-val">${selectedRun.total_pnl.toFixed(2)}</div>
              <div className={`bt-cell-sub ${selectedRun.total_pnl_pct >= 0 ? 'green' : 'red'}`}>
                {selectedRun.total_pnl_pct >= 0 ? '+' : ''}{selectedRun.total_pnl_pct.toFixed(2)}%
              </div>
            </div>
            <div className={`bt-cell ${selectedRun.win_rate >= 0.5 ? 'green' : 'red'}`}>
              <div className="bt-cell-label">Win Rate</div>
              <div className="bt-cell-val">{(selectedRun.win_rate * 100).toFixed(1)}%</div>
              <div className="bt-cell-sub">{selectedRun.winning_trades}W / {selectedRun.losing_trades}L</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Profit Factor</div>
              <div className="bt-cell-val">{selectedRun.profit_factor != null ? selectedRun.profit_factor.toFixed(2) : '∞'}</div>
              <div className="bt-cell-sub">{selectedRun.total_trades} trades</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Sharpe</div>
              <div className="bt-cell-val">{selectedRun.sharpe_ratio.toFixed(2)}</div>
              <div className="bt-cell-sub">annualized</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Max DD</div>
              <div className="bt-cell-val red">{selectedRun.max_drawdown_pct.toFixed(2)}%</div>
              <div className="bt-cell-sub">-${selectedRun.max_drawdown.toFixed(2)}</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Balance</div>
              <div className="bt-cell-val">${formatPrice(selectedRun.final_balance)}</div>
              <div className="bt-cell-sub">from ${formatPrice(selectedRun.initial_balance)}</div>
            </div>
          </div>

          <div className="bt-strip">
            <span><DollarSign size={11} /> Avg Win <strong className="green">+${selectedRun.avg_win.toFixed(2)}</strong></span>
            <span><TrendingDown size={11} /> Avg Loss <strong className="red">-${selectedRun.avg_loss.toFixed(2)}</strong></span>
            <span><Target size={11} /> RR <strong>{selectedRun.total_trades > 0 ? (selectedRun.avg_win / Math.max(selectedRun.avg_loss, 0.01)).toFixed(2) : '--'}</strong></span>
            {selectedRun.max_consecutive_losses != null && (
              <span><AlertTriangle size={11} /> Max Loss Streak <strong className="red">{selectedRun.max_consecutive_losses}</strong></span>
            )}
          </div>

          {equityCurve.length > 0 && (
            <div className="bt-equity-mini">
              <svg viewBox={`0 0 ${equityCurve.length} 40`} className="bt-equity-svg" preserveAspectRatio="none">
                {(() => {
                  const vals = equityCurve.map(e => e.account_balance)
                  const min = Math.min(...vals)
                  const max = Math.max(...vals)
                  const range = max - min || 1
                  const points = vals.map((v, i) => `${i},${40 - ((v - min) / range) * 36}`).join(' ')
                  const isProfit = vals[vals.length - 1] >= vals[0]
                  return (
                    <>
                      <polyline points={points} fill="none" stroke={isProfit ? '#36c7a5' : '#f1616d'} strokeWidth="1.5" />
                    </>
                  )
                })()}
              </svg>
              <span className="bt-equity-label">Equity Curve</span>
            </div>
          )}

          {showTrades && trades.length > 0 && (
            <div className="bt-trades-section">
              <div className="bt-trades-hdr">
                <span>Trades ({trades.length})</span>
                <button className="bt-trades-toggle" onClick={() => setShowTrades(false)}>Close</button>
              </div>
              <div className="bt-trades-list">
                {trades.slice(0, 30).map((t, i) => (
                  <div key={i} className={`bt-trade-row ${t.pnl >= 0 ? 'green' : 'red'}`}>
                    <span className="bt-t-num">{i + 1}</span>
                    <span className="bt-t-side">{t.side?.toUpperCase()}</span>
                    <span className="bt-t-entry">${t.entry_price?.toFixed(0)}</span>
                    <span className="bt-t-exit">${t.exit_price?.toFixed(0)}</span>
                    <span className="bt-t-pnl">{t.pnl >= 0 ? '+' : ''}{t.pnl?.toFixed(2)}</span>
                    <span className="bt-t-reason">{t.close_reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {runs.length > 0 && (
        <div className="bt-history">
          <div className="bt-history-hdr">Run History</div>
          <div className="bt-history-list">
            {runs.slice(0, 15).map((run) => (
              <button key={run.id} type="button"
                className={`bt-hist-item ${selectedRun?.id === run.id ? 'active' : ''} ${run.total_pnl >= 0 ? 'green' : 'red'}`}
                onClick={() => loadRunDetail(run.id)}>
                <span className="bt-hist-date">{new Date(run.created_at ?? run.end_date).toLocaleDateString()}</span>
                <span className="bt-hist-time">{new Date(run.created_at ?? run.end_date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                <span className="bt-hist-pnl">${run.total_pnl?.toFixed(0) ?? '0'}</span>
                <span className="bt-hist-wr">{(run.win_rate * 100).toFixed(0)}%</span>
                <span className="bt-hist-trades">{run.total_trades}tx</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {!selectedRun && runs.length === 0 && (
        <div className="bt-empty">
          <Zap size={24} className="bt-empty-icon" />
          <p>Configure parameters and execute a backtest to see if the model works on past data.</p>
          <p className="bt-empty-hint">Good model = 50%+ win rate, profit factor {'>'} 1.5, drawdown {'<'} 15%</p>
        </div>
      )}
    </div>
  )
}
