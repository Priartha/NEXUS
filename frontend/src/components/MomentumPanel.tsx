import { useMemo } from 'react'
import { useChartStore } from '../store/chartStore'
import { Zap, TrendingUp, TrendingDown, Activity, BarChart3 } from 'lucide-react'

export function MomentumPanel() {
  const metrics = useChartStore((state) => state.metrics)
  const signals = useChartStore((state) => state.signals)
  const regime = useChartStore((state) => state.regime)

  const momentum = useMemo(() => {
    if (!metrics) return null

    const rsi = metrics.rsi14 ?? 50
    const trendScore = metrics.trend_score ?? 0
    const volScore = metrics.volatility_score ?? 0

    return {
      rsi,
      rsiZone: rsi < 30 ? 'oversold' : rsi < 40 ? 'near_oversold' : rsi > 70 ? 'overbought' : rsi > 60 ? 'near_overbought' : 'neutral',
      trendScore,
      trendDir: trendScore > 0.15 ? 'bullish' : trendScore < -0.15 ? 'bearish' : 'neutral',
      volScore,
      biasScore: metrics.bias_score ?? 0,
      instBias: metrics.institutional_bias ?? 'neutral',
      atr14: metrics.atr14,
      expectedMove: metrics.expected_move ?? 0,
      expectedMovePct: metrics.expected_move_pct ?? 0,
      displacement: metrics.displacement_ratio ?? 0,
      efficiencyRatio: regime?.efficiency_ratio ?? 0,
      signals,
      signalCount: signals.length,
      buySignals: signals.filter(s => s.side === 'buy').length,
      sellSignals: signals.filter(s => s.side === 'sell').length,
      avgConfidence: signals.length ? signals.reduce((sum, s) => sum + s.confidence, 0) / signals.length : 0,
      avgRR: signals.length ? signals.reduce((sum, s) => sum + s.risk_reward, 0) / signals.length : 0,
    }
  }, [metrics, signals, regime])

  if (!momentum) {
    return (
      <div className="momentum-panel">
        <div className="momentum-empty">Waiting for momentum data...</div>
      </div>
    )
  }

  const getRsiColor = (rsi: number) => rsi < 30 ? '#22c55e' : rsi > 70 ? '#ef4444' : '#f59e0b'
  const getTrendColor = (score: number) => score > 0.15 ? '#22c55e' : score < -0.15 ? '#ef4444' : '#f59e0b'
  const getBiasColor = (bias: string) => bias === 'bullish' ? '#22c55e' : bias === 'bearish' ? '#ef4444' : '#f59e0b'

  return (
    <div className="momentum-panel">
      {/* RSI Momentum */}
      <div className="momentum-section">
        <h3 className="momentum-section-title">
          <Zap size={14} /> RSI Momentum
        </h3>
        <div className="momentum-grid">
          <div className="momentum-metric">
            <span className="momentum-label">RSI (14)</span>
            <span className="momentum-value" style={{ color: getRsiColor(momentum.rsi) }}>
              {momentum.rsi.toFixed(1)}
            </span>
            <span className="momentum-badge" style={{ borderColor: getRsiColor(momentum.rsi) }}>
              {momentum.rsiZone.replace('_', ' ')}
            </span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">RSI Bar</span>
            <div className="momentum-bar-container">
              <div
                className="momentum-bar"
                style={{
                  width: `${momentum.rsi}%`,
                  background: momentum.rsi < 30 ? '#22c55e' : momentum.rsi > 70 ? '#ef4444' : '#3b82f6'
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Trend Momentum */}
      <div className="momentum-section">
        <h3 className="momentum-section-title">
          <TrendingUp size={14} /> Trend Momentum
        </h3>
        <div className="momentum-grid">
          <div className="momentum-metric">
            <span className="momentum-label">Trend Score</span>
            <span className="momentum-value" style={{ color: getTrendColor(momentum.trendScore) }}>
              {momentum.trendScore > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {momentum.trendScore.toFixed(3)}
            </span>
            <span className="momentum-sub">{momentum.trendDir}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Displacement Ratio</span>
            <span className="momentum-value">{momentum.displacement.toFixed(3)}</span>
            <span className="momentum-sub">{momentum.displacement > 0.5 ? 'Strong' : 'Weak'}</span>
          </div>
        </div>
      </div>

      {/* Institutional Bias */}
      <div className="momentum-section">
        <h3 className="momentum-section-title">
          <Activity size={14} /> Institutional Bias
        </h3>
        <div className="momentum-grid">
          <div className="momentum-metric">
            <span className="momentum-label">Overall Bias</span>
            <span className="momentum-value" style={{ color: getBiasColor(momentum.instBias) }}>
              {momentum.instBias.toUpperCase()}
            </span>
            <span className="momentum-sub">Score: {momentum.biasScore.toFixed(3)}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Volatility Score</span>
            <span className="momentum-value">{momentum.volScore.toFixed(3)}</span>
          </div>
        </div>
      </div>

      {/* Expected Move */}
      <div className="momentum-section">
        <h3 className="momentum-section-title">
          <BarChart3 size={14} /> Expected Move
        </h3>
        <div className="momentum-grid">
          <div className="momentum-metric">
            <span className="momentum-label">ATR (14)</span>
            <span className="momentum-value">{momentum.atr14.toFixed(2)}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Expected Move</span>
            <span className="momentum-value">{momentum.expectedMove.toFixed(2)}</span>
            <span className="momentum-sub">({(momentum.expectedMovePct * 100).toFixed(2)}%)</span>
          </div>
        </div>
      </div>

      {/* Signal Summary */}
      <div className="momentum-section">
        <h3 className="momentum-section-title">
          <Zap size={14} /> Signal Summary
        </h3>
        <div className="momentum-grid">
          <div className="momentum-metric">
            <span className="momentum-label">Total Signals</span>
            <span className="momentum-value">{momentum.signalCount}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Buy Signals</span>
            <span className="momentum-value" style={{ color: '#22c55e' }}>{momentum.buySignals}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Sell Signals</span>
            <span className="momentum-value" style={{ color: '#ef4444' }}>{momentum.sellSignals}</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Avg Confidence</span>
            <span className="momentum-value">{(momentum.avgConfidence * 100).toFixed(1)}%</span>
          </div>
          <div className="momentum-metric">
            <span className="momentum-label">Avg R:R</span>
            <span className="momentum-value">1:{momentum.avgRR.toFixed(2)}</span>
          </div>
        </div>
      </div>

      {/* Recent Signals */}
      {momentum.signals.length > 0 && (
        <div className="momentum-section">
          <h3 className="momentum-section-title">
            <Activity size={14} /> Recent Signals
          </h3>
          <div className="momentum-signals">
            {momentum.signals.slice(-5).reverse().map((signal) => (
              <div key={signal.id} className={`momentum-signal ${signal.side}`}>
                <div className="signal-header">
                  <span className={`signal-side ${signal.side}`}>
                    {signal.side === 'buy' ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                    {signal.side.toUpperCase()}
                  </span>
                  <span className="signal-confidence">{(signal.confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="signal-details">
                  <span>Entry: ${signal.entry.toFixed(2)}</span>
                  <span>SL: ${signal.stop_loss.toFixed(2)}</span>
                  <span>TP: ${signal.exit_price.toFixed(2)}</span>
                  <span>R:R {signal.risk_reward.toFixed(1)}</span>
                </div>
                <div className="signal-reason">{signal.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
