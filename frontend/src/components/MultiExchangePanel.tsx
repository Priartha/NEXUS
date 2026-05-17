import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  ArrowUpRight,
  ArrowDownRight,
  Globe,
  TrendingUp,
  AlertTriangle,
  Clock,
} from 'lucide-react'

interface ExchangePrice {
  exchange: string
  symbol: string
  price: number
  volume_24h: number
  bid: number
  ask: number
  spread_pct: number
  timestamp: number
  status: 'ok' | 'error' | 'timeout'
  error?: string
}

interface MultiExchangeData {
  prices: ExchangePrice[]
  avg_price: number
  max_price: number
  min_price: number
  spread_range_pct: number
  best_exchange: string
  worst_exchange: string
  timestamp: number
}

function formatPrice(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '--'
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 1000) return 'just now'
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  return `${Math.floor(diff / 60000)}m ago`
}

const EXCHANGE_COLORS: Record<string, string> = {
  binance: '#f0b90b',
  coinbase: '#0052ff',
  kraken: '#684eea',
  okx: '#fff',
  bybit: '#f7a600',
}

export function MultiExchangePanel() {
  const [data, setData] = useState<MultiExchangeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/price/multi-exchange')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    if (!autoRefresh) return
    const interval = setInterval(fetchData, 15000)
    return () => clearInterval(interval)
  }, [fetchData, autoRefresh])

  if (loading && !data) {
    return (
      <div className="multi-exchange-panel">
        <div className="mep-loading">
          <RefreshCw size={16} className="mep-loading-spinner" />
          <span>Loading exchange prices...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="multi-exchange-panel">
      {/* Header */}
      <div className="mep-header">
        <h2>
          <Globe size={14} />
          Multi-Exchange Prices
        </h2>
        <div className="mep-controls">
          <button
            className={`mep-btn ${autoRefresh ? 'active' : ''}`}
            onClick={() => setAutoRefresh(!autoRefresh)}
            title={autoRefresh ? 'Auto-refresh ON' : 'Auto-refresh OFF'}
          >
            <Clock size={12} />
            {autoRefresh ? '15s' : 'Manual'}
          </button>
          <button className="mep-btn" onClick={fetchData} title="Refresh now">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mep-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="mep-btn" onClick={fetchData}>Retry</button>
        </div>
      )}

      {/* Summary Stats */}
      {data && (
        <div className="mep-summary">
          <div className="mep-stat">
            <span className="mep-stat-label">Average</span>
            <span className="mep-stat-value">${formatPrice(data.avg_price)}</span>
          </div>
          <div className="mep-stat">
            <span className="mep-stat-label">Spread Range</span>
            <span className={`mep-stat-value ${data.spread_range_pct > 0.5 ? 'warning' : 'ok'}`}>
              {data.spread_range_pct.toFixed(3)}%
            </span>
          </div>
          <div className="mep-stat">
            <span className="mep-stat-label">Best</span>
            <span className="mep-stat-value best">{data.best_exchange}</span>
          </div>
          <div className="mep-stat">
            <span className="mep-stat-label">Updated</span>
            <span className="mep-stat-value">{timeAgo(data.timestamp)}</span>
          </div>
        </div>
      )}

      {/* Exchange List */}
      <div className="mep-list">
        {data?.prices.map((ex) => {
          const diff = data.avg_price > 0 ? ((ex.price - data.avg_price) / data.avg_price) * 100 : 0
          const isBest = ex.exchange === data.best_exchange
          const color = EXCHANGE_COLORS[ex.exchange.toLowerCase()] ?? '#888'

          return (
            <div
              key={ex.exchange}
              className={`mep-exchange-card ${ex.status === 'error' ? 'error' : ''} ${isBest ? 'best' : ''}`}
            >
              <div className="mep-exchange-header">
                <div className="mep-exchange-identity">
                  <span className="mep-exchange-dot" style={{ backgroundColor: color }} />
                  <span className="mep-exchange-name">{ex.exchange}</span>
                  {isBest && <span className="mep-best-badge">BEST</span>}
                </div>
                <div className="mep-exchange-price">
                  <span className="mep-price-value">${formatPrice(ex.price)}</span>
                  <span className={`mep-price-diff ${diff >= 0 ? 'positive' : 'negative'}`}>
                    {diff >= 0 ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                    {diff >= 0 ? '+' : ''}{diff.toFixed(3)}%
                  </span>
                </div>
              </div>

              {ex.status === 'ok' ? (
                <div className="mep-exchange-details">
                  <div className="mep-detail-row">
                    <span className="mep-detail-label">Bid</span>
                    <span className="mep-detail-value">${formatPrice(ex.bid)}</span>
                  </div>
                  <div className="mep-detail-row">
                    <span className="mep-detail-label">Ask</span>
                    <span className="mep-detail-value">${formatPrice(ex.ask)}</span>
                  </div>
                  <div className="mep-detail-row">
                    <span className="mep-detail-label">Spread</span>
                    <span className="mep-detail-value">{ex.spread_pct.toFixed(3)}%</span>
                  </div>
                  <div className="mep-detail-row">
                    <span className="mep-detail-label">24h Vol</span>
                    <span className="mep-detail-value">
                      {ex.volume_24h != null && ex.volume_24h > 0
                        ? `$${(ex.volume_24h / 1e6).toFixed(1)}M`
                        : '--'}
                    </span>
                  </div>
                  <div className="mep-detail-row">
                    <span className="mep-detail-label">Updated</span>
                    <span className="mep-detail-value">{timeAgo(ex.timestamp)}</span>
                  </div>
                </div>
              ) : (
                <div className="mep-exchange-error">
                  <AlertTriangle size={11} />
                  <span>{ex.error ?? ex.status}</span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Arbitrage Opportunity */}
      {data && data.spread_range_pct > 0.1 && (
        <div className="mep-arbitrage">
          <TrendingUp size={13} />
          <div className="mep-arb-info">
            <span className="mep-arb-label">Arbitrage Opportunity</span>
            <span className="mep-arb-value">
              {data.spread_range_pct.toFixed(3)}% between {data.best_exchange} and {data.worst_exchange}
            </span>
          </div>
        </div>
      )}

      {!loading && data?.prices.length === 0 && (
        <div className="mep-empty">
          <Globe size={24} />
          <p>No exchange data available</p>
          <p className="mep-empty-hint">Ensure backend multi-exchange ingestion is configured</p>
        </div>
      )}
    </div>
  )
}
