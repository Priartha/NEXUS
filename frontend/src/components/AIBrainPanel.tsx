import { useMemo } from 'react'
import { Brain, TrendingUp, TrendingDown, Activity, Target, Database, BarChart3, GitBranch, Layers } from 'lucide-react'
import type { AiAgentStatus } from '../types/market'

interface AIBrainPanelProps {
  aiIntelligence?: AiAgentStatus | null
}

export function AIBrainPanel({ aiIntelligence }: AIBrainPanelProps) {
  const data = useMemo(() => {
    if (!aiIntelligence) return null

    const decisions = aiIntelligence.decisions ?? 0
    const accuracy = aiIntelligence.accuracy ?? 0
    const memory = aiIntelligence.memory_stats
    const patternsLearned = aiIntelligence.patterns_learned ?? 0
    const hoursKnown = aiIntelligence.market_hours_knowledge ?? 0

    return {
      decisions,
      accuracy,
      memoryStats: memory ? {
        totalTrades: memory.total_trades ?? 0,
        winningTrades: memory.winning_trades ?? 0,
        winRate: memory.win_rate ?? 0,
        totalPnl: memory.total_pnl ?? 0,
        avgPnl: memory.avg_pnl_per_trade ?? 0,
        patternsLearned: memory.patterns_learned ?? 0,
        hoursLearned: memory.market_hours_learned ?? 0,
      } : null,
      patternsLearned,
      hoursKnown,
    }
  }, [aiIntelligence])

  if (!data) {
    return (
      <div className="inst-panel">
        <div className="inst-empty">Waiting for AI brain data...</div>
      </div>
    )
  }

  return (
    <div className="inst-panel">
      {/* Agent Overview */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <Brain size={14} /> Self-Aware Agent Status
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">Total Decisions</span>
            <span className="inst-value">{data.decisions}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Accuracy</span>
            <span className="inst-value" style={{ color: data.accuracy > 0.55 ? '#22c55e' : data.accuracy > 0.4 ? '#f59e0b' : '#ef4444' }}>
              {(data.accuracy * 100).toFixed(1)}%
            </span>
            <div className="inst-bar-container">
              <div className="inst-bar" style={{ width: `${data.accuracy * 100}%`, background: data.accuracy > 0.55 ? '#22c55e' : '#f59e0b' }} />
            </div>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Patterns Memorized</span>
            <span className="inst-value">{data.patternsLearned}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Market Hours Known</span>
            <span className="inst-value">{data.hoursKnown}</span>
          </div>
        </div>
      </div>

      {/* Memory Stats */}
      {data.memoryStats && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Database size={14} /> Memory Statistics
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Total Trades</span>
              <span className="inst-value">{data.memoryStats.totalTrades}</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Win Rate</span>
              <span className="inst-value" style={{ color: data.memoryStats.winRate > 0.55 ? '#22c55e' : '#f59e0b' }}>
                {(data.memoryStats.winRate * 100).toFixed(1)}%
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Winning Trades</span>
              <span className="inst-value" style={{ color: '#22c55e' }}>{data.memoryStats.winningTrades}</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Total PnL</span>
              <span className="inst-value" style={{ color: data.memoryStats.totalPnl >= 0 ? '#22c55e' : '#ef4444' }}>
                {data.memoryStats.totalPnl >= 0 ? '+' : ''}{data.memoryStats.totalPnl.toFixed(2)}
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Avg PnL / Trade</span>
              <span className="inst-value" style={{ color: data.memoryStats.avgPnl >= 0 ? '#22c55e' : '#ef4444' }}>
                {data.memoryStats.avgPnl >= 0 ? '+' : ''}{data.memoryStats.avgPnl.toFixed(4)}
              </span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Patterns Learned</span>
              <span className="inst-value">{data.memoryStats.patternsLearned}</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Hours Learned</span>
              <span className="inst-value">{data.memoryStats.hoursLearned}</span>
            </div>
          </div>
        </div>
      )}

      {/* Learning Summary */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <Layers size={14} /> Learning Summary
        </h3>
        <div className="inst-grid">
          <div className="inst-metric" style={{ gridColumn: '1 / -1' }}>
            <span className="inst-sub">
              Agent has made <strong>{data.decisions}</strong> decisions with{' '}
              <strong style={{ color: data.accuracy > 0.55 ? '#22c55e' : '#f59e0b' }}>
                {(data.accuracy * 100).toFixed(1)}% accuracy
              </strong>.
              It has memorized <strong>{data.patternsLearned}</strong> price-action patterns
              and logged <strong>{data.hoursKnown}</strong> market hour behaviors.
              {data.memoryStats && (
                <> Memory reflects <strong>{data.memoryStats.totalTrades}</strong> trades
                with a <strong style={{ color: data.memoryStats.winRate > 0.55 ? '#22c55e' : '#f59e0b' }}>
                  {(data.memoryStats.winRate * 100).toFixed(1)}% win rate</strong>.</>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
