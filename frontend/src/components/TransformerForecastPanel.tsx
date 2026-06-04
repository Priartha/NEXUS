import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Minus,
  BarChart3,
  Clock,
} from 'lucide-react'

interface ForecastHorizon {
  horizon: string
  horizon_bars: number
  predicted_direction: string
  predicted_return_pct: number
  confidence: number
  entry_price: number
  target_price: number
  stop_price: number
  description?: string
}

interface TransformerForecast {
  current_price: number
  model_ready: boolean
  horizons: ForecastHorizon[]
}

export function TransformerForecastPanel() {
  const [forecast, setForecast] = useState<TransformerForecast | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchForecast = useCallback(async () => {
    try {
      const res = await fetch('/transformer/forecast?candles=100')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setForecast(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchForecast()
    const interval = setInterval(fetchForecast, 60000)
    return () => clearInterval(interval)
  }, [fetchForecast])

  const getDirectionColor = (dir: string) => {
    switch (dir) {
      case 'up': case 'bullish': return '#22c55e'
      case 'down': case 'bearish': return '#ef4444'
      default: return '#f59e0b'
    }
  }

  const getDirectionIcon = (dir: string) => {
    switch (dir) {
      case 'up': case 'bullish': return <TrendingUp size={14} />
      case 'down': case 'bearish': return <TrendingDown size={14} />
      default: return <Minus size={14} />
    }
  }

  if (loading && !forecast) {
    return (
      <div className="forecast-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading forecast data...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="forecast-panel">
      <div className="dsp-header">
        <h2><BarChart3 size={14} /> Transformer Forecast</h2>
        <div className="dsp-controls">
          <button className="dsp-btn" onClick={fetchForecast} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchForecast}>Retry</button>
        </div>
      )}

      {forecast && (
        <>
          <div className="dsp-summary">
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Current Price</span>
                <span className="dsp-stat-value">${forecast.current_price.toFixed(2)}</span>
              </div>
            </div>
            <div className="dsp-stat">
              <div className="dsp-stat-info">
                <span className="dsp-stat-label">Model Ready</span>
                <span className={`dsp-stat-value ${forecast.model_ready ? 'positive' : 'negative'}`}>
                  {forecast.model_ready ? 'Yes' : 'No'}
                </span>
              </div>
            </div>
          </div>

          <div className="dsp-section">
            <h3>Price Forecasts</h3>
            <div className="forecast-horizons">
              {forecast.horizons.map((h, i) => {
                const color = getDirectionColor(h.predicted_direction)
                const pct = h.predicted_return_pct
                return (
                  <div key={i} className="forecast-card" style={{ borderLeftColor: color }}>
                    <div className="forecast-card-header">
                      <Clock size={12} />
                      <span className="forecast-horizon-name">{h.horizon}</span>
                      <span className="forecast-direction" style={{ color }}>
                        {getDirectionIcon(h.predicted_direction)}
                        {h.predicted_direction.toUpperCase()}
                      </span>
                    </div>
                    <div className="forecast-card-price">
                      ${h.target_price.toFixed(2)}
                    </div>
                    <div className="forecast-card-details">
                      <span className={`forecast-change ${pct >= 0 ? 'positive' : 'negative'}`}>
                        {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                      </span>
                      <span className="forecast-confidence">
                        Confidence: {(h.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="forecast-card-stops">
                      <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                        Stop: ${h.stop_price.toFixed(2)}
                      </span>
                      <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                        Horizon: {h.horizon_bars} bars
                      </span>
                    </div>
                    <div className="regime-prob-bar-bg">
                      <div
                        className="regime-prob-bar"
                        style={{
                          width: `${(h.confidence * 100).toFixed(0)}%`,
                          backgroundColor: color,
                          opacity: 0.5,
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}

      {!loading && !forecast && (
        <div className="dsp-empty">
          <BarChart3 size={24} />
          <p>No forecast data available</p>
        </div>
      )}
    </div>
  )
}
