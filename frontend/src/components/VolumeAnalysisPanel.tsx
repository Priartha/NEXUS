import { memo, useMemo } from 'react'
import { Activity, BarChart3, Target, Zap, AlertTriangle, Layers } from 'lucide-react'
import { useChartStore } from '../store/chartStore'

export const VolumeAnalysisPanel = memo(function VolumeAnalysisPanel() {
  const vol = useChartStore((s) => s.volumeAnalysis)
  const delta = useChartStore((s) => s.deltaAnalysis)

  const data = useMemo(() => {
    if (!vol && !delta) return null
    return { vol, delta }
  }, [vol, delta])

  if (!data) {
    return (
      <div className="volume-panel">
        <div className="volume-empty">Waiting for tick-level volume data...</div>
      </div>
    )
  }

  const getDeltaDivergenceColor = (type: string) => {
    if (type.includes('bullish')) return '#22c55e'
    if (type.includes('bearish')) return '#ef4444'
    return '#94a3b8'
  }

  return (
    <div className="volume-panel">
      {/* Genuine Volume Analysis */}
      {data.vol && (
        <>
          <div className="volume-section">
            <h3 className="volume-section-title">
              <BarChart3 size={14} /> Genuine Volume Analysis
            </h3>
            <div className="volume-meta">
              Tick-level buy/sell breakdown from Binance trade stream (not candle approximation)
            </div>
            <div className="volume-grid">
              <div className="volume-metric">
                <span className="volume-label">Buy Volume</span>
                <span className="volume-value" style={{ color: '#22c55e' }}>
                  {data.vol.total_buy_volume.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Sell Volume</span>
                <span className="volume-value" style={{ color: '#ef4444' }}>
                  {data.vol.total_sell_volume.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Total Volume</span>
                <span className="volume-value">
                  {data.vol.total_volume.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Buy/Sell Ratio</span>
                <span className="volume-value" style={{ color: data.vol.buy_sell_ratio > 1 ? '#22c55e' : '#ef4444' }}>
                  {data.vol.buy_sell_ratio.toFixed(3)}
                </span>
                <span className="volume-sub">{data.vol.buy_sell_ratio > 1.05 ? 'Buying pressure' : data.vol.buy_sell_ratio < 0.95 ? 'Selling pressure' : 'Neutral'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Volume Delta</span>
                <span className="volume-value" style={{ color: data.vol.volume_delta > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.vol.volume_delta > 0 ? '+' : ''}{data.vol.volume_delta.toFixed(4)}
                </span>
                <span className="volume-sub">({(data.vol.volume_delta_pct * 100).toFixed(2)}% of total)</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Absorption Ratio</span>
                <span className="volume-value">{data.vol.absorption_ratio.toFixed(3)}</span>
                <span className="volume-sub">{data.vol.absorption_ratio < 0.35 ? 'Directional' : 'Absorption'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Bid/Ask Ratio</span>
                <span className="volume-value" style={{ color: data.vol.bid_ask_ratio > 1 ? '#22c55e' : '#ef4444' }}>
                  {data.vol.bid_ask_ratio.toFixed(3)}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Avg Trade Size</span>
                <span className="volume-value">{data.vol.avg_trade_size.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
              </div>
            </div>
          </div>

          {/* VPIN & Large Trades */}
          <div className="volume-section">
            <h3 className="volume-section-title">
              <Zap size={14} /> Trade Quality
            </h3>
            <div className="volume-grid">
              <div className="volume-metric">
                <span className="volume-label">VPIN</span>
                <span className="volume-value" style={{ color: data.vol.vpin > 0.7 ? '#ef4444' : data.vol.vpin > 0.5 ? '#f59e0b' : '#22c55e' }}>
                  {data.vol.vpin.toFixed(4)}
                </span>
                <span className="volume-sub">{data.vol.vpin > 0.7 ? 'High informed trading risk' : data.vol.vpin > 0.5 ? 'Moderate' : 'Low informed trading'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Large Trade Ratio</span>
                <span className="volume-value" style={{ color: data.vol.large_trade_ratio > 0.3 ? '#ef4444' : '#94a3b8' }}>
                  {(data.vol.large_trade_ratio * 100).toFixed(1)}%
                </span>
                <span className="volume-sub">{data.vol.large_trade_ratio > 0.3 ? 'Whale activity detected' : 'Normal'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Buy Trades</span>
                <span className="volume-value" style={{ color: '#22c55e' }}>{data.vol.buy_count}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Sell Trades</span>
                <span className="volume-value" style={{ color: '#ef4444' }}>{data.vol.sell_count}</span>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Delta Analysis */}
      {data.delta && (
        <>
          <div className="volume-section">
            <h3 className="volume-section-title">
              <Activity size={14} /> Delta Analysis (Tick-Level CVD)
            </h3>
            <div className="volume-meta">
              True cumulative volume delta from aggressive buy/sell classification
            </div>
            <div className="volume-grid">
              <div className="volume-metric">
                <span className="volume-label">Cumulative Delta</span>
                <span className="volume-value" style={{ color: data.delta.cumulative_delta > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.cumulative_delta > 0 ? '+' : ''}{data.delta.cumulative_delta.toFixed(4)}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Last Delta</span>
                <span className="volume-value" style={{ color: data.delta.last_delta > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.last_delta > 0 ? '+' : ''}{data.delta.last_delta.toFixed(4)}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Delta Momentum</span>
                <span className="volume-value" style={{ color: data.delta.delta_momentum > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.delta_momentum > 0 ? '+' : ''}{data.delta.delta_momentum.toFixed(4)}
                </span>
                <span className="volume-sub">{data.delta.delta_momentum > 0 ? 'Accelerating buys' : 'Accelerating sells'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Delta Acceleration</span>
                <span className="volume-value" style={{ color: data.delta.delta_acceleration > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.delta_acceleration > 0 ? '+' : ''}{data.delta.delta_acceleration.toFixed(4)}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Delta Balance</span>
                <span className="volume-value" style={{ color: data.delta.delta_balance > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.delta_balance > 0 ? '+' : ''}{data.delta.delta_balance.toFixed(4)}
                </span>
                <span className="volume-sub">{data.delta.delta_balance > 0 ? 'Buying pressure' : 'Selling pressure'}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">CVD Slope</span>
                <span className="volume-value" style={{ color: data.delta.cvd_slope > 0 ? '#22c55e' : '#ef4444' }}>
                  {data.delta.cvd_slope > 0 ? '+' : ''}{data.delta.cvd_slope.toFixed(4)}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">CVD Trend</span>
                <span className="volume-value" style={{ color: data.delta.cvd_trend === 'increasing' ? '#22c55e' : data.delta.cvd_trend === 'decreasing' ? '#ef4444' : '#94a3b8' }}>
                  {data.delta.cvd_trend.toUpperCase()}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Delta Extreme</span>
                <span className="volume-value" style={{ color: data.delta.delta_extreme ? '#ef4444' : '#22c55e' }}>
                  {data.delta.delta_extreme ? 'YES' : 'Normal'}
                </span>
              </div>
            </div>
          </div>

          {/* Delta Divergence */}
          <div className="volume-section">
            <h3 className="volume-section-title">
              <Target size={14} /> Delta Divergence
            </h3>
            <div className="volume-grid">
              <div className="volume-metric">
                <span className="volume-label">Divergence Type</span>
                <span className="volume-value" style={{ color: getDeltaDivergenceColor(data.delta.delta_divergence_type) }}>
                  {data.delta.delta_divergence_type === 'none' ? 'NONE' : data.delta.delta_divergence_type.replace('_', ' ').toUpperCase()}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Divergence Strength</span>
                <span className="volume-value">{(data.delta.delta_divergence_strength * 100).toFixed(1)}%</span>
              </div>
            </div>
            {data.delta.delta_divergence_type !== 'none' && (
              <div className="volume-alert" style={{ borderColor: getDeltaDivergenceColor(data.delta.delta_divergence_type) }}>
                <AlertTriangle size={12} />
                {data.delta.delta_divergence_type.includes('bullish')
                  ? 'Bullish delta divergence: price lower, delta higher — accumulation'
                  : 'Bearish delta divergence: price higher, delta lower — distribution'}
              </div>
            )}
          </div>

          {/* Aggressive Trade Counts */}
          <div className="volume-section">
            <h3 className="volume-section-title">
              <Layers size={14} /> Aggressive Trade Counts
            </h3>
            <div className="volume-grid">
              <div className="volume-metric">
                <span className="volume-label">Aggressive Buys</span>
                <span className="volume-value" style={{ color: '#22c55e' }}>{data.delta.aggressive_buy_count}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Aggressive Sells</span>
                <span className="volume-value" style={{ color: '#ef4444' }}>{data.delta.aggressive_sell_count}</span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Net Aggressive</span>
                <span className="volume-value" style={{ color: data.delta.aggressive_buy_count > data.delta.aggressive_sell_count ? '#22c55e' : '#ef4444' }}>
                  {data.delta.aggressive_buy_count - data.delta.aggressive_sell_count > 0 ? '+' : ''}
                  {data.delta.aggressive_buy_count - data.delta.aggressive_sell_count}
                </span>
              </div>
              <div className="volume-metric">
                <span className="volume-label">Aggression Ratio</span>
                <span className="volume-value" style={{ color: data.delta.aggressive_buy_count > data.delta.aggressive_sell_count ? '#22c55e' : '#ef4444' }}>
                  {data.delta.aggressive_sell_count > 0
                    ? (data.delta.aggressive_buy_count / data.delta.aggressive_sell_count).toFixed(3)
                    : 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
})
