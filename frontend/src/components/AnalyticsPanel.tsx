import { useEffect, useState, useCallback } from 'react'
import {
  TrendingUp,
  Minus,
  BarChart3,
  Download,
  Calendar,
  Clock,
  Target,
  Zap,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Database,
  Activity,
  Cpu,
  ChevronDown,
  ChevronUp,
  AlertCircle,
} from 'lucide-react'
import { useChartStore } from '../store/chartStore'

interface PatternStats {
  total_patterns: number
  bullish_patterns: number
  bearish_patterns: number
  completed_patterns: number
  avg_confidence: number
  avg_score: number
  top_patterns: { name: string; direction: string; count: number; avg_conf: number }[]
}

interface RegimeDistribution {
  [phase: string]: { count: number; avg_confidence: number }
}

interface AiAccuracy {
  total_decisions: number
  actionable_decisions?: number
  no_trade_decisions?: number
  grade_distribution: { [grade: string]: { count: number; avg_confidence: number } }
  avg_confidence: number
  avg_setup_score: number
}

interface StorageStats {
  [table: string]: number | string | null
}

interface DailyPerformance {
  date: string
  symbol: string
  total_signals: number
  bullish_signals: number
  bearish_signals: number
  avg_signal_confidence: number | null
  total_paper_trades: number
  paper_wins: number
  paper_losses: number
  paper_pnl: number
  paper_win_rate: number | null
  avg_regime: string | null
  dominant_pattern: string | null
  avg_atr: number | null
  avg_rsi: number | null
  max_drawdown_pct: number | null
}

interface PatternHistory {
  timestamp: number
  pattern_id: string
  name: string
  direction: string
  confidence: number
  score: number
  description: string
  candle_count: number
  completed: number
  symbol: string
  timeframe: string
  session: string | null
  regime_phase: string | null
}

interface RegimeHistory {
  timestamp: number
  symbol: string
  timeframe: string
  phase: string
  bias: string
  confidence: number
  range_high: number | null
  range_low: number | null
  range_mid: number | null
  width_pct: number | null
  atr_compression: number | null
  efficiency_ratio: number | null
  volume_state: string | null
  reason: string | null
}

interface AiDecision {
  timestamp: number
  symbol: string
  timeframe: string
  provider: string | null
  model: string | null
  direction: string | null
  grade: string | null
  readiness: string | null
  confidence: number | null
  setup_score: number | null
  entry: number | null
  stop_loss: number | null
  take_profit: number | null
  risk_reward: number | null
  summary: string | null
  confirmations: string[]
  blockers: string[]
  calculations: string[]
  momentum_score: number | null
  option_symbol: string | null
}

type TabKey = 'overview' | 'patterns' | 'regimes' | 'ai' | 'performance' | 'storage'

const DIRECTION_COLORS: Record<string, string> = {
  bullish: '#1fe3a3',
  bearish: '#ff5b6b',
  neutral: '#8ab4f8',
}

const GRADE_COLORS: Record<string, string> = {
  A_PLUS: '#1fe3a3',
  A: '#1fe3a3',
  B_PLUS: '#8ab4f8',
  B: '#8ab4f8',
  C: '#f59f43',
  NO_TRADE: '#666',
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleString()
}

