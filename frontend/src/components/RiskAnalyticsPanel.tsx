import { useMemo } from 'react'
import { useChartStore } from '../store/chartStore'
import { Shield, Percent, TrendingUp, AlertTriangle, Target, Calculator } from 'lucide-react'

export function RiskAnalyticsPanel() {
  const signals = useChartStore((state) => state.signals)
  const metrics = useChartStore((state) => state.metrics)

  const analytics = useMemo(() => {
    if (!signals.length || !metrics) return null

    const latestSignal = signals[signals.length - 1]
    const atr14 = metrics.atr14
    const vwap = metrics.vwap
    const close = metrics.vwap * (1 + (metrics.vwap_distance_pct || 0) / 100)

    return {
      signal: latestSignal,
      winProb: latestSignal.win_probability ?? 0.5,
      kelly: latestSignal.kelly_fraction ?? 0,
      riskFrac: latestSignal.suggested_risk_fraction ?? 0.01,
      cvar: latestSignal.cvar95_loss ?? 0,
      ruin: latestSignal.risk_of_ruin ?? 0,
      rr: latestSignal.risk_reward,
      confidence: latestSignal.confidence,
      atr14,
      vwap,
      close,
      vwapDist: metrics.vwap_distance_pct ?? 0,
      volZ: metrics.volume_zscore ?? 0,
      realizedVol: metrics.realized_volatility ?? 0,
      parkinsonVol: metrics.parkinson_volatility ?? 0,
      gkVol: metrics.garman_klass_volatility ?? 0,
      biasScore: metrics.bias_score ?? 0,
      trendScore: metrics.trend_score ?? 0,
      volScore: metrics.volatility_score ?? 0,
      instBias: metrics.institutional_bias ?? 'neutral',
      expectedMove: metrics.expected_move ?? 0,
      expectedMovePct: metrics.expected_move_pct ?? 0,
      premiumDiscount: metrics.premium_discount ?? 0,
      equilibrium: metrics.equilibrium ?? 0,
      displacement: metrics.displacement_ratio ?? 0,
    }
  }, [signals, metrics])

  if (!analytics) {
    return (
      <div className="risk-panel">
        <div className="risk-empty">Waiting for signal and metrics data...</div>
      </div>
    )
  }

  const getKellyColor = (k: number) => k > 0.2 ? '#22c55e' : k > 0.1 ? '#f59e0b' : '#ef4444'
  const getRuinColor = (r: number) => r < 0.1 ? '#22c55e' : r < 0.3 ? '#f59e0b' : '#ef4444'
  const getCvarColor = (c: number, risk: number) => (c / risk) < 2 ? '#22c55e' : (c / risk) < 3 ? '#f59e0b' : '#ef4444'

  return (
    <div className="risk-panel">
      {/* Position Sizing */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <Calculator size={14} /> Position Sizing (Kelly Criterion)
        </h3>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">Full Kelly</span>
            <span className="risk-value" style={{ color: getKellyColor(analytics.kelly) }}>
              {(analytics.kelly * 100).toFixed(2)}%
            </span>
            <span className="risk-sub">Quarter Kelly: {(analytics.riskFrac * 100).toFixed(2)}%</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Win Probability</span>
            <span className="risk-value">{(analytics.winProb * 100).toFixed(1)}%</span>
            <span className="risk-sub">Loss: {((1 - analytics.winProb) * 100).toFixed(1)}%</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Risk:Reward</span>
            <span className="risk-value">1:{analytics.rr.toFixed(2)}</span>
          </div>
        </div>
      </div>

      {/* Risk Metrics */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <Shield size={14} /> Risk Metrics
        </h3>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">CVaR 95%</span>
            <span className="risk-value" style={{ color: getCvarColor(analytics.cvar, analytics.signal.stop_loss ? Math.abs(analytics.signal.entry - analytics.signal.stop_loss) : 1) }}>
              ${analytics.cvar.toFixed(2)}
            </span>
            <span className="risk-sub">Conditional Value at Risk</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Risk of Ruin</span>
            <span className="risk-value" style={{ color: getRuinColor(analytics.ruin) }}>
              {(analytics.ruin * 100).toFixed(2)}%
            </span>
            <span className="risk-sub">{analytics.ruin < 0.1 ? 'Safe' : analytics.ruin < 0.3 ? 'Moderate' : 'High Risk'}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Signal Confidence</span>
            <span className="risk-value">{(analytics.confidence * 100).toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* Volatility Analysis */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <TrendingUp size={14} /> Volatility Analysis
        </h3>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">ATR (14)</span>
            <span className="risk-value">{analytics.atr14.toFixed(2)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Realized Vol</span>
            <span className="risk-value">{(analytics.realizedVol * 100).toFixed(2)}%</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Parkinson Vol</span>
            <span className="risk-value">{(analytics.parkinsonVol * 100).toFixed(2)}%</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Garman-Klass Vol</span>
            <span className="risk-value">{(analytics.gkVol * 100).toFixed(2)}%</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Volume Z-Score</span>
            <span className="risk-value">{analytics.volZ.toFixed(2)}</span>
            <span className="risk-sub">{analytics.volZ > 2 ? 'High volume' : analytics.volZ < -2 ? 'Low volume' : 'Normal'}</span>
          </div>
        </div>
      </div>

      {/* Institutional Bias */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <Target size={14} /> Institutional Bias
        </h3>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">Overall Bias</span>
            <span className="risk-value" style={{
              color: analytics.instBias === 'bullish' ? '#22c55e' : analytics.instBias === 'bearish' ? '#ef4444' : '#f59e0b'
            }}>
              {analytics.instBias.toUpperCase()}
            </span>
            <span className="risk-sub">Score: {analytics.biasScore.toFixed(3)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Trend Score</span>
            <span className="risk-value">{analytics.trendScore.toFixed(3)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Volatility Score</span>
            <span className="risk-value">{analytics.volScore.toFixed(3)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Expected Move</span>
            <span className="risk-value">{analytics.expectedMove.toFixed(2)}</span>
            <span className="risk-sub">({(analytics.expectedMovePct * 100).toFixed(2)}%)</span>
          </div>
        </div>
      </div>

      {/* VWAP & Premium/Discount */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <Percent size={14} /> VWAP & Pricing
        </h3>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">VWAP</span>
            <span className="risk-value">{analytics.vwap.toFixed(2)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">VWAP Distance</span>
            <span className="risk-value" style={{ color: analytics.vwapDist > 0 ? '#22c55e' : '#ef4444' }}>
              {analytics.vwapDist.toFixed(3)}%
            </span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Premium/Discount</span>
            <span className="risk-value">{analytics.premiumDiscount.toFixed(3)}</span>
            <span className="risk-sub">{analytics.premiumDiscount > 0.25 ? 'Premium' : analytics.premiumDiscount < -0.25 ? 'Discount' : 'Fair'}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Equilibrium</span>
            <span className="risk-value">{analytics.equilibrium.toFixed(2)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Displacement Ratio</span>
            <span className="risk-value">{analytics.displacement.toFixed(3)}</span>
          </div>
        </div>
      </div>

      {/* Signal Details */}
      <div className="risk-section">
        <h3 className="risk-section-title">
          <AlertTriangle size={14} /> Signal Details
        </h3>
        <div className="risk-signal-reason">
          <p>{analytics.signal.reason}</p>
        </div>
        <div className="risk-grid">
          <div className="risk-metric">
            <span className="risk-label">Entry</span>
            <span className="risk-value">${analytics.signal.entry.toFixed(2)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Stop Loss</span>
            <span className="risk-value" style={{ color: '#ef4444' }}>${analytics.signal.stop_loss.toFixed(2)}</span>
          </div>
          <div className="risk-metric">
            <span className="risk-label">Take Profit</span>
            <span className="risk-value" style={{ color: '#22c55e' }}>${analytics.signal.exit_price.toFixed(2)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
