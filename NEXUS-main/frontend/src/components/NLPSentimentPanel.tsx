import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  MessageSquare,
  TrendingUp,
  TrendingDown,
  Minus,
  BarChart3,
  Brain,
} from 'lucide-react'

interface NLPSentiment {
  aggregate_score: number
  aggregate_label: string
  confidence: number
  source_count: number
  finbert_score: number | null
  vader_score: number | null
  fear_greed_index: number | null
  weighted_score: number
  description: string
  timestamp: number
}

export function NLPSentimentPanel() {
  const [sentiment, setSentiment] = useState<NLPSentiment | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchSentiment = useCallback(async () => {
    try {
      const res = await fetch('/nlp/sentiment')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setSentiment(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSentiment()
    const interval = setInterval(fetchSentiment, 120000)
    return () => clearInterval(interval)
  }, [fetchSentiment])

  const getSentimentColor = (score: number) => {
    if (score > 0.3) return '#22c55e'
    if (score > 0.1) return '#84cc16'
    if (score < -0.3) return '#ef4444'
    if (score < -0.1) return '#f97316'
    return '#f59e0b'
  }

  const getSentimentIcon = (label: string) => {
    switch (label) {
      case 'bullish': case 'positive': return <TrendingUp size={14} />
      case 'bearish': case 'negative': return <TrendingDown size={14} />
      default: return <Minus size={14} />
    }
  }

  const getFgiColor = (index: number) => {
    if (index > 75) return '#22c55e'
    if (index > 55) return '#84cc16'
    if (index > 45) return '#f59e0b'
    if (index > 25) return '#f97316'
    return '#ef4444'
  }

  if (loading && !sentiment) {
    return (
      <div className="nlp-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading sentiment data...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="nlp-panel">
      <div className="dsp-header">
        <h2><MessageSquare size={14} /> NLP Sentiment</h2>
        <div className="dsp-controls">
          <button className="dsp-btn" onClick={fetchSentiment} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchSentiment}>Retry</button>
        </div>
      )}

      {sentiment && (
        <>
          <div className="dsp-summary">
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Score</span>
                <span className="dsp-stat-value" style={{ color: getSentimentColor(sentiment.aggregate_score) }}>
                  {sentiment.aggregate_score.toFixed(4)}
                </span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Label</span>
                <span className="dsp-stat-value" style={{ color: getSentimentColor(sentiment.aggregate_score) }}>
                  {getSentimentIcon(sentiment.aggregate_label)}
                  {sentiment.aggregate_label.toUpperCase()}
                </span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Confidence</span>
                <span className="dsp-stat-value">{(sentiment.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Sources</span>
                <span className="dsp-stat-value">{sentiment.source_count}</span>
              </div>
            </div>
            {sentiment.fear_greed_index !== null && (
              <div className="dsp-stat">
                <div className="dsp-stat-info">
                  <span className="dsp-stat-label">Fear & Greed</span>
                  <span className="dsp-stat-value" style={{ color: getFgiColor(sentiment.fear_greed_index) }}>
                    {sentiment.fear_greed_index}
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="dsp-section">
            <h3>Model Scores</h3>
            <div className="sentiment-sources">
              {sentiment.finbert_score !== null && (
                <div className="sentiment-source-row">
                  <div className="sentiment-source-header">
                    <Brain size={14} />
                    <span className="sentiment-source-name">FinBERT</span>
                    <span className="sentiment-source-label" style={{ color: getSentimentColor(sentiment.finbert_score) }}>
                      {sentiment.finbert_score > 0 ? 'Positive' : sentiment.finbert_score < 0 ? 'Negative' : 'Neutral'}
                    </span>
                  </div>
                  <div className="regime-prob-bar-bg">
                    <div className="regime-prob-bar" style={{ width: `${Math.abs(sentiment.finbert_score * 100).toFixed(1)}%`, backgroundColor: getSentimentColor(sentiment.finbert_score) }} />
                  </div>
                  <div className="sentiment-source-footer">
                    <span>Score: {sentiment.finbert_score.toFixed(4)}</span>
                  </div>
                </div>
              )}
              {sentiment.vader_score !== null && (
                <div className="sentiment-source-row">
                  <div className="sentiment-source-header">
                    <MessageSquare size={14} />
                    <span className="sentiment-source-name">VADER</span>
                    <span className="sentiment-source-label" style={{ color: getSentimentColor(sentiment.vader_score) }}>
                      {sentiment.vader_score > 0 ? 'Positive' : sentiment.vader_score < 0 ? 'Negative' : 'Neutral'}
                    </span>
                  </div>
                  <div className="regime-prob-bar-bg">
                    <div className="regime-prob-bar" style={{ width: `${Math.abs(sentiment.vader_score * 100).toFixed(1)}%`, backgroundColor: getSentimentColor(sentiment.vader_score) }} />
                  </div>
                  <div className="sentiment-source-footer">
                    <span>Score: {sentiment.vader_score.toFixed(4)}</span>
                  </div>
                </div>
              )}
              <div className="sentiment-source-row">
                <div className="sentiment-source-header">
                  <BarChart3 size={14} />
                  <span className="sentiment-source-name">Weighted</span>
                  <span className="sentiment-source-label" style={{ color: getSentimentColor(sentiment.weighted_score) }}>
                    {sentiment.weighted_score > 0 ? 'Positive' : sentiment.weighted_score < 0 ? 'Negative' : 'Neutral'}
                  </span>
                </div>
                <div className="regime-prob-bar-bg">
                  <div className="regime-prob-bar" style={{ width: `${Math.abs(sentiment.weighted_score * 100).toFixed(1)}%`, backgroundColor: getSentimentColor(sentiment.weighted_score) }} />
                </div>
                <div className="sentiment-source-footer">
                  <span>Score: {sentiment.weighted_score.toFixed(4)}</span>
                </div>
              </div>
            </div>
          </div>

          {sentiment.description && (
            <div className="dsp-section">
              <h3>Description</h3>
              <p className="sentiment-description" style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {sentiment.description}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