function formatNumber(n: number | null): string {
  if (n == null) return '--'
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toFixed(2)
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

export function AnalyticsPanel() {
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [loading, setLoading] = useState(true)
  const [patternStats, setPatternStats] = useState<PatternStats | null>(null)
  const [regimeDist, setRegimeDist] = useState<RegimeDistribution | null>(null)
  const [aiAccuracy, setAiAccuracy] = useState<AiAccuracy | null>(null)
  const [storageStats, setStorageStats] = useState<StorageStats | null>(null)
  const [dailyPerf, setDailyPerf] = useState<DailyPerformance[]>([])
  const [patternHistory, setPatternHistory] = useState<PatternHistory[]>([])
  const [regimeHistory, setRegimeHistory] = useState<RegimeHistory[]>([])
  const [aiDecisions, setAiDecisions] = useState<AiDecision[]>([])
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [daysFilter, setDaysFilter] = useState(7)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [stats, dist, accuracy, storage, perf, patterns, regimes, decisions] =
        await Promise.all([
          safeFetchJson(`/history/patterns/stats?days=${daysFilter}`),
          safeFetchJson(`/history/regimes/distribution?days=${daysFilter}`),
          safeFetchJson(`/history/ai/accuracy?days=${daysFilter}&timeframe=${encodeURIComponent(selectedTimeframe)}`),
          safeFetchJson('/history/stats'),
          safeFetchJson(`/history/performance?limit=${daysFilter}`),
          safeFetchJson('/history/patterns?limit=50'),
          safeFetchJson('/history/regimes?limit=50'),
          safeFetchJson('/history/ai?limit=50'),
        ])
      setPatternStats(stats)
      setRegimeDist(dist)
      setAiAccuracy(accuracy)
      setStorageStats(storage)
      setDailyPerf(Array.isArray(perf) ? perf : [])
      setPatternHistory(Array.isArray(patterns) ? patterns : [])
      setRegimeHistory(Array.isArray(regimes) ? regimes : [])
      setAiDecisions(Array.isArray(decisions) ? decisions : [])
    } catch (e: any) {
      setError(e.message || 'Failed to load analytics data')
    } finally {
      setLoading(false)
    }
  }, [daysFilter, selectedTimeframe])

  useEffect(() => {
    loadData()
    const interval = setInterval(loadData, 60000)
    return () => clearInterval(interval)
  }, [loadData])

  const handleExport = async (format: 'csv' | 'json', endpoint: string, filename: string) => {
    try {
      const data = await safeFetchJson(endpoint)
      if (!data) return
      if (format === 'json') {
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: 'application/json',
        })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${filename}.json`
        a.click()
        URL.revokeObjectURL(url)
      } else {
        if (!Array.isArray(data) || data.length === 0) return
        const headers = Object.keys(data[0])
        const csv = [
          headers.join(','),
          ...data.map((row: Record<string, unknown>) =>
            headers
              .map((h) => {
                const val = row[h]
                if (val == null) return ''
                if (typeof val === 'object')
                  return `"${JSON.stringify(val).replace(/"/g, '""')}"`
                return `"${String(val).replace(/"/g, '""')}"`
              })
              .join(',')
          ),
        ].join('\n')
        const blob = new Blob([csv], { type: 'text/csv' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${filename}.csv`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (e) {
      console.error('Export failed:', e)
    }
  }

  const handleCleanup = async () => {
    if (
      !confirm(
        'Run data cleanup? This will delete old records based on retention policies.'
      )
    )
      return
    try {
      await fetch('/history/cleanup', { method: 'POST' })
      loadData()
    } catch (e) {
      console.error('Cleanup failed:', e)
    }
  }

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'overview', label: 'Overview', icon: <BarChart3 size={12} /> },
    { key: 'patterns', label: 'Patterns', icon: <Layers size={12} /> },
    { key: 'regimes', label: 'Regimes', icon: <Activity size={12} /> },
    { key: 'ai', label: 'AI Decisions', icon: <Cpu size={12} /> },
    { key: 'performance', label: 'Performance', icon: <TrendingUp size={12} /> },
    { key: 'storage', label: 'Storage', icon: <Database size={12} /> },
  ]

  return (
    <div className="analytics-panel">
      {/* Header */}
      <div className="analytics-header">
        <h2>
          <Database size={14} />
          Analytics &amp; History
        </h2>
        <div className="analytics-controls">
          <select
            value={daysFilter}
            onChange={(e) => setDaysFilter(Number(e.target.value))}
            className="days-select"
          >
            <option value={1}>24h</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
          <button className="analytics-btn" onClick={loadData} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="analytics-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`analytics-tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="analytics-error">
          <AlertCircle size={14} />
          <span>{error}</span>
          <button className="analytics-btn" onClick={loadData}>
            Retry
          </button>
        </div>
      )}

      {/* Content */}
      <div className="analytics-content">
        {loading ? (
          <div className="analytics-loading">
            <RefreshCw size={16} className="analytics-loading-spinner" />
            <span>Loading analytics...</span>
          </div>
        ) : activeTab === 'overview' ? (
          <OverviewTab
            patternStats={patternStats}
            regimeDist={regimeDist}
            aiAccuracy={aiAccuracy}
            storageStats={storageStats}
          />
        ) : activeTab === 'patterns' ? (
          <PatternsTab
            patternStats={patternStats}
            patternHistory={patternHistory}
            expandedRow={expandedRow}
            setExpandedRow={setExpandedRow}
            onExport={(fmt) => handleExport(fmt, '/history/patterns', 'patterns')}
          />
        ) : activeTab === 'regimes' ? (
          <RegimesTab
            regimeDist={regimeDist}
            regimeHistory={regimeHistory}
            expandedRow={expandedRow}
            setExpandedRow={setExpandedRow}
            onExport={(fmt) => handleExport(fmt, '/history/regimes', 'regimes')}
          />
        ) : activeTab === 'ai' ? (
          <AiTab
            aiAccuracy={aiAccuracy}
            aiDecisions={aiDecisions}
            expandedRow={expandedRow}
            setExpandedRow={setExpandedRow}
            onExport={(fmt) => handleExport(fmt, '/history/ai', 'ai-decisions')}
          />
        ) : activeTab === 'performance' ? (
          <PerformanceTab
            dailyPerf={dailyPerf}
            onExport={(fmt) => handleExport(fmt, '/history/performance', 'performance')}
          />
        ) : activeTab === 'storage' ? (
          <StorageTab
            storageStats={storageStats}
            onCleanup={handleCleanup}
            onExport={(fmt, endpoint, name) => handleExport(fmt, endpoint, name)}
          />
        ) : null}
      </div>
    </div>
  )
}

