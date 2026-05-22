import { useMemo } from 'react'
import { useChartStore } from '../store/chartStore'
import {
  Shield,
  Percent,
  TrendingUp,
  AlertTriangle,
  Target,
  Calculator,
  Info,
  Activity,
  DollarSign,
} from 'lucide-react'

export function RiskAnalyticsPanel() {
  const signals = useChartStore((state) => state.signals)
  const metrics = useChartStore((state) => state.metrics)
  const scalpRisk = useChartStore((state) => state.scalpRisk)
  const scalp = useChartStore((state) => state.scalpContext)

  const blockers = useMemo(() => {
    if (!scalp) return null
    return {
      trade_blocked_reasons: scalp.trade_blocked_reasons ?? [],
      blockedCount: (scalp.trade_blocked_reasons ?? []).length,
      hasBlockers: (scalp.trade_blocked_reasons ?? []).length > 0,
    }
  }, [scalp])

  const analytics = useMemo(() => {
    if (!signals || signals.length === 0 || !metrics) return null

    const latestSignal = signals[signals.length - 1]
    if (!latestSignal) return null

    const atr14 = metrics.atr14 || 0
    const vwap = metrics.vwap || 0
    const close = vwap * (1 + (metrics.vwap_distance_pct || 0) / 100)

    return {
      signal: latestSignal,
      winProb: latestSignal.win_probability ?? 0.5,
      kelly: latestSignal.kelly_fraction ?? 0,
      riskFrac: latestSignal.suggested_risk_fraction ?? 0.01,
      cvar: latestSignal.cvar95_loss ?? 0,
      ruin: latestSignal.risk_of_ruin ?? 0,
      rr: latestSignal.risk_reward,
      confidence: latestSignal.confidence ?? 0,
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

  const getKellyColor = (k: number) => (k > 0.2 ? '#1fe3a3' : k > 0.1 ? '#f59f43' : '#ff5b6b')
  const getRuinColor = (r: number) => (r < 0.1 ? '#1fe3a3' : r < 0.3 ? '#f59f43' : '#ff5b6b')
  const getCvarColor = (c: number, risk: number) =>
    risk > 0 && c / risk < 2 ? '#1fe3a3' : risk > 0 && c / risk < 3 ? '#f59f43' : '#ff5b6b'
  const getRiskLevelColor = (level: string) => {
    switch (level?.toLowerCase()) {
      case 'low':
        return '#1fe3a3'
      case 'medium':
        return '#f59f43'
      case 'high':
        return '#ff5b6b'
      default:
        return '#8ab4f8'
    }
  }

  const riskLevel = scalpRisk?.daily_loss_hit ? 'high' : scalpRisk && scalpRisk.daily_pnl < 0 ? 'medium' : 'low'

  const allWarnings = [
    ...(blockers?.trade_blocked_reasons ?? []),
    ...(scalpRisk?.daily_loss_hit ? ['Daily loss limit reached — trading halted'] : []),
  ]

  return (
    <div className="risk-panel">
      {/* Risk Overview */}
      {scalpRisk && (
        <div className="risk-section risk-overview-section">
          <h3 className="risk-section-title">
            <Shield size={14} /> Risk Overview
          </h3>
          <div className="risk-overview-grid">
            <div className="risk-overview-card">
              <div className="risk-ov-icon">
                <Activity size={16} />
              </div>
              <div className="risk-ov-info">
                <span className="risk-ov-label">Risk Level</span>
                <span
                  className="risk-ov-value"
                  style={{ color: getRiskLevelColor(riskLevel) }}
                >
                  {riskLevel.toUpperCase()}
                </span>
              </div>
            </div>
            <div className="risk-overview-card">
              <div className="risk-ov-icon">
                <DollarSign size={16} />
              </div>
              <div className="risk-ov-info">
                <span className="risk-ov-label">Daily P&L</span>
                <span
                  className={`risk-ov-value ${(scalpRisk.daily_pnl || 0) >= 0 ? 'positive' : 'negative'}`}
                >
                  {(scalpRisk.daily_pnl || 0) >= 0 ? '+' : ''}${(scalpRisk.daily_pnl || 0).toFixed(2)}
                </span>
              </div>
            </div>
            <div className="risk-overview-card">
              <div className="risk-ov-icon">
                <Target size={16} />
              </div>
              <div className="risk-ov-info">
                <span className="risk-ov-label">Positions</span>
                <span className="risk-ov-value">
                  {scalpRisk.open_futures}/{scalpRisk.max_positions}
                </span>
              </div>
            </div>
            <div className="risk-overview-card">
              <div className="risk-ov-icon">
                <Percent size={16} />
              </div>
              <div className="risk-ov-info">
                <span className="risk-ov-label">Drawdown</span>
                <span className="risk-ov-value">{scalpRisk.daily_loss_pct.toFixed(2)}%</span>
              </div>
            </div>
          </div>

          {/* Warnings */}
          {allWarnings.length > 0 && (
            <div className="risk-warnings">
              <AlertTriangle size={12} />
              <div className="risk-warnings-list">
                {allWarnings.map((w, i) => (
                  <span key={i} className="risk-warning">
                    {w}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Position Sizing */}
      {analytics && (
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
              <span className="risk-sub">
                Quarter Kelly: {(analytics.riskFrac * 100).toFixed(2)}%
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Win Probability</span>
              <span className="risk-value">{(analytics.winProb * 100).toFixed(1)}%</span>
              <span className="risk-sub">
                Loss: {((1 - analytics.winProb) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Risk:Reward</span>
              <span className="risk-value">
                1:{analytics.rr != null ? analytics.rr.toFixed(2) : '--'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Risk Metrics */}
      {analytics && (
        <div className="risk-section">
          <h3 className="risk-section-title">
            <Shield size={14} /> Risk Metrics
          </h3>
          <div className="risk-grid">
            <div className="risk-metric">
              <span className="risk-label">CVaR 95%</span>
              <span
                className="risk-value"
                style={{
                  color: getCvarColor(
                    analytics.cvar,
                    analytics.signal?.stop_loss
                      ? Math.abs(analytics.signal.entry - analytics.signal.stop_loss)
                      : 1
                  ),
                }}
              >
                ${analytics.cvar.toFixed(2)}
              </span>
              <span className="risk-sub">Conditional Value at Risk</span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Risk of Ruin</span>
              <span
                className="risk-value"
                style={{ color: getRuinColor(analytics.ruin) }}
              >
                {(analytics.ruin * 100).toFixed(2)}%
              </span>
              <span className="risk-sub">
                {analytics.ruin < 0.1
                  ? 'Safe'
                  : analytics.ruin < 0.3
                    ? 'Moderate'
                    : 'High Risk'}
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Signal Confidence</span>
              <span className="risk-value">
                {(analytics.confidence * 100).toFixed(1)}%
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Volatility Analysis */}
      {analytics && (
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
              <span className="risk-value">
                {(analytics.realizedVol * 100).toFixed(2)}%
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Parkinson Vol</span>
              <span className="risk-value">
                {(analytics.parkinsonVol * 100).toFixed(2)}%
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Garman-Klass Vol</span>
              <span className="risk-value">{(analytics.gkVol * 100).toFixed(2)}%</span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Volume Z-Score</span>
              <span className="risk-value">{analytics.volZ.toFixed(2)}</span>
              <span className="risk-sub">
                {analytics.volZ > 2
                  ? 'High volume'
                  : analytics.volZ < -2
                    ? 'Low volume'
                    : 'Normal'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Institutional Bias */}
      {analytics && (
        <div className="risk-section">
          <h3 className="risk-section-title">
            <Target size={14} /> Institutional Bias
          </h3>
          <div className="risk-grid">
            <div className="risk-metric">
              <span className="risk-label">Overall Bias</span>
              <span
                className="risk-value"
                style={{
                  color:
                    analytics.instBias === 'bullish'
                      ? '#1fe3a3'
                      : analytics.instBias === 'bearish'
                        ? '#ff5b6b'
                        : '#f59f43',
                }}
              >
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
              <span className="risk-sub">
                ({(analytics.expectedMovePct * 100).toFixed(2)}%)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* VWAP & Premium/Discount */}
      {analytics && (
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
              <span
                className="risk-value"
                style={{ color: analytics.vwapDist > 0 ? '#1fe3a3' : '#ff5b6b' }}
              >
                {analytics.vwapDist.toFixed(3)}%
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Premium/Discount</span>
              <span className="risk-value">{analytics.premiumDiscount.toFixed(3)}</span>
              <span className="risk-sub">
                {analytics.premiumDiscount > 0.25
                  ? 'Premium'
                  : analytics.premiumDiscount < -0.25
                    ? 'Discount'
                    : 'Fair'}
              </span>
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
      )}

      {/* Signal Details */}
      {analytics && analytics.signal && (
        <div className="risk-section">
          <h3 className="risk-section-title">
            <AlertTriangle size={14} /> Signal Details
          </h3>
          {analytics.signal.reason && (
            <div className="risk-signal-reason">
              <Info size={12} />
              <p>{analytics.signal.reason}</p>
            </div>
          )}
          <div className="risk-grid">
            <div className="risk-metric">
              <span className="risk-label">Entry</span>
              <span className="risk-value">
                ${analytics.signal.entry?.toFixed(2) ?? '--'}
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Stop Loss</span>
              <span className="risk-value" style={{ color: '#ff5b6b' }}>
                ${analytics.signal.stop_loss?.toFixed(2) ?? '--'}
              </span>
            </div>
            <div className="risk-metric">
              <span className="risk-label">Take Profit</span>
              <span className="risk-value" style={{ color: '#1fe3a3' }}>
                ${analytics.signal.exit_price?.toFixed(2) ?? '--'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!analytics && !scalpRisk && (
        <div className="risk-empty">
          <Shield size={24} className="risk-empty-icon" />
          <p>Waiting for signal and metrics data...</p>
          <p className="risk-empty-hint">
            Connect to live data or run a backtest to see risk analytics.
          </p>
        </div>
      )}
    </div>
  )
}
