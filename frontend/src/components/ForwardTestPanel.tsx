import { useEffect, useState, useCallback } from 'react'
import {
  Play,
  Pause,
  RotateCcw,
  TrendingUp,
  TrendingDown,
  Clock,
  Target,
  Shield,
  Zap,
  BarChart3,
  Activity,
  AlertCircle,
  CheckCircle,
  XCircle,
  Timer,
  DollarSign,
  Percent,
  RefreshCw,
} from 'lucide-react'

interface TradeStats {
  balance: number
  initial_balance: number
  total_pnl: number
  total_pnl_pct: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  signal_count: number
  peak_balance: number
  max_drawdown: number
  max_drawdown_pct: number
  updated_at: string
}

interface OpenTrade {
  id: string
  signal_id: string
  timestamp: number
  side: 'buy' | 'sell'
  entry_price: number
  stop_loss: number
  initial_sl: number
  tp1: number
  tp2: number
  quantity: number
  remaining_qty: number
  status: string
  confidence: number
  reason: string
  slippage: number
  commission: number
  bars_held: number
  tp1_hit: boolean
  total_pnl: number
  opened_at: string
}

interface ClosedTrade {
  id: string
  signal_id: string
  timestamp: number
  side: 'buy' | 'sell'
  entry_price: number
  stop_loss: number
  exit_price: number
  tp1: number
  tp2: number
  quantity: number
  status: string
  confidence: number
  reason: string
  slippage: number
  commission: number
  bars_held: number
  tp1_hit: boolean
  total_pnl: number
  pnl: number
  close_reason: string
  closed_at: string
  opened_at: string
}

interface DemoStatus {
  running: boolean
  stats: TradeStats | null
  open_trades: OpenTrade[]
  last_update: string
}

async function safeFetchJson(url: string): Promise<any | null> {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    const contentType = res.headers.get('content-type')
    if (!contentType || !contentType.includes('application/json')) return null
    return await res.json()
  } catch {
    return null
  }
}

async function safePost(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'POST' })
    return res.ok
  } catch {
    return false
  }
}