function OverviewTab({
  patternStats,
  regimeDist,
  aiAccuracy,
  storageStats,
}: {
  patternStats: PatternStats | null
  regimeDist: RegimeDistribution | null
  aiAccuracy: AiAccuracy | null
  storageStats: StorageStats | null
}) {
  const hasData = patternStats || regimeDist || aiAccuracy || storageStats

  if (!hasData) {
    return (
      <div className="analytics-empty">
        <Database size={24} />
        <h3>No Analytics Data</h3>
        <p>
          Historical data recording is not enabled or no data has been collected
          yet.
        </p>
      </div>
    )
  }

  return (
    <div className="overview-grid">
      {/* Pattern Summary */}
      <div className="overview-card">
        <h3>
          <Layers size={13} />
          Pattern Summary
        </h3>
        {patternStats ? (
          <>
            <div className="overview-stat-row">
              <span>Total Patterns</span>
              <strong>{patternStats.total_patterns}</strong>
            </div>
            <div className="overview-stat-row">
              <span>Bullish</span>
              <strong style={{ color: DIRECTION_COLORS.bullish }}>
                {patternStats.bullish_patterns}
              </strong>
            </div>
            <div className="overview-stat-row">
              <span>Bearish</span>
              <strong style={{ color: DIRECTION_COLORS.bearish }}>
                {patternStats.bearish_patterns}
              </strong>
            </div>
            <div className="overview-stat-row">
              <span>Completed</span>
              <strong>{patternStats.completed_patterns}</strong>
            </div>
            <div className="overview-stat-row">
              <span>Avg Confidence</span>
              <strong>
                {(patternStats.avg_confidence * 100).toFixed(1)}%
              </strong>
            </div>
            <div className="overview-stat-row">
              <span>Avg Score</span>
              <strong>{(patternStats.avg_score * 100).toFixed(1)}%</strong>
            </div>
          </>
        ) : (
          <p className="empty-state">No pattern data available</p>
        )}
      </div>

      {/* Regime Distribution */}
      <div className="overview-card">
        <h3>
          <Activity size={13} />
          Regime Distribution
        </h3>
        {regimeDist && Object.keys(regimeDist).length > 0 ? (
          Object.entries(regimeDist).map(([phase, data]) => (
            <div key={phase} className="overview-stat-row">
              <span>{phase.replaceAll('_', ' ')}</span>
              <strong>
                {data.count} ({(data.avg_confidence * 100).toFixed(0)}%)
              </strong>
            </div>
          ))
        ) : (
          <p className="empty-state">No regime data available</p>
        )}
      </div>

      {/* AI Accuracy */}
      <div className="overview-card">
        <h3>
          <Cpu size={13} />
          AI Decision Stats
        </h3>
        {aiAccuracy ? (
          aiAccuracy.total_decisions > 0 ? (
            <>
            <div className="overview-stat-row">
              <span>Total Reviews</span>
              <strong>{aiAccuracy.total_decisions}</strong>
            </div>
            <div className="overview-stat-row">
              <span>Actionable</span>
              <strong>{aiAccuracy.actionable_decisions ?? 0}</strong>
            </div>
            <div className="overview-stat-row">
              <span>No Trade</span>
              <strong>{aiAccuracy.no_trade_decisions ?? 0}</strong>
            </div>
            <div className="overview-stat-row">
              <span>Avg Confidence</span>
              <strong>
                {(aiAccuracy.avg_confidence * 100).toFixed(1)}%
              </strong>
            </div>
            <div className="overview-stat-row">
              <span>Avg Setup Score</span>
              <strong>
                {(aiAccuracy.avg_setup_score * 100).toFixed(1)}%
              </strong>
            </div>
            {Object.entries(aiAccuracy.grade_distribution).map(([grade, data]) => (
              <div key={grade} className="overview-stat-row">
                <span style={{ color: GRADE_COLORS[grade] ?? '#888' }}>
                  {grade}
                </span>
                <strong>
                  {data.count} ({(data.avg_confidence * 100).toFixed(0)}%)
                </strong>
              </div>
            ))}
            </>
          ) : (
            <p className="empty-state">No recent AI decisions in the selected time window</p>
          )
        ) : (
          <p className="empty-state">No AI data available</p>
        )}
      </div>

      {/* Storage Overview */}
      <div className="overview-card">
        <h3>
          <Database size={13} />
          Storage Overview
        </h3>
        {storageStats ? (
          Object.entries(storageStats)
            .filter(
              ([key]) =>
                !key.startsWith('oldest') &&
                !key.startsWith('newest') &&
                key !== 'candle_date_range_days'
            )
            .map(([table, count]) => (
              <div key={table} className="overview-stat-row">
                <span>{table.replaceAll('_', ' ')}</span>
                <strong>{formatNumber(count as number)}</strong>
              </div>
            ))
        ) : (
          <p className="empty-state">No storage data available</p>
        )}
      </div>
    </div>
  )
}

