import { useCallback, useEffect, useState } from 'react'
import { BarChart3, Play, TrendingDown, DollarSign, Target, Zap } from 'lucide-react'
import type { BacktestRun } from '../types/market'
import { formatPrice } from '../types/market'

export default function BacktestPanel() {
  const [runs, setRuns] = useState<BacktestRun[]>([])
  const [selectedRun, setSelectedRun] = useState<BacktestRun | null>(null)
  const [running, setRunning] = useState(false)
  const [candleCount, setCandleCount] = useState(500)
  const [positionSize, setPositionSize] = useState(2)

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch('/backtest/runs')
      setRuns(await res.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => void fetchRuns(), 0)
    return () => clearTimeout(initial)
  }, [fetchRuns])

  const runBacktest = async () => {
    setRunning(true)
    try {
      const res = await fetch('/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candle_count: candleCount, position_size_pct: positionSize / 100 }),
      })
      const result: BacktestRun = await res.json()
      setRuns((prev) => [result, ...prev])
      setSelectedRun(result)
    } catch { /* ignore */ } finally { setRunning(false) }
  }

  const loadRunDetail = async (runId: string) => {
    try {
      const res = await fetch(`/backtest/runs/${runId}`)
      setSelectedRun(await res.json())
    } catch { /* ignore */ }
  }

  return (
    <div className="bt-panel">
      <div className="bt-panel-hdr">
        <BarChart3 size={14} className="bt-hdr-icon" />
        <span>Strategy Backtest</span>
        <span className="bt-hdr-badge">v1</span>
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
              onChange={(e) => setPositionSize(Number(e.target.value))} min={0.5} max={100} step={0.5} />
            <span className="bt-ctl-unit">%</span>
          </div>
        </div>
        <button className="bt-exec" onClick={runBacktest} disabled={running}>
          {running ? <><span className="bt-spinner" /> Running...</> : <><Play size={11} /> Execute</>}
        </button>
      </div>

      {selectedRun && (
        <div className="bt-result">
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
              <div className="bt-cell-val red">{(selectedRun.max_drawdown_pct * 100).toFixed(2)}%</div>
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
          </div>
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
          <p>Configure parameters and execute a backtest to begin.</p>
        </div>
      )}
    </div>
  )
}
