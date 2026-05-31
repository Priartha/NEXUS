import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BarChart3,
  Play,
  TrendingDown,
  DollarSign,
  Target,
  Zap,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Upload,
  FileSpreadsheet,
  Database,
  Globe,
} from 'lucide-react'
import { formatPrice } from '../types/market'

interface BacktestRun {
  id: string
  symbol: string
  timeframe: string
  created_at: string
  end_date: string
  initial_balance: number
  final_balance: number
  total_pnl: number
  total_pnl_pct: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  profit_factor: number | null
  sharpe_ratio: number
  max_drawdown: number
  max_drawdown_pct: number
  avg_win: number
  avg_loss: number
  avg_hold_bars: number
  data_quality?: DataQualityReport
  trades?: any[]
  equity_curve?: any[]
}

interface DataQualityReport {
  verdict: string
  score: number
  source_type: string
  provider: string
  requested_symbol: string
  actual_symbol: string
  symbol_alias_used: boolean
  timeframe: string
  native_timeframe: boolean
  requested_count?: number | null
  candle_count: number
  unique_candle_count: number
  first_timestamp?: number | null
  last_timestamp?: number | null
  expected_interval_ms: number
  latest_age_ms?: number | null
  stale: boolean
  duplicate_count: number
  missing_candle_count: number
  irregular_interval_count: number
  invalid_ohlc_count: number
  zero_volume_count: number
  warnings: string[]
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

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function metric(value: number | null | undefined, digits = 2): string {
  return isNumber(value) ? value.toFixed(digits) : '--'
}

function percent(value: number | null | undefined, digits = 1): string {
  return isNumber(value) ? `${(value * 100).toFixed(digits)}%` : '--'
}

function signedPercentValue(value: number | null | undefined, digits = 2): string {
  if (!isNumber(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`
}

function timeLabel(timestamp?: number | null): string {
  return isNumber(timestamp) ? new Date(timestamp).toLocaleString() : '--'
}

export default function BacktestPanel() {
  const [runs, setRuns] = useState<BacktestRun[]>([])
  const [selectedRun, setSelectedRun] = useState<BacktestRun | null>(null)
  const [running, setRunning] = useState(false)
  const [candleCount, setCandleCount] = useState(5000)
  const [positionSize, setPositionSize] = useState(2.0)
  const [maxHoldBars, setMaxHoldBars] = useState(6)
  const [trailingStop, setTrailingStop] = useState(true)
  const [tpMultiplier, setTpMultiplier] = useState(1.5)
  const [trades, setTrades] = useState<any[]>([])
  const [equityCurve, setEquityCurve] = useState<any[]>([])
  const [expandedTrades, setExpandedTrades] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingRuns, setLoadingRuns] = useState(false)

  // CSV Import state
  const [dataSource, setDataSource] = useState<'api' | 'csv'>('api')
  const [csvFormat, setCsvFormat] = useState('auto')
  const [csvFormats, setCsvFormats] = useState<any[]>([])
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [csvMetadata, setCsvMetadata] = useState<any>(null)
  const [csvParsing, setCsvParsing] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchRuns = useCallback(async () => {
    setLoadingRuns(true)
    try {
      const data = await safeFetchJson('/backtest/runs')
      if (data) {
        setRuns(Array.isArray(data) ? data : [])
      }
    } catch (e) {
      console.error('Failed to fetch backtest runs:', e)
    } finally {
      setLoadingRuns(false)
    }
  }, [])

  useEffect(() => {
    fetchRuns()
    fetchFormats()
  }, [fetchRuns])

  const fetchFormats = useCallback(async () => {
    try {
      const data = await safeFetchJson('/csv-import/formats')
      if (data) setCsvFormats(data)
    } catch {
      console.error('Failed to fetch CSV formats')
    }
  }, [])

  const runBacktest = async () => {
    setRunning(true)
    setError(null)
    setTrades([])
    setEquityCurve([])
    try {
      const res = await fetch('/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candle_count: candleCount,
          position_size_pct: positionSize / 100,
          symbol: 'BTCUSD',
          timeframe: '5m',
          initial_balance: 10000,
          max_hold_bars: maxHoldBars,
          breakeven_threshold: 0.5,
          trailing_stop: trailingStop,
          tp_atr_multiplier: tpMultiplier,
          signal_side_mode: 'normal',
          avoid_reason_tokens: [],
          adaptive_learning: true,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        setError(err?.detail || `Backtest failed with status ${res.status}`)
        return
      }
      const contentType = res.headers.get('content-type')
      if (!contentType || !contentType.includes('application/json')) {
        setError('Server returned invalid response')
        return
      }
      const result: BacktestRun = await res.json()
      setRuns((prev) => [result, ...prev])
      setSelectedRun(result)

      // Fetch full details with trades
      const detail = await safeFetchJson(`/backtest/runs/${result.id}`)
      if (detail) {
        if (detail.trades) setTrades(detail.trades)
        if (detail.equity_curve) setEquityCurve(detail.equity_curve)
      }
    } catch (e: any) {
      setError(e.message || 'Backtest error')
    } finally {
      setRunning(false)
    }
  }

  const loadRunDetail = async (runId: string) => {
    try {
      const data = await safeFetchJson(`/backtest/runs/${runId}`)
      if (data) {
        setSelectedRun(data)
        setTrades(data.trades || [])
        setEquityCurve(data.equity_curve || [])
        setExpandedTrades(false)
      }
    } catch (e) {
      console.error('Failed to load run detail:', e)
    }
  }

  const resetData = async () => {
    try {
      await fetch('/backtest/reset', { method: 'POST' })
      setRuns([])
      setSelectedRun(null)
      setTrades([])
      setEquityCurve([])
      setExpandedTrades(false)
      setCsvFile(null)
      setCsvMetadata(null)
      fetchRuns()
    } catch (e) {
      console.error('Failed to reset:', e)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.name.endsWith('.csv')) {
      setError('Please select a CSV file')
      return
    }
    setCsvFile(file)
    setCsvMetadata(null)
    setError(null)
  }

  const parseCsvFile = async () => {
    if (!csvFile) return
    setCsvParsing(true)
    setError(null)
    try {
      const text = await csvFile.text()
      const res = await fetch('/csv-import/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          format: csvFormat,
          symbol: 'BTCUSDT',
          timeframe: '5m',
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        setError(err?.detail || 'Failed to parse CSV')
        return
      }
      const data = await res.json()
      setCsvMetadata(data.metadata)
      if (data.warnings?.length > 0) {
        setError(data.warnings.join('; '))
      }
    } catch (e: any) {
      setError(e.message || 'CSV parse error')
    } finally {
      setCsvParsing(false)
    }
  }

  const runCsvBacktest = async () => {
    if (!csvFile) return
    setRunning(true)
    setError(null)
    setTrades([])
    setEquityCurve([])
    try {
      const text = await csvFile.text()
      const res = await fetch('/csv-import/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: text,
          format: csvFormat,
          symbol: 'BTCUSDT',
          timeframe: '5m',
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        setError(err?.detail || 'Backtest failed')
        return
      }
      const result: BacktestRun = await res.json()
      setRuns((prev) => [result, ...prev])
      setSelectedRun(result)

      const detail = await safeFetchJson(`/backtest/runs/${result.id}`)
      if (detail) {
        if (detail.trades) setTrades(detail.trades)
        if (detail.equity_curve) setEquityCurve(detail.equity_curve)
      }
    } catch (e: any) {
      setError(e.message || 'Backtest error')
    } finally {
      setRunning(false)
    }
  }

  const verdict = selectedRun ? (() => {
    const pf = selectedRun.profit_factor
    const dd = selectedRun.max_drawdown_pct
    const trades = selectedRun.total_trades
    const pnlPct = selectedRun.total_pnl_pct

    if (!isNumber(pf) || !isNumber(dd) || !isNumber(trades) || !isNumber(pnlPct)) {
      return { label: 'DATA UNAVAILABLE', icon: AlertTriangle, color: '#f59f43' }
    }
    if (trades < 30) {
      return { label: 'LOW SAMPLE', icon: AlertTriangle, color: '#f59f43' }
    }
    if (pf >= 1.5 && pnlPct > 0 && dd < 15) {
      return { label: 'PASSED STRICT GATE', icon: CheckCircle, color: '#1fe3a3' }
    }
    if (pf > 1.0 && pnlPct > 0 && dd < 15) {
      return { label: 'PROFITABLE, WEAK PF', icon: AlertTriangle, color: '#f59f43' }
    }
    return { label: 'FAILING BACKTEST', icon: XCircle, color: '#ff5b6b' }
  })() : null

  return (
    <div className="bt-panel">
      {/* Header */}
      <div className="bt-panel-hdr">
        <BarChart3 size={14} />
        <span>Strategy Backtest</span>
        <span className="bt-hdr-badge">v2</span>
      </div>

      {/* Data Source Selector */}
      <div className="bt-source-selector">
        <button
          className={`bt-source-btn ${dataSource === 'api' ? 'active' : ''}`}
          onClick={() => setDataSource('api')}
        >
          <Globe size={12} />
          Live API
        </button>
        <button
          className={`bt-source-btn ${dataSource === 'csv' ? 'active' : ''}`}
          onClick={() => setDataSource('csv')}
        >
          <Database size={12} />
          Import CSV
        </button>
      </div>

      {/* Controls */}
      <div className="bt-controls">
        {dataSource === 'api' && (
          <>
            <div className="bt-ctl-group">
              <label className="bt-ctl-label">Candles</label>
              <input
                className="bt-ctl-input"
                type="number"
                value={candleCount}
                onChange={(e) => setCandleCount(Number(e.target.value))}
                min={100}
                max={2000}
              />
            </div>
          </>
        )}
        <div className="bt-ctl-group">
          <label className="bt-ctl-label">Risk</label>
          <div className="bt-ctl-unit-wrap">
            <input
              className="bt-ctl-input"
              type="number"
              value={positionSize}
              onChange={(e) => setPositionSize(Number(e.target.value))}
              min={0.5}
              max={10}
              step={0.5}
            />
            <span className="bt-ctl-unit">%</span>
          </div>
        </div>
        <div className="bt-ctl-group">
          <label className="bt-ctl-label">Hold</label>
          <input
            className="bt-ctl-input"
            type="number"
            value={maxHoldBars}
            onChange={(e) => setMaxHoldBars(Number(e.target.value))}
            min={4}
            max={100}
            step={2}
          />
        </div>
        <div className="bt-ctl-group">
          <label className="bt-ctl-label">TP (ATR)</label>
          <input
            className="bt-ctl-input"
            type="number"
            value={tpMultiplier}
            onChange={(e) => setTpMultiplier(Number(e.target.value))}
            min={0}
            max={8}
            step={1}
          />
        </div>
        <button
          className={`bt-toggle-btn ${trailingStop ? 'active' : ''}`}
          onClick={() => setTrailingStop(!trailingStop)}
          title="Trailing stop — moves SL to breakeven at 1R profit"
        >
          Trail {trailingStop ? 'ON' : 'OFF'}
        </button>
        {dataSource === 'api' ? (
          <button className="bt-exec" onClick={runBacktest} disabled={running}>
            {running ? (
              <>
                <span className="bt-spinner" />
                Running...
              </>
            ) : (
              <>
                <Play size={11} />
                Execute
              </>
            )}
          </button>
        ) : (
          <button className="bt-exec" onClick={runCsvBacktest} disabled={running || !csvFile}>
            {running ? (
              <>
                <span className="bt-spinner" />
                Running...
              </>
            ) : (
              <>
                <Play size={11} />
                Run CSV
              </>
            )}
          </button>
        )}
        <button className="bt-reset-btn" onClick={resetData} title="Reset all backtest data">
          <RefreshCw size={11} />
          Reset
        </button>
      </div>

      {/* CSV Import Section */}
      {dataSource === 'csv' && (
        <div className="bt-csv-section">
          <div className="bt-csv-header">
            <FileSpreadsheet size={14} />
            <span>Import Historical Data</span>
          </div>

          <div className="bt-csv-row">
            <div className="bt-csv-format">
              <label className="bt-ctl-label">Format</label>
              <select
                className="bt-csv-select"
                value={csvFormat}
                onChange={(e) => setCsvFormat(e.target.value)}
              >
                {csvFormats.map((f) => (
                  <option key={f.id} value={f.id}>{f.name}</option>
                ))}
              </select>
            </div>

            <div className="bt-csv-upload">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                style={{ display: 'none' }}
              />
              <button
                className="bt-csv-upload-btn"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload size={12} />
                {csvFile ? csvFile.name : 'Select CSV File'}
              </button>
              {csvFile && (
                <button
                  className="bt-csv-parse-btn"
                  onClick={parseCsvFile}
                  disabled={csvParsing}
                >
                  {csvParsing ? 'Parsing...' : 'Parse'}
                </button>
              )}
            </div>
          </div>

          {csvMetadata && (
            <div className="bt-csv-meta">
              <div className="bt-csv-meta-item">
                <span className="bt-csv-meta-label">Candles</span>
                <span className="bt-csv-meta-value">{csvMetadata.parsed_candles?.toLocaleString()}</span>
              </div>
              <div className="bt-csv-meta-item">
                <span className="bt-csv-meta-label">Period</span>
                <span className="bt-csv-meta-value">{csvMetadata.date_range}</span>
              </div>
              <div className="bt-csv-meta-item">
                <span className="bt-csv-meta-label">Price Range</span>
                <span className="bt-csv-meta-value">{csvMetadata.price_range}</span>
              </div>
              <div className="bt-csv-meta-item">
                <span className="bt-csv-meta-label">Format</span>
                <span className="bt-csv-meta-value">{csvMetadata.format_detected}</span>
              </div>
            </div>
          )}

          {csvFormats.length > 0 && (
            <div className="bt-csv-hint">
              Supported: {csvFormats.map(f => f.name).join(', ')}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bt-error">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* Results */}
      {selectedRun && (
        <div className="bt-result">
          {/* Verdict */}
          {verdict && (
            <div className="bt-verdict" style={{ borderColor: verdict.color }}>
              <verdict.icon size={14} color={verdict.color} />
              <span style={{ color: verdict.color, fontWeight: 700 }}>{verdict.label}</span>
              <span className="bt-verdict-sub">
                WR {percent(selectedRun.win_rate, 1)} | PF {metric(selectedRun.profit_factor, 4)} | DD{' '}
                {metric(selectedRun.max_drawdown_pct, 4)}%
              </span>
            </div>
          )}

          {/* Stats Grid */}
          <div className="bt-result-grid">
            <div className={`bt-cell ${!isNumber(selectedRun.total_pnl) || selectedRun.total_pnl >= 0 ? 'green' : 'red'}`}>
              <div className="bt-cell-label">PnL</div>
              <div className="bt-cell-val">{isNumber(selectedRun.total_pnl) ? `$${metric(selectedRun.total_pnl, 2)}` : '--'}</div>
              <div className={`bt-cell-sub ${!isNumber(selectedRun.total_pnl_pct) || selectedRun.total_pnl_pct >= 0 ? 'green' : 'red'}`}>
                {signedPercentValue(selectedRun.total_pnl_pct, 4)}
              </div>
            </div>
            <div className={`bt-cell ${isNumber(selectedRun.win_rate) && selectedRun.win_rate < 0.5 ? 'red' : 'green'}`}>
              <div className="bt-cell-label">Win Rate</div>
              <div className="bt-cell-val">{percent(selectedRun.win_rate, 2)}</div>
              <div className="bt-cell-sub">
                {isNumber(selectedRun.winning_trades) ? selectedRun.winning_trades : '--'}W / {isNumber(selectedRun.losing_trades) ? selectedRun.losing_trades : '--'}L
              </div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Profit Factor</div>
              <div className="bt-cell-val">
                {metric(selectedRun.profit_factor, 4)}
              </div>
              <div className="bt-cell-sub">{isNumber(selectedRun.total_trades) ? selectedRun.total_trades : '--'} trades</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Sharpe</div>
              <div className="bt-cell-val">{metric(selectedRun.sharpe_ratio, 4)}</div>
              <div className="bt-cell-sub">ratio</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Max DD</div>
              <div className="bt-cell-val red">{metric(selectedRun.max_drawdown_pct, 4)}%</div>
              <div className="bt-cell-sub">{isNumber(selectedRun.max_drawdown) ? `$${metric(selectedRun.max_drawdown, 2)}` : '--'}</div>
            </div>
            <div className="bt-cell">
              <div className="bt-cell-label">Balance</div>
              <div className="bt-cell-val">${formatPrice(selectedRun.final_balance)}</div>
              <div className="bt-cell-sub">from ${formatPrice(selectedRun.initial_balance)}</div>
            </div>
          </div>

          {/* Strip */}
          <div className="bt-strip">
            <span>
              <DollarSign size={11} /> Avg Win{' '}
              <strong className="green">{isNumber(selectedRun.avg_win) ? `+$${metric(selectedRun.avg_win, 2)}` : '--'}</strong>
            </span>
            <span>
              <TrendingDown size={11} /> Avg Loss{' '}
              <strong className="red">{isNumber(selectedRun.avg_loss) ? `$${metric(selectedRun.avg_loss, 2)}` : '--'}</strong>
            </span>
            <span>
              <Target size={11} /> RR{' '}
              <strong>
                {isNumber(selectedRun.avg_loss) && isNumber(selectedRun.avg_win) && selectedRun.avg_loss > 0 && selectedRun.avg_win > 0
                  ? (selectedRun.avg_win / selectedRun.avg_loss).toFixed(4)
                  : '--'}
              </strong>
            </span>
            <span>
              <Clock size={11} /> Avg Hold{' '}
              <strong>{isNumber(selectedRun.avg_hold_bars) ? `${metric(selectedRun.avg_hold_bars, 1)} bars` : '--'}</strong>
            </span>
          </div>

          {selectedRun.data_quality && (
            <div className="bt-strip">
              <span>
                <Database size={11} /> Data{' '}
                <strong>{selectedRun.data_quality.verdict.replace(/_/g, ' ').toUpperCase()}</strong>
              </span>
              <span>
                Score <strong>{selectedRun.data_quality.score}/100</strong>
              </span>
              <span>
                Source <strong>{selectedRun.data_quality.provider}:{selectedRun.data_quality.source_type}</strong>
              </span>
              <span>
                Symbol <strong>{selectedRun.data_quality.actual_symbol}</strong>
              </span>
              <span>
                Candles <strong>{selectedRun.data_quality.candle_count}/{selectedRun.data_quality.requested_count ?? '--'}</strong>
              </span>
              <span>
                Gaps <strong>{selectedRun.data_quality.missing_candle_count}</strong>
              </span>
              <span>
                Duplicates <strong>{selectedRun.data_quality.duplicate_count}</strong>
              </span>
              <span>
                Last <strong>{timeLabel(selectedRun.data_quality.last_timestamp)}</strong>
              </span>
            </div>
          )}

          {selectedRun.data_quality?.warnings?.length ? (
            <div className="bt-error">
              <AlertTriangle size={14} />
              <span>{selectedRun.data_quality.warnings.join('; ')}</span>
            </div>
          ) : null}

          {/* Equity Curve */}
          {equityCurve.length > 1 && (
            <div className="bt-equity-mini">
              <svg
                viewBox={`0 0 ${Math.max(equityCurve.length, 2)} 40`}
                className="bt-equity-svg"
                preserveAspectRatio="none"
              >
                {(() => {
                  const vals = equityCurve.map((e) => e.account_balance).filter((v) => v != null && !isNaN(v))
                  if (vals.length < 2) return null
                  const min = Math.min(...vals)
                  const max = Math.max(...vals)
                  const range = max - min || 1
                  const points = vals
                    .map((v, i) => `${i},${40 - ((v - min) / range) * 36}`)
                    .join(' ')
                  const isProfit = vals[vals.length - 1] >= vals[0]
                  return (
                    <>
                      <polyline
                        points={points}
                        fill="none"
                        stroke={isProfit ? '#1fe3a3' : '#ff5b6b'}
                        strokeWidth="1.5"
                      />
                    </>
                  )
                })()}
              </svg>
              <span className="bt-equity-label">Equity Curve</span>
            </div>
          )}

          {/* Trades Toggle */}
          {trades.length > 0 && (
            <button className="bt-trades-toggle" onClick={() => setExpandedTrades(!expandedTrades)}>
              {expandedTrades ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Trades ({trades.length})
            </button>
          )}

          {/* Trades List */}
          {expandedTrades && trades.length > 0 && (
            <div className="bt-trades-section">
              <div className="bt-trades-list">
                {trades.slice(0, 50).map((t, i) => (
                  <div key={i} className={`bt-trade-row ${t.pnl >= 0 ? 'green' : 'red'}`}>
                    <span className="bt-t-num">{i + 1}</span>
                    <span className="bt-t-side">{t.side?.toUpperCase()}</span>
                    <span className="bt-t-entry">${t.entry_price?.toFixed(0)}</span>
                    <span className="bt-t-exit">${t.exit_price?.toFixed(0)}</span>
                    <span className="bt-t-pnl">
                      {t.pnl >= 0 ? '+' : ''}
                      {t.pnl?.toFixed(2)}
                    </span>
                    <span className="bt-t-reason">{t.close_reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Run History */}
      {runs.length > 0 && (
        <div className="bt-history">
          <div className="bt-history-hdr">
            <span>Run History</span>
            {loadingRuns && <RefreshCw size={11} className="bt-history-loading" />}
          </div>
          <div className="bt-history-list">
            {runs.slice(0, 15).map((run) => (
              <button
                key={run.id}
                type="button"
                className={`bt-hist-item ${selectedRun?.id === run.id ? 'active' : ''} ${run.total_pnl >= 0 ? 'green' : 'red'}`}
                onClick={() => loadRunDetail(run.id)}
              >
                <span className="bt-hist-date">
                  {new Date(run.created_at ?? run.end_date).toLocaleDateString()}
                </span>
                <span className="bt-hist-time">
                  {new Date(run.created_at ?? run.end_date).toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
                <span className="bt-hist-pnl">{isNumber(run.total_pnl) ? `$${metric(run.total_pnl, 0)}` : '--'}</span>
                <span className="bt-hist-wr">{percent(run.win_rate, 1)}</span>
                <span className="bt-hist-trades">{isNumber(run.total_trades) ? run.total_trades : '--'}tx</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {!selectedRun && runs.length === 0 && (
        <div className="bt-empty">
          <Zap size={24} className="bt-empty-icon" />
          <p>Configure parameters and execute a backtest to see if the model works on past data.</p>
        </div>
      )}
    </div>
  )
}