function PatternsTab({
  patternStats,
  patternHistory,
  expandedRow,
  setExpandedRow,
  onExport,
}: {
  patternStats: PatternStats | null
  patternHistory: PatternHistory[]
  expandedRow: string | null
  setExpandedRow: (id: string | null) => void
  onExport: (format: 'csv' | 'json') => void
}) {
  return (
    <div className="analytics-tab-content">
      <div className="analytics-tab-header">
        <h3>Pattern History</h3>
        <div className="export-btns">
          <button className="export-btn" onClick={() => onExport('csv')}>
            <Download size={12} />
            CSV
          </button>
          <button className="export-btn" onClick={() => onExport('json')}>
            <Download size={12} />
            JSON
          </button>
        </div>
      </div>

      {patternStats && patternStats.top_patterns.length > 0 && (
        <div className="top-patterns">
          <h4>Top Patterns</h4>
          <div className="top-pattern-list">
            {patternStats.top_patterns.map((p, i) => (
              <div key={i} className="top-pattern-item">
                <span className="tp-rank">#{i + 1}</span>
                <span className="tp-name">{p.name.replaceAll('_', ' ')}</span>
                <span className={`tp-dir ${p.direction}`}>
                  {p.direction === 'bullish' ? (
                    <ArrowUpRight size={10} />
                  ) : (
                    <ArrowDownRight size={10} />
                  )}
                </span>
                <span className="tp-count">{p.count}</span>
                <span className="tp-conf">
                  {(p.avg_conf * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="history-table">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Time</th>
              <th>Pattern</th>
              <th>Direction</th>
              <th>Confidence</th>
              <th>Score</th>
              <th>Session</th>
              <th>Regime</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {patternHistory.map((p) => (
              <tr
                key={p.pattern_id + p.timestamp}
                className="history-row"
              >
                <td>
                  <button
                    className="expand-btn"
                    onClick={() =>
                      setExpandedRow(
                        expandedRow === p.pattern_id + p.timestamp
                          ? null
                          : p.pattern_id + p.timestamp
                      )
                    }
                  >
                    {expandedRow === p.pattern_id + p.timestamp ? (
                      <ChevronUp size={12} />
                    ) : (
                      <ChevronDown size={12} />
                    )}
                  </button>
                </td>
                <td>{formatTimestamp(p.timestamp)}</td>
                <td>{p.name.replaceAll('_', ' ')}</td>
                <td>
                  <span className={`dir-badge ${p.direction}`}>
                    {p.direction === 'bullish' ? (
                      <ArrowUpRight size={10} />
                    ) : p.direction === 'bearish' ? (
                      <ArrowDownRight size={10} />
                    ) : (
                      <Minus size={10} />
                    )}
                    {p.direction}
                  </span>
                </td>
                <td>{(p.confidence * 100).toFixed(0)}%</td>
                <td>{(p.score * 100).toFixed(0)}%</td>
                <td>{p.session ?? '--'}</td>
                <td>{p.regime_phase ?? '--'}</td>
                <td>
                  <span
                    className={`status-badge ${p.completed ? 'completed' : 'active'}`}
                  >
                    {p.completed ? 'Completed' : 'Active'}
                  </span>
                </td>
              </tr>
            ))}
            {expandedRow &&
              patternHistory.map((p) => {
                const rowKey = p.pattern_id + p.timestamp
                if (rowKey !== expandedRow) return null
                return (
                  <tr key={rowKey + '-detail'} className="history-detail-row">
                    <td colSpan={9}>
                      <div className="detail-content">
                        <p>{p.description}</p>
                        <div className="detail-meta">
                          <span>
                            <Clock size={10} />
                            Candles: {p.candle_count}
                          </span>
                          <span>
                            <Target size={10} />
                            Symbol: {p.symbol}
                          </span>
                          <span>
                            <Layers size={10} />
                            TF: {p.timeframe}
                          </span>
                        </div>
                      </div>
                    </td>
                  </tr>
                )
              })}
          </tbody>
        </table>
        {patternHistory.length === 0 && (
          <p className="empty-state">No pattern history available</p>
        )}
      </div>
    </div>
  )
}

function RegimesTab({
  regimeDist,
  regimeHistory,
  expandedRow,
  setExpandedRow,
  onExport,
}: {
  regimeDist: RegimeDistribution | null
  regimeHistory: RegimeHistory[]
  expandedRow: string | null
  setExpandedRow: (id: string | null) => void
  onExport: (format: 'csv' | 'json') => void
}) {
  return (
    <div className="analytics-tab-content">
      <div className="analytics-tab-header">
        <h3>Regime History</h3>
        <div className="export-btns">
          <button className="export-btn" onClick={() => onExport('csv')}>
            <Download size={12} />
            CSV
          </button>
          <button className="export-btn" onClick={() => onExport('json')}>
            <Download size={12} />
            JSON
          </button>
        </div>
      </div>

      {regimeDist && Object.keys(regimeDist).length > 0 && (
        <div className="regime-bars">
          {Object.entries(regimeDist)
            .sort((a, b) => b[1].count - a[1].count)
            .map(([phase, data]) => (
              <div key={phase} className="regime-bar-item">
                <span className="rb-label">
                  {phase.replaceAll('_', ' ')}
                </span>
                <div className="rb-track">
                  <div
                    className="rb-fill"
                    style={{
                      width: `${(data.count / Math.max(...Object.values(regimeDist).map((d) => d.count))) * 100}%`,
                    }}
                  />
                </div>
                <span className="rb-count">{data.count}</span>
                <span className="rb-conf">
                  {(data.avg_confidence * 100).toFixed(0)}%
                </span>
              </div>
            ))}
        </div>
      )}

      <div className="history-table">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Time</th>
              <th>Phase</th>
              <th>Bias</th>
              <th>Confidence</th>
              <th>Range</th>
              <th>Width %</th>
              <th>Volume</th>
              <th>Efficiency</th>
            </tr>
          </thead>
          <tbody>
            {regimeHistory.map((r, i) => {
              const rowKey = `regime-${r.timestamp}-${i}`
              return (
                <>
                  <tr key={rowKey} className="history-row">
                    <td>
                      <button
                        className="expand-btn"
                        onClick={() =>
                          setExpandedRow(expandedRow === rowKey ? null : rowKey)
                        }
                      >
                        {expandedRow === rowKey ? (
                          <ChevronUp size={12} />
                        ) : (
                          <ChevronDown size={12} />
                        )}
                      </button>
                    </td>
                    <td>{formatTimestamp(r.timestamp)}</td>
                    <td>
                      <span className="phase-badge">
                        {r.phase.replaceAll('_', ' ')}
                      </span>
                    </td>
                    <td>
                      <span className={`dir-badge ${r.bias}`}>{r.bias}</span>
                    </td>
                    <td>{(r.confidence * 100).toFixed(0)}%</td>
                    <td>
                      {r.range_low != null && r.range_high != null
                        ? `${formatNumber(r.range_low)} - ${formatNumber(r.range_high)}`
                        : '--'}
                    </td>
                    <td>
                      {r.width_pct != null
                        ? `${(r.width_pct * 100).toFixed(1)}%`
                        : '--'}
                    </td>
                    <td>{r.volume_state ?? '--'}</td>
                    <td>
                      {r.efficiency_ratio != null
                        ? r.efficiency_ratio.toFixed(2)
                        : '--'}
                    </td>
                  </tr>
                  {expandedRow === rowKey && (
                    <tr
                      key={rowKey + '-detail'}
                      className="history-detail-row"
                    >
                      <td colSpan={9}>
                        <div className="detail-content">
                          {r.reason && <p>{r.reason}</p>}
                          <div className="detail-meta">
                            <span>
                              <Target size={10} />
                              ATR Compression:{' '}
                              {r.atr_compression?.toFixed(2) ?? '--'}
                            </span>
                            <span>
                              <Zap size={10} />
                              Symbol: {r.symbol}
                            </span>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
        {regimeHistory.length === 0 && (
          <p className="empty-state">No regime history available</p>
        )}
      </div>
    </div>
  )
}

function AiTab({
  aiAccuracy,
  aiDecisions,
  expandedRow,
  setExpandedRow,
  onExport,
}: {
  aiAccuracy: AiAccuracy | null
  aiDecisions: AiDecision[]
  expandedRow: string | null
  setExpandedRow: (id: string | null) => void
  onExport: (format: 'csv' | 'json') => void
}) {
  return (
    <div className="analytics-tab-content">
      <div className="analytics-tab-header">
        <h3>AI Decision History</h3>
        <div className="export-btns">
          <button className="export-btn" onClick={() => onExport('csv')}>
            <Download size={12} />
            CSV
          </button>
          <button className="export-btn" onClick={() => onExport('json')}>
            <Download size={12} />
            JSON
          </button>
        </div>
      </div>

      {aiAccuracy && (
        <div className="ai-summary-cards">
          <div className="ai-summary-card">
            <span className="asc-label">Total Decisions</span>
            <span className="asc-value">{aiAccuracy.total_decisions}</span>
          </div>
          <div className="ai-summary-card">
            <span className="asc-label">Avg Confidence</span>
            <span className="asc-value">
              {(aiAccuracy.avg_confidence * 100).toFixed(1)}%
            </span>
          </div>
          <div className="ai-summary-card">
            <span className="asc-label">Avg Setup Score</span>
            <span className="asc-value">
              {(aiAccuracy.avg_setup_score * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      <div className="history-table">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Time</th>
              <th>Grade</th>
              <th>Direction</th>
              <th>Confidence</th>
              <th>Setup Score</th>
              <th>Entry</th>
              <th>Stop Loss</th>
              <th>Take Profit</th>
              <th>R:R</th>
            </tr>
          </thead>
          <tbody>
            {aiDecisions.map((d, i) => {
              const rowKey = `ai-${d.timestamp}-${i}`
              return (
                <>
                  <tr key={rowKey} className="history-row">
                    <td>
                      <button
                        className="expand-btn"
                        onClick={() =>
                          setExpandedRow(
                            expandedRow === rowKey ? null : rowKey
                          )
                        }
                      >
                        {expandedRow === rowKey ? (
                          <ChevronUp size={12} />
                        ) : (
                          <ChevronDown size={12} />
                        )}
                      </button>
                    </td>
                    <td>{formatTimestamp(d.timestamp)}</td>
                    <td>
                      <span
                        className="grade-badge"
                        style={{
                          color: GRADE_COLORS[d.grade ?? ''] ?? '#888',
                        }}
                      >
                        {d.grade ?? '--'}
                      </span>
                    </td>
                    <td>
                      <span className={`dir-badge ${d.direction ?? 'neutral'}`}>
                        {d.direction === 'bullish' ? (
                          <ArrowUpRight size={10} />
                        ) : d.direction === 'bearish' ? (
                          <ArrowDownRight size={10} />
                        ) : (
                          <Minus size={10} />
                        )}
                        {d.direction ?? '--'}
                      </span>
                    </td>
                    <td>
                      {d.confidence != null
                        ? `${(d.confidence * 100).toFixed(0)}%`
                        : '--'}
                    </td>
                    <td>
                      {d.setup_score != null
                        ? `${(d.setup_score * 100).toFixed(0)}%`
                        : '--'}
                    </td>
                    <td>
                      {d.entry != null ? formatNumber(d.entry) : '--'}
                    </td>
                    <td>
                      {d.stop_loss != null ? formatNumber(d.stop_loss) : '--'}
                    </td>
                    <td>
                      {d.take_profit != null
                        ? formatNumber(d.take_profit)
                        : '--'}
                    </td>
                    <td>
                      {d.risk_reward != null
                        ? `${d.risk_reward.toFixed(1)}x`
                        : '--'}
                    </td>
                  </tr>
                  {expandedRow === rowKey && (
                    <tr
                      key={rowKey + '-detail'}
                      className="history-detail-row"
                    >
                      <td colSpan={10}>
                        <div className="detail-content">
                          {d.summary && (
                            <p className="ai-summary">{d.summary}</p>
                          )}
                          <div className="detail-meta">
                            <span>
                              <Cpu size={10} />
                              Model:{' '}
                              {d.model ?? d.provider ?? '--'}
                            </span>
                            {d.option_symbol && (
                              <span>
                                <Target size={10} />
                                Option: {d.option_symbol}
                              </span>
                            )}
                            {d.momentum_score != null && (
                              <span>
                                <Zap size={10} />
                                Momentum:{' '}
                                {(d.momentum_score * 100).toFixed(0)}%
                              </span>
                            )}
                          </div>
                          {d.confirmations.length > 0 && (
                            <div className="ai-chips">
                              <span className="chip-label">
                                Confirmations:
                              </span>
                              {d.confirmations.map((c, j) => (
                                <span key={j} className="chip confirmation">
                                  {c}
                                </span>
                              ))}
                            </div>
                          )}
                          {d.blockers.length > 0 && (
                            <div className="ai-chips">
                              <span className="chip-label">Blockers:</span>
                              {d.blockers.map((b, j) => (
                                <span key={j} className="chip blocker">
                                  {b}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
          </tbody>
        </table>
        {aiDecisions.length === 0 && (
          <p className="empty-state">No AI decisions recorded</p>
        )}
      </div>
    </div>
  )
}

function PerformanceTab({
  dailyPerf,
  onExport,
}: {
  dailyPerf: DailyPerformance[]
  onExport: (format: 'csv' | 'json') => void
}) {
  const totalPnl = dailyPerf.reduce((s, d) => s + d.paper_pnl, 0)
  const validWinRates = dailyPerf.filter((d) => d.paper_win_rate != null)
  const avgWinRate =
    validWinRates.reduce((s, d) => s + (d.paper_win_rate ?? 0), 0) /
    Math.max(1, validWinRates.length)
  const totalTrades = dailyPerf.reduce((s, d) => s + d.total_paper_trades, 0)
  const totalWins = dailyPerf.reduce((s, d) => s + d.paper_wins, 0)

  return (
    <div className="analytics-tab-content">
      <div className="analytics-tab-header">
        <h3>Daily Performance</h3>
        <div className="export-btns">
          <button className="export-btn" onClick={() => onExport('csv')}>
            <Download size={12} />
            CSV
          </button>
          <button className="export-btn" onClick={() => onExport('json')}>
            <Download size={12} />
            JSON
          </button>
        </div>
      </div>

      <div className="perf-summary">
        <div className="perf-stat">
          <span className="ps-label">Total P&amp;L</span>
          <span
            className={`ps-value ${totalPnl >= 0 ? 'positive' : 'negative'}`}
          >
            ${totalPnl.toFixed(2)}
          </span>
        </div>
        <div className="perf-stat">
          <span className="ps-label">Total Trades</span>
          <span className="ps-value">{totalTrades}</span>
        </div>
        <div className="perf-stat">
          <span className="ps-label">Wins</span>
          <span className="ps-value positive">{totalWins}</span>
        </div>
        <div className="perf-stat">
          <span className="ps-label">Avg Win Rate</span>
          <span className="ps-value">
            {(avgWinRate * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="history-table">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Signals</th>
              <th>Bull/Bear</th>
              <th>Trades</th>
              <th>W/L</th>
              <th>Win Rate</th>
              <th>P&amp;L</th>
              <th>Avg RSI</th>
              <th>Avg ATR</th>
              <th>Max DD</th>
            </tr>
          </thead>
          <tbody>
            {dailyPerf.map((d) => (
              <tr key={d.date} className="history-row">
                <td>
                  <span className="date-cell">
                    <Calendar size={10} />
                    {d.date}
                  </span>
                </td>
                <td>{d.total_signals}</td>
                <td>
                  <span style={{ color: DIRECTION_COLORS.bullish }}>
                    {d.bullish_signals}
                  </span>
                  {' / '}
                  <span style={{ color: DIRECTION_COLORS.bearish }}>
                    {d.bearish_signals}
                  </span>
                </td>
                <td>{d.total_paper_trades}</td>
                <td>
                  <span className="win-count">{d.paper_wins}</span>
                  {' / '}
                  <span className="loss-count">{d.paper_losses}</span>
                </td>
                <td>
                  {d.paper_win_rate != null
                    ? `${(d.paper_win_rate * 100).toFixed(1)}%`
                    : '--'}
                </td>
                <td>
                  <span
                    className={`pnl-cell ${d.paper_pnl >= 0 ? 'positive' : 'negative'}`}
                  >
                    ${d.paper_pnl.toFixed(2)}
                  </span>
                </td>
                <td>
                  {d.avg_rsi != null ? d.avg_rsi.toFixed(1) : '--'}
                </td>
                <td>
                  {d.avg_atr != null ? d.avg_atr.toFixed(2) : '--'}
                </td>
                <td>
                  {d.max_drawdown_pct != null
                    ? `${d.max_drawdown_pct.toFixed(2)}%`
                    : '--'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {dailyPerf.length === 0 && (
          <p className="empty-state">No performance data available</p>
        )}
      </div>
    </div>
  )
}

function StorageTab({
  storageStats,
  onCleanup,
  onExport,
}: {
  storageStats: StorageStats | null
  onCleanup: () => void
  onExport: (format: 'csv' | 'json', endpoint: string, name: string) => void
}) {
  if (!storageStats)
    return (
      <p className="empty-state">No storage data available</p>
    )

  const tables = Object.entries(storageStats)
    .filter(
      ([key]) =>
        !key.startsWith('oldest') &&
        !key.startsWith('newest') &&
        key !== 'candle_date_range_days'
    )
    .map(([table, count]) => ({ table, count: count as number }))

  const candleRange = storageStats.candle_date_range_days
    ? `${storageStats.candle_date_range_days} days`
    : 'No data'

  return (
    <div className="analytics-tab-content">
      <div className="analytics-tab-header">
        <h3>Storage Management</h3>
        <button className="cleanup-btn" onClick={onCleanup}>
          <RefreshCw size={12} />
          Run Cleanup
        </button>
      </div>

      <div className="storage-info">
        <div className="storage-stat">
          <span className="ss-label">Candle Date Range</span>
          <span className="ss-value">{candleRange}</span>
        </div>
      </div>

      <div className="storage-table">
        <table>
          <thead>
            <tr>
              <th>Table</th>
              <th>Records</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tables.map(({ table, count }) => (
              <tr key={table} className="storage-row">
                <td>{table.replaceAll('_', ' ')}</td>
                <td>{formatNumber(count)}</td>
                <td>
                  <div className="storage-actions">
                    <button
                      className="storage-action-btn"
                      onClick={() =>
                        onExport(
                          'csv',
                          `/history/${table.replace('_history', '').replace('market_snapshots', 'snapshots').replace('candle_archive', 'candles').replace('ai_decisions_history', 'ai').replace('pattern_history', 'patterns').replace('regime_history', 'regimes').replace('metrics_history', 'metrics').replace('liquidity_history', 'liquidity').replace('orderbook_history', 'orderbook').replace('performance_daily', 'performance')}`,
                          table
                        )
                      }
                    >
                      <Download size={10} />
                      CSV
                    </button>
                    <button
                      className="storage-action-btn"
                      onClick={() =>
                        onExport(
                          'json',
                          `/history/${table.replace('_history', '').replace('market_snapshots', 'snapshots').replace('candle_archive', 'candles').replace('ai_decisions_history', 'ai').replace('pattern_history', 'patterns').replace('regime_history', 'regimes').replace('metrics_history', 'metrics').replace('liquidity_history', 'liquidity').replace('orderbook_history', 'orderbook').replace('performance_daily', 'performance')}`,
                          table
                        )
                      }
                    >
                      <Download size={10} />
                      JSON
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