export function ForwardTestPanel() {
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [openTrades, setOpenTrades] = useState<OpenTrade[]>([])
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    try {
      const [demoStatus, demoTrades] = await Promise.all([
        safeFetchJson('/demo/status'),
        safeFetchJson('/demo/trades'),
      ])

      if (demoStatus) {
        setStatus(demoStatus)
      }
      if (demoTrades) {
        setOpenTrades(demoTrades.open_trades || [])
        setClosedTrades(demoTrades.closed_trades || [])
      }
    } catch (e: any) {
      setError(e.message || 'Failed to load demo data')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 10000)
    return () => clearInterval(interval)
  }, [loadData])

  const handleStart = async () => {
    setActionLoading(true)
    setError(null)
    const success = await safePost('/demo/start')
    if (success) {
      await loadData()
    } else {
      setError('Failed to start demo. Ensure backend is running.')
    }
    setActionLoading(false)
  }

  const handleStop = async () => {
    setActionLoading(true)
    setError(null)
    const success = await safePost('/demo/stop')
    if (success) {
      await loadData()
    } else {
      setError('Failed to stop demo.')
    }
    setActionLoading(false)
  }

  const handleReset = async () => {
    if (!confirm('Reset all demo trading data? This cannot be undone.')) return
    setActionLoading(true)
    setError(null)
    const success = await safePost('/demo/reset')
    if (success) {
      await loadData()
    } else {
      setError('Failed to reset demo.')
    }
    setActionLoading(false)
  }

  const stats = status?.stats
  const isRunning = status?.running ?? false

  const formatPrice = (n: number | null | undefined): string => {
    if (n == null) return '--'
    return n.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  }

  const formatTime = (ts: string | number): string => {
    const d = new Date(ts)
    return d.toLocaleTimeString()
  }

  const formatDuration = (bars: number): string => {
    const minutes = bars * 5
    if (minutes < 60) return `${minutes}m`
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  }

  if (loading) {
    return (
      <div className="forward-test-panel">
        <div className="ftp-loading">
          <RefreshCw size={16} className="ftp-loading-spinner" />
          <span>Loading demo data...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="forward-test-panel">
      {/* Header */}
      <div className="ftp-header">
        <h2>
          <Activity size={14} />
          Forward Testing (Demo)
        </h2>
        <div className="ftp-controls">
          {!isRunning ? (
            <button className="ftp-btn start" onClick={handleStart} disabled={actionLoading}>
              <Play size={12} />
              Start Demo
            </button>
          ) : (
            <button className="ftp-btn stop" onClick={handleStop} disabled={actionLoading}>
              <Pause size={12} />
              Stop Demo
            </button>
          )}
          <button className="ftp-btn reset" onClick={handleReset} disabled={actionLoading}>
            <RotateCcw size={12} />
            Reset
          </button>
          <div className={`ftp-status-indicator ${isRunning ? 'running' : 'stopped'}`}>
            <span className={`ftp-status-dot ${isRunning ? 'running' : 'stopped'}`} />
            {isRunning ? 'Running' : 'Stopped'}
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="ftp-error">
          <AlertCircle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Stats Overview */}
      {stats && (
        <div className="ftp-stats-grid">
          <div className="ftp-stat-card">
            <div className="ftp-stat-icon">
              <DollarSign size={16} />
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Balance</span>
              <span className="ftp-stat-value">${formatPrice(stats.balance)}</span>
            </div>
          </div>

          <div className={`ftp-stat-card ${stats.total_pnl >= 0 ? 'positive' : 'negative'}`}>
            <div className="ftp-stat-icon">
              {stats.total_pnl >= 0 ? (
                <TrendingUp size={16} />
              ) : (
                <TrendingDown size={16} />
              )}
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Total P&L</span>
              <span className="ftp-stat-value">
                {stats.total_pnl >= 0 ? '+' : ''}${formatPrice(stats.total_pnl)}
              </span>
              <span className="ftp-stat-sub">
                {stats.total_pnl_pct >= 0 ? '+' : ''}
                {stats.total_pnl_pct.toFixed(2)}%
              </span>
            </div>
          </div>

          <div className="ftp-stat-card">
            <div className="ftp-stat-icon">
              <BarChart3 size={16} />
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Win Rate</span>
              <span className="ftp-stat-value">
                {(stats.win_rate * 100).toFixed(1)}%
              </span>
              <span className="ftp-stat-sub">
                {stats.winning_trades}W / {stats.losing_trades}L
              </span>
            </div>
          </div>

          <div className="ftp-stat-card">
            <div className="ftp-stat-icon">
              <Target size={16} />
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Total Trades</span>
              <span className="ftp-stat-value">{stats.total_trades}</span>
              <span className="ftp-stat-sub">{stats.signal_count} signals</span>
            </div>
          </div>

          <div className="ftp-stat-card">
            <div className="ftp-stat-icon">
              <Shield size={16} />
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Max Drawdown</span>
              <span className="ftp-stat-value">
                {stats.max_drawdown_pct.toFixed(2)}%
              </span>
              <span className="ftp-stat-sub">${formatPrice(stats.max_drawdown)}</span>
            </div>
          </div>

          <div className="ftp-stat-card">
            <div className="ftp-stat-icon">
              <Percent size={16} />
            </div>
            <div className="ftp-stat-info">
              <span className="ftp-stat-label">Avg Win / Loss</span>
              <span className="ftp-stat-value">${formatPrice(stats.avg_win)}</span>
              <span className="ftp-stat-sub">/ ${formatPrice(stats.avg_loss)}</span>
            </div>
          </div>
        </div>
      )}

      {/* Open Trades */}
      {openTrades.length > 0 && (
        <div className="ftp-section">
          <h3>
            <Clock size={12} />
            Open Trades ({openTrades.length})
          </h3>
          <div className="ftp-trade-list">
            {openTrades.map((trade) => (
              <div key={trade.id} className={`ftp-trade-card ${trade.side}`}>
                <div className="ftp-trade-header">
                  <div className="ftp-trade-side">
                    {trade.side === 'buy' ? (
                      <span className="ftp-side-badge bullish">BUY</span>
                    ) : (
                      <span className="ftp-side-badge bearish">SELL</span>
                    )}
                    <span className="ftp-trade-id">{trade.id}</span>
                  </div>
                  <div className="ftp-trade-meta">
                    <span>
                      <Timer size={10} />
                      {formatDuration(trade.bars_held)}
                    </span>
                    <span>
                      <Zap size={10} />
                      {(trade.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                <div className="ftp-trade-levels">
                  <div className="ftp-level">
                    <span className="ftp-level-label">Entry</span>
                    <span className="ftp-level-value">
                      ${formatPrice(trade.entry_price)}
                    </span>
                  </div>
                  <div className="ftp-level stop">
                    <span className="ftp-level-label">SL</span>
                    <span className="ftp-level-value">
                      ${formatPrice(trade.stop_loss)}
                    </span>
                  </div>
                  <div className="ftp-level tp">
                    <span className="ftp-level-label">TP1</span>
                    <span className="ftp-level-value">${formatPrice(trade.tp1)}</span>
                  </div>
                  <div className="ftp-level tp">
                    <span className="ftp-level-label">TP2</span>
                    <span className="ftp-level-value">${formatPrice(trade.tp2)}</span>
                  </div>
                </div>

                <div className="ftp-trade-footer">
                  <span className="ftp-trade-reason">{trade.reason}</span>
                  {trade.tp1_hit && (
                    <span className="ftp-tp1-badge">
                      <CheckCircle size={10} />
                      TP1 Hit
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Closed Trades */}
      {closedTrades.length > 0 && (
        <div className="ftp-section">
          <h3>Recent Closed Trades ({closedTrades.length})</h3>
          <div className="ftp-trade-list">
            {closedTrades.slice(-10).reverse().map((trade) => (
              <div
                key={trade.id}
                className={`ftp-trade-card closed ${trade.pnl >= 0 ? 'win' : 'loss'}`}
              >
                <div className="ftp-trade-header">
                  <div className="ftp-trade-side">
                    {trade.side === 'buy' ? (
                      <span className="ftp-side-badge bullish">BUY</span>
                    ) : (
                      <span className="ftp-side-badge bearish">SELL</span>
                    )}
                    <span className="ftp-trade-id">{trade.id}</span>
                  </div>
                  <div className="ftp-trade-pnl">
                    <span
                      className={`ftp-pnl-value ${trade.pnl >= 0 ? 'positive' : 'negative'}`}
                    >
                      {trade.pnl >= 0 ? '+' : ''}${formatPrice(trade.pnl)}
                    </span>
                  </div>
                </div>

                <div className="ftp-trade-levels">
                  <div className="ftp-level">
                    <span className="ftp-level-label">Entry</span>
                    <span className="ftp-level-value">
                      ${formatPrice(trade.entry_price)}
                    </span>
                  </div>
                  <div className="ftp-level">
                    <span className="ftp-level-label">Exit</span>
                    <span className="ftp-level-value">
                      ${formatPrice(trade.exit_price)}
                    </span>
                  </div>
                  <div className="ftp-level">
                    <span className="ftp-level-label">Bars</span>
                    <span className="ftp-level-value">{trade.bars_held}</span>
                  </div>
                </div>

                <div className="ftp-trade-footer">
                  <span className={`ftp-close-reason ${trade.close_reason}`}>
                    {trade.close_reason === 'stop_loss' && <XCircle size={10} />}
                    {trade.close_reason === 'tp2_hit' && <CheckCircle size={10} />}
                    {trade.close_reason === 'time_exit' && <Clock size={10} />}
                    {trade.close_reason.replace('_', ' ')}
                  </span>
                  <span className="ftp-trade-time">{formatTime(trade.closed_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!stats && !isRunning && closedTrades.length === 0 && (
        <div className="ftp-empty">
          <AlertCircle size={24} />
          <h3>No Demo Data</h3>
          <p>
            Start the forward demo test to begin tracking live trades with the
            current strategy configuration.
          </p>
          <button className="ftp-btn start" onClick={handleStart}>
            <Play size={12} />
            Start Demo Test
          </button>
        </div>
      )}
    </div>
  )
}
