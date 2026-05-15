import { useMemo } from 'react'
import { useChartStore } from '../store/chartStore'
import { TrendingUp, TrendingDown, Activity, BarChart3, Waves, GitBranch, Target, AlertTriangle } from 'lucide-react'

export function InstitutionalMetricsPanel() {
  const metrics = useChartStore((state) => state.metrics)

  const institutional = useMemo(() => {
    if (!metrics) return null

    const hurst = metrics.hurst_exponent ?? 0.5
    const hurstRegime = hurst < 0.4 ? 'mean_reverting' : hurst > 0.6 ? 'trending' : 'random'
    const entropy = metrics.shannon_entropy ?? 1.0
    const entropyFactor = 1.0 - entropy

    return {
      hurst,
      hurstRegime,
      entropy,
      entropyFactor,
      garchVol: metrics.garch_volatility ?? 0,
      garchPersistence: metrics.garch_persistence ?? 0,
      kalmanTrend: metrics.kalman_trend ?? 0,
      kalmanStrength: metrics.kalman_trend_strength ?? 0,
      markovBull: metrics.markov_bull_prob ?? 0.5,
      markovBear: metrics.markov_bear_prob ?? 0.5,
      markovCertainty: metrics.markov_regime_certainty ?? 0,
      mcVar95: metrics.monte_carlo_var95 ?? 0,
      mcExpectedReturn: metrics.monte_carlo_expected_return ?? 0,
      mcMaxDD: metrics.monte_carlo_max_drawdown ?? 0,
      fourierPeriod: metrics.fourier_dominant_period ?? 0,
      fourierStrength: metrics.fourier_cycle_strength ?? 0,
      vpPoc: metrics.volume_profile_poc ?? 0,
      vpVah: metrics.volume_profile_vah ?? 0,
      vpVal: metrics.volume_profile_val ?? 0,
      vpImbalance: metrics.volume_profile_imbalance ?? 0,
      skewness: metrics.return_skewness ?? 0,
      kurtosis: metrics.return_kurtosis ?? 3,
      fractalDim: metrics.fractal_dimension ?? 1.5,
      ljungBox: metrics.ljung_box_statistic ?? 0,
      acfLag1: metrics.autocorrelation_lag1 ?? 0,
    }
  }, [metrics])

  if (!institutional) {
    return (
      <div className="inst-panel">
        <div className="inst-empty">Waiting for institutional metrics...</div>
      </div>
    )
  }

  const getHurstColor = (h: number) => h < 0.4 ? '#22c55e' : h > 0.6 ? '#3b82f6' : '#f59e0b'
  const getRegimeIcon = (regime: string) => {
    if (regime === 'mean_reverting') return <Waves size={14} />
    if (regime === 'trending') return <TrendingUp size={14} />
    return <Activity size={14} />
  }

  return (
    <div className="inst-panel">
      {/* Regime Detection */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <GitBranch size={14} /> Regime Detection
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">Hurst Exponent</span>
            <span className="inst-value" style={{ color: getHurstColor(institutional.hurst) }}>
              {institutional.hurst.toFixed(3)}
            </span>
            <span className="inst-badge" style={{ borderColor: getHurstColor(institutional.hurst) }}>
              {getRegimeIcon(institutional.hurstRegime)} {institutional.hurstRegime.replace('_', ' ')}
            </span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Shannon Entropy</span>
            <span className="inst-value">{institutional.entropy.toFixed(3)}</span>
            <span className="inst-sub">Structure: {(institutional.entropyFactor * 100).toFixed(1)}%</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Fractal Dimension</span>
            <span className="inst-value">{institutional.fractalDim.toFixed(3)}</span>
            <span className="inst-sub">{institutional.fractalDim < 1.3 ? 'Smooth trend' : institutional.fractalDim > 1.7 ? 'Chaotic' : 'Balanced'}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Autocorrelation (Lag 1)</span>
            <span className="inst-value">{institutional.acfLag1.toFixed(3)}</span>
            <span className="inst-sub">Ljung-Box: {institutional.ljungBox.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {/* Volatility Forecasting */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <BarChart3 size={14} /> Volatility Forecasting
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">GARCH(1,1) Volatility</span>
            <span className="inst-value">{(institutional.garchVol * 100).toFixed(3)}%</span>
            <span className="inst-sub">Persistence: {institutional.garchPersistence.toFixed(3)}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Kalman Trend</span>
            <span className="inst-value" style={{ color: institutional.kalmanTrend > 0 ? '#22c55e' : '#ef4444' }}>
              {institutional.kalmanTrend > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {institutional.kalmanTrend.toFixed(4)}
            </span>
            <span className="inst-sub">Strength: {(institutional.kalmanStrength * 100).toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* Markov Regime Switching */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <Activity size={14} /> Markov Regime Switching
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">Bull Regime</span>
            <div className="inst-bar-container">
              <div className="inst-bar" style={{ width: `${institutional.markovBull * 100}%`, background: '#22c55e' }} />
            </div>
            <span className="inst-value">{(institutional.markovBull * 100).toFixed(1)}%</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Bear Regime</span>
            <div className="inst-bar-container">
              <div className="inst-bar" style={{ width: `${institutional.markovBear * 100}%`, background: '#ef4444' }} />
            </div>
            <span className="inst-value">{(institutional.markovBear * 100).toFixed(1)}%</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Regime Certainty</span>
            <span className="inst-value">{(institutional.markovCertainty * 100).toFixed(1)}%</span>
            <span className="inst-sub">Transition: {((1 - institutional.markovCertainty) * 100).toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* Monte Carlo Simulation */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <Target size={14} /> Monte Carlo Simulation
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">VaR 95%</span>
            <span className="inst-value" style={{ color: institutional.mcVar95 > 0.05 ? '#ef4444' : '#22c55e' }}>
              {(institutional.mcVar95 * 100).toFixed(2)}%
            </span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Expected Return</span>
            <span className="inst-value" style={{ color: institutional.mcExpectedReturn > 0 ? '#22c55e' : '#ef4444' }}>
              {(institutional.mcExpectedReturn * 100).toFixed(2)}%
            </span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Max Drawdown Prob</span>
            <span className="inst-value">{(institutional.mcMaxDD * 100).toFixed(2)}%</span>
          </div>
        </div>
      </div>

      {/* Volume Profile */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <BarChart3 size={14} /> Volume Profile
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">POC</span>
            <span className="inst-value">{institutional.vpPoc.toFixed(2)}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">VAH</span>
            <span className="inst-value">{institutional.vpVah.toFixed(2)}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">VAL</span>
            <span className="inst-value">{institutional.vpVal.toFixed(2)}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Volume Imbalance</span>
            <span className="inst-value" style={{ color: institutional.vpImbalance > 0 ? '#22c55e' : '#ef4444' }}>
              {institutional.vpImbalance.toFixed(3)}
            </span>
            <span className="inst-sub">{institutional.vpImbalance > 0.3 ? 'Bullish' : institutional.vpImbalance < -0.3 ? 'Bearish' : 'Neutral'}</span>
          </div>
        </div>
      </div>

      {/* Distribution Analysis */}
      <div className="inst-section">
        <h3 className="inst-section-title">
          <AlertTriangle size={14} /> Distribution Analysis
        </h3>
        <div className="inst-grid">
          <div className="inst-metric">
            <span className="inst-label">Skewness</span>
            <span className="inst-value">{institutional.skewness.toFixed(3)}</span>
            <span className="inst-sub">{institutional.skewness > 1 ? 'Right tail' : institutional.skewness < -1 ? 'Left tail' : 'Symmetric'}</span>
          </div>
          <div className="inst-metric">
            <span className="inst-label">Kurtosis</span>
            <span className="inst-value">{institutional.kurtosis.toFixed(3)}</span>
            <span className="inst-sub">{institutional.kurtosis > 4 ? 'Fat tails' : 'Normal'}</span>
          </div>
        </div>
      </div>

      {/* Cycle Detection */}
      {institutional.fourierStrength > 0.2 && (
        <div className="inst-section">
          <h3 className="inst-section-title">
            <Waves size={14} /> Cycle Detection
          </h3>
          <div className="inst-grid">
            <div className="inst-metric">
              <span className="inst-label">Dominant Period</span>
              <span className="inst-value">{institutional.fourierPeriod.toFixed(0)} bars</span>
            </div>
            <div className="inst-metric">
              <span className="inst-label">Cycle Strength</span>
              <span className="inst-value">{(institutional.fourierStrength * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
