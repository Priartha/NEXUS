import { useMemo, useEffect, useState } from 'react'
import { 
  Brain, 
  Cpu, 
  TrendingUp, 
  Clock, 
  Target, 
  Award,
  BarChart2,
  Zap,
  Eye,
  Sparkles,
  Database,
  Layers,
  RefreshCw,
} from 'lucide-react'
import type { AIIntelligence } from '../types/market'

interface AIBrainPanelProps {
  aiIntelligence?: AIIntelligence | null
}

export function AIBrainPanel({ aiIntelligence }: AIBrainPanelProps) {
  const [tick, setTick] = useState(0)
  
  // Refresh every 5 seconds to show live data
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 5000)
    return () => clearInterval(interval)
  }, [])

  const stats = aiIntelligence?.memory_stats || {
    total_trades: 0,
    winning_trades: 0,
    win_rate: 0,
    total_pnl: 0,
    avg_pnl_per_trade: 0,
    patterns_learned: 0,
    market_hours_learned: 0,
  }

  const winRatePct = (stats.win_rate || 0) * 100
  
  // Real-time market insights from live data
  const marketInsights = useMemo(() => {
    const hour = new Date().getHours()
    
    // Simulate learning from time - more hours = better understanding
    const hours_of_data = Math.max(1, stats.market_hours_learned || 1)
    const learning_bonus = Math.min(0.3, hours_of_data / 24 * 0.3)
    
    // Hour-based volatility patterns (learned behavior)
    const isHighVolatilityHour = [8, 9, 14, 15, 21, 22].includes(hour)
    const isAsianSession = hour >= 0 && hour < 8
    const isLondonSession = hour >= 8 && hour < 16
    const isNYSession = hour >= 13 && hour < 21
    
    return {
      hour,
      isHighVolatilityHour,
      isAsianSession,
      isLondonSession,
      isNYSession,
      learning_bonus,
    }
  }, [tick, stats.market_hours_learned])

  const learningProgress = useMemo(() => {
    const patterns = stats.patterns_learned || 0
    const hours = stats.market_hours_learned || 1
    
    // Progress towards mastery
    const patternProgress = Math.min(100, (patterns / 50) * 100)
    const hourProgress = Math.min(100, (hours / 24) * 100)
    
    return {
      patterns: patternProgress,
      hours: hourProgress,
      overall: (patternProgress + hourProgress) / 2,
    }
  }, [stats.patterns_learned, stats.market_hours_learned])

  const aiConfidence = useMemo(() => {
    // Calculate confidence based on learning
    const baseConfidence = 0.45
    const learningBonus = Math.min(0.35, (stats.patterns_learned / 100) * 0.25)
    const accuracyBonus = (stats.win_rate || 0.5) * 0.25
    const timeBonus = marketInsights.learning_bonus
    
    return Math.min(0.95, baseConfidence + learningBonus + accuracyBonus + timeBonus)
  }, [stats.patterns_learned, stats.win_rate, marketInsights.learning_bonus])

  // If no data yet, show "learning" state
  const isLearning = stats.total_trades === 0 && stats.market_hours_learned === 0

  return (
    <div className="ai-brain-panel">
      {/* Header */}
      <div className="ai-brain-header">
        <div className="ai-brain-title">
          <Brain size={14} />
          <span>AI TRADING BRAIN</span>
          <span className={`ai-status-badge ${isLearning ? 'learning' : 'active'}`}>
            <Sparkles size={10} />
            {isLearning ? 'LEARNING' : 'ACTIVE'}
          </span>
        </div>
        <div className="ai-brain-subtitle">
          {isLearning 
            ? 'Analyzing market patterns • Building intelligence...'
            : 'Self-aware autonomous intelligence • Pure price action analysis'}
        </div>
      </div>

      {/* Core Intelligence */}
      <div className="ai-brain-core">
        <div className="ai-intelligence-card main">
          <div className="ai-card-header">
            <Cpu size={12} />
            <span>DECISION MAKER</span>
          </div>
          <div className="ai-confidence-ring">
            <svg viewBox="0 0 36 36" className="circular-chart">
              <path
                className="circle-bg"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <path
                className="circle"
                strokeDasharray={`${aiConfidence.toFixed(0)}, 100`}
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <text x="18" y="20.35" className="percentage">{(aiConfidence * 100).toFixed(0)}%</text>
            </svg>
          </div>
          <div className="ai-confidence-label">
            <span>AI Confidence</span>
            <strong>{isLearning ? 'Learning...' : `${(aiConfidence * 100).toFixed(0)}%`}</strong>
          </div>
        </div>

        <div className="ai-intelligence-card">
          <div className="ai-card-header">
            <Target size={12} />
            <span>TRADES</span>
          </div>
          <div className="ai-metric">
            <span className="ai-metric-value">{stats.total_trades}</span>
            <span className="ai-metric-label">Total</span>
          </div>
          <div className="ai-metric">
            <span className="ai-metric-value positive">{stats.winning_trades}</span>
            <span className="ai-metric-label">Wins</span>
          </div>
        </div>

        <div className="ai-intelligence-card">
          <div className="ai-card-header">
            <BarChart2 size={12} />
            <span>WIN RATE</span>
          </div>
          <div className="ai-metric large">
            <span className={`ai-metric-value ${winRatePct >= 50 ? 'positive' : 'negative'}`}>
              {winRatePct.toFixed(1)}%
            </span>
            <span className="ai-metric-label">Accuracy</span>
          </div>
        </div>

        <div className="ai-intelligence-card">
          <div className="ai-card-header">
            <Award size={12} />
            <span>P&L</span>
          </div>
          <div className="ai-metric large">
            <span className={`ai-metric-value ${stats.total_pnl >= 0 ? 'positive' : 'negative'}`}>
              {stats.total_pnl >= 0 ? '+' : ''}{stats.total_pnl.toFixed(2)}%
            </span>
            <span className="ai-metric-label">Total</span>
          </div>
        </div>
      </div>

      {/* Learning Progress */}
      <div className="ai-brain-section">
        <div className="ai-section-header">
          <Layers size={12} />
          <span>LEARNING PROGRESS</span>
        </div>
        <div className="ai-progress-grid">
          <div className="ai-progress-item">
            <div className="ai-progress-header">
              <Database size={10} />
              <span>Patterns Learned</span>
              <span className="ai-progress-value">{stats.patterns_learned}</span>
            </div>
            <div className="ai-progress-bar">
              <div className="ai-progress-fill" style={{ width: `${learningProgress.patterns}%` }} />
            </div>
          </div>
          <div className="ai-progress-item">
            <div className="ai-progress-header">
              <Clock size={10} />
              <span>Market Hours</span>
              <span className="ai-progress-value">{stats.market_hours_learned}h</span>
            </div>
            <div className="ai-progress-bar">
              <div className="ai-progress-fill" style={{ width: `${learningProgress.hours}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* Live Market Intelligence */}
      <div className="ai-brain-section">
        <div className="ai-section-header">
          <Eye size={12} />
          <span>LIVE MARKET INTELLIGENCE</span>
        </div>
        <div className="ai-market-grid">
          <div className="ai-market-item">
            <Clock size={10} />
            <span>Hour</span>
            <span className="ai-market-value">{marketInsights.hour}:00</span>
          </div>
          <div className="ai-market-item">
            <Zap size={10} />
            <span>Vol</span>
            <span className={`ai-market-value ${marketInsights.isHighVolatilityHour ? 'negative' : ''}`}>
              {marketInsights.isHighVolatilityHour ? 'HIGH' : 'NORMAL'}
            </span>
          </div>
          <div className="ai-market-item">
            <span>Session</span>
            <span className="ai-market-value">
              {marketInsights.isAsianSession ? 'ASIAN' : 
               marketInsights.isLondonSession ? 'LONDON' : 
               marketInsights.isNYSession ? 'NY' : 'MIXED'}
            </span>
          </div>
          <div className="ai-market-item">
            <TrendingUp size={10} />
            <span>Bias</span>
            <span className="ai-market-value">
              {stats.total_trades > 5 ? (stats.win_rate > 0.5 ? 'bullish' : stats.win_rate < 0.5 ? 'bearish' : 'neutral') : 'learning'}
            </span>
          </div>
        </div>
      </div>

      {/* Decision Factors */}
      <div className="ai-brain-section">
        <div className="ai-section-header">
          <Sparkles size={12} />
          <span>DECISION FACTORS</span>
        </div>
        <div className="ai-factors-list">
          <div className="ai-factor">
            <div className="ai-factor-icon">
              <TrendingUp size={10} />
            </div>
            <div className="ai-factor-info">
              <span className="ai-factor-name">Price Action</span>
              <span className="ai-factor-desc">OHLCV pattern analysis • EMA, RSI, MACD</span>
            </div>
            <div className="ai-factor-status active">ACTIVE</div>
          </div>
          <div className="ai-factor">
            <div className="ai-factor-icon">
              <BarChart2 size={10} />
            </div>
            <div className="ai-factor-info">
              <span className="ai-factor-name">Pattern Memory</span>
              <span className="ai-factor-desc">Bayesian pattern learning • {stats.patterns_learned} patterns</span>
            </div>
            <div className="ai-factor-status active">ACTIVE</div>
          </div>
          <div className="ai-factor">
            <div className="ai-factor-icon">
              <Clock size={10} />
            </div>
            <div className="ai-factor-info">
              <span className="ai-factor-name">Time Intelligence</span>
              <span className="ai-factor-desc">Hour/day behavior • {stats.market_hours_learned}h learned</span>
            </div>
            <div className="ai-factor-status active">ACTIVE</div>
          </div>
          <div className="ai-factor">
            <div className="ai-factor-icon">
              <Target size={10} />
            </div>
            <div className="ai-factor-info">
              <span className="ai-factor-name">Risk/Reward</span>
              <span className="ai-factor-desc">Dynamic position sizing • 2:1 minimum</span>
            </div>
            <div className="ai-factor-status active">ACTIVE</div>
          </div>
        </div>
      </div>

      {/* Memory Stats */}
      <div className="ai-brain-section">
        <div className="ai-section-header">
          <Database size={12} />
          <span>MEMORY STATS</span>
        </div>
        <div className="ai-stats-grid">
          <div className="ai-stat-item">
            <span className="ai-stat-label">Avg P&L/Trade</span>
            <span className={`ai-stat-value ${stats.avg_pnl_per_trade >= 0 ? 'positive' : 'negative'}`}>
              {stats.avg_pnl_per_trade >= 0 ? '+' : ''}{stats.avg_pnl_per_trade.toFixed(3)}%
            </span>
          </div>
          <div className="ai-stat-item">
            <span className="ai-stat-label">Decisions</span>
            <span className="ai-stat-value">{aiIntelligence?.decisions || 0}</span>
          </div>
          <div className="ai-stat-item">
            <span className="ai-stat-label">External APIs</span>
            <span className="ai-stat-value neutral">NONE</span>
          </div>
          <div className="ai-stat-item">
            <span className="ai-stat-label">Data Source</span>
            <span className="ai-stat-value">PRICE ONLY</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="ai-brain-footer">
        <div className="ai-footer-item">
          <RefreshCw size={10} />
          <span>Learning: {learningProgress.overall.toFixed(0)}%</span>
        </div>
        <div className="ai-footer-item">
          <Brain size={10} />
          <span>Mastery: {((aiIntelligence?.accuracy || 0.45) * 100).toFixed(0)}%</span>
        </div>
      </div>
    </div>
  )
}