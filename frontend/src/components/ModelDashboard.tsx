import { useEffect, useState, useCallback } from 'react'
import {
  BrainCircuit,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  BarChart3,
  Clock,
  Target,
  Zap,
} from 'lucide-react'

interface ModelGradeStats {
  grade: string
  count: number
  avg_confidence: number
  win_rate: number | null
  avg_pnl: number | null
}

interface ModelPerformance {
  total_decisions: number
  accuracy: number | null
  avg_confidence: number
  grade_distribution: ModelGradeStats[]
  last_24h_decisions: number
  last_24h_accuracy: number | null
  drift_score: number | null
  degradation_detected: boolean
  top_performing_grade: string | null
  worst_performing_grade: string | null
  timestamp: number
}

interface ModelTrendPoint {
  date: string
  decisions: number
  accuracy: number | null
  avg_confidence: number
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '--'
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toFixed(2)
}

const GRADE_COLORS: Record<string, string> = {
  A_PLUS: '#1fe3a3',
  A: '#1fe3a3',
  B_PLUS: '#8ab4f8',
  B: '#8ab4f8',
  C: '#f59f43',
  NO_TRADE: '#666',
}

export function ModelDashboard() {
  const [performance, setPerformance] = useState<ModelPerformance | null>(null)
  const [trend, setTrend] = useState<ModelTrendPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [daysFilter, setDaysFilter] = useState(7)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [perfRes, trendRes] = await Promise.all([
        fetch('/model/performance'),
        fetch(`/model/trend?days=${daysFilter}`),
      ])

      if (perfRes.ok) {
        const contentType = perfRes.headers.get('content-type')
        if (contentType && contentType.includes('application/json')) {
          setPerformance(await perfRes.json())
        }
      }

      if (trendRes.ok) {
        const contentType = trendRes.headers.get('content-type')
        if (contentType && contentType.includes('application/json')) {
          setTrend(await trendRes.json())
        }
      }
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [daysFilter])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000)
    return () => clearInterval(interval)
  }, [fetchData])

  if (loading && !performance) {
    return (
      <div className="model-dashboard">
        <div className="md-loading">
          <RefreshCw size={16} className="md-loading-spinner" />
          <span>Loading model performance...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="model-dashboard">
      {/* Header */}
      <div className="md-header">
        <h2>
          <BrainCircuit size={14} />
          Model Accuracy Dashboard
        </h2>
        <div className="md-controls">
          <select
            value={daysFilter}
            onChange={(e) => setDaysFilter(Number(e.target.value))}
            className="md-select"
          >
            <option value={1}>24h</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
          <button className="md-btn" onClick={fetchData} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="md-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="md-btn" onClick={fetchData}>Retry</button>
        </div>
      )}

      {/* Drift Warning */}
      {performance?.degradation_detected && (
        <div className="md-drift-warning">
          <AlertTriangle size={14} />
          <span>Model degradation detected — consider retraining</span>
        </div>
      )}

      {/* Summary Stats */}
      {performance && (
        <div className="md-summary">
          <div className="md-stat-card">
            <div className="md-stat-icon">
              <BarChart3 size={16} />
            </div>
            <div className="md-stat-info">
              <span className="md-stat-label">Total Decisions</span>
              <span className="md-stat-value">{performance.total_decisions}</span>
            </div>
          </div>
          <div className="md-stat-card">
            <div className="md-stat-icon">
              <Target size={16} />
            </div>
            <div className="md-stat-info">
              <span className="md-stat-label">Accuracy</span>
              <span className={`md-stat-value ${performance.accuracy != null && performance.accuracy >= 0.55 ? 'positive' : performance.accuracy != null && performance.accuracy < 0.45 ? 'negative' : ''}`}>
                {performance.accuracy != null ? `${(performance.accuracy * 100).toFixed(1)}%` : '--'}
              </span>
            </div>
          </div>
          <div className="md-stat-card">
            <div className="md-stat-icon">
              <Zap size={16} />
            </div>
            <div className="md-stat-info">
              <span className="md-stat-label">Avg Confidence</span>
              <span className="md-stat-value">{(performance.avg_confidence * 100).toFixed(1)}%</span>
            </div>
          </div>
          <div className="md-stat-card">
            <div className="md-stat-icon">
              <Clock size={16} />
            </div>
            <div className="md-stat-info">
              <span className="md-stat-label">24h Decisions</span>
              <span className="md-stat-value">{performance.last_24h_decisions}</span>
            </div>
          </div>
          {performance.drift_score != null && (
            <div className="md-stat-card">
              <div className="md-stat-icon" style={{ color: performance.drift_score > 0.3 ? '#ff5b6b' : '#1fe3a3' }}>
                <TrendingDown size={16} />
              </div>
              <div className="md-stat-info">
                <span className="md-stat-label">Drift Score</span>
                <span className={`md-stat-value ${performance.drift_score > 0.3 ? 'negative' : 'positive'}`}>
                  {(performance.drift_score * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Grade Distribution */}
      {performance && performance.grade_distribution.length > 0 && (
        <div className="md-section">
          <h3>Grade Distribution</h3>
          <div className="md-grade-list">
            {performance.grade_distribution.map((g) => (
              <div key={g.grade} className="md-grade-card">
                <div className="md-grade-header">
                  <span
                    className="md-grade-badge"
                    style={{ color: GRADE_COLORS[g.grade] ?? '#888' }}
                  >
                    {g.grade}
                  </span>
                  <span className="md-grade-count">{g.count}</span>
                </div>
                <div className="md-grade-details">
                  <div className="md-grade-row">
                    <span className="md-grade-label">Avg Conf</span>
                    <span className="md-grade-value">{(g.avg_confidence * 100).toFixed(0)}%</span>
                  </div>
                  {g.win_rate != null && (
                    <div className="md-grade-row">
                      <span className="md-grade-label">Win Rate</span>
                      <span className={`md-grade-value ${g.win_rate >= 0.5 ? 'positive' : 'negative'}`}>
                        {(g.win_rate * 100).toFixed(0)}%
                      </span>
                    </div>
                  )}
                  {g.avg_pnl != null && (
                    <div className="md-grade-row">
                      <span className="md-grade-label">Avg P&L</span>
                      <span className={`md-grade-value ${g.avg_pnl >= 0 ? 'positive' : 'negative'}`}>
                        ${g.avg_pnl.toFixed(2)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Trend Chart (simple bar visualization) */}
      {trend.length > 0 && (
        <div className="md-section">
          <h3>Performance Trend</h3>
          <div className="md-trend-chart">
            {trend.map((point, i) => {
              const maxAcc = Math.max(...trend.map((p) => p.accuracy ?? 0), 0.01)
              const accHeight = point.accuracy != null ? (point.accuracy / maxAcc) * 100 : 0
              return (
                <div key={i} className="md-trend-bar">
                  <div
                    className="md-trend-fill"
                    style={{
                      height: `${accHeight}%`,
                      backgroundColor: point.accuracy != null && point.accuracy >= 0.55 ? '#1fe3a3' : '#ff5b6b',
                    }}
                  />
                  <span className="md-trend-date">{point.date}</span>
                  <span className="md-trend-value">
                    {point.accuracy != null ? `${(point.accuracy * 100).toFixed(0)}%` : '--'}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Best/Worst Grades */}
      {performance && (performance.top_performing_grade || performance.worst_performing_grade) && (
        <div className="md-section">
          <h3>Performance Insights</h3>
          <div className="md-insights">
            {performance.top_performing_grade && (
              <div className="md-insight positive">
                <TrendingUp size={13} />
                <span>Best performing: <strong>{performance.top_performing_grade}</strong></span>
              </div>
            )}
            {performance.worst_performing_grade && (
              <div className="md-insight negative">
                <TrendingDown size={13} />
                <span>Worst performing: <strong>{performance.worst_performing_grade}</strong></span>
              </div>
            )}
            {performance.last_24h_accuracy != null && (
              <div className="md-insight">
                <Clock size={13} />
                <span>24h accuracy: <strong>{(performance.last_24h_accuracy * 100).toFixed(1)}%</strong></span>
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !performance && (
        <div className="md-empty">
          <BrainCircuit size={24} />
          <p>No model performance data available</p>
          <p className="md-empty-hint">Model tracking will begin after decisions are recorded</p>
        </div>
      )}
    </div>
  )
}
