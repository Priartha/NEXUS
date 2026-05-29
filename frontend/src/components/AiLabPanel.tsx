import { BrainCircuit, Shield, Zap, AlertTriangle, Target } from 'lucide-react'
import { useChartStore } from '../store/chartStore'

export function AiLabPanel() {
  const stats = useChartStore((s) => s.stats)
  const scalpRisk = useChartStore((s) => s.scalpRisk)

  const ensemble = stats?.ensemble
  const optimizer = stats?.self_optimizer
  const anomaly = stats?.anomaly_detector

  return (
    <div className="panel-content">
      {/* ── ENSEMBLE MODEL ── */}
      <section>
        <h2><BrainCircuit size={13} /> Ensemble Model</h2>
        {ensemble ? (
          <>
            <dl className="facts compact">
              <div><dt>Trades</dt><dd>{ensemble.total_trades}</dd></div>
              <div><dt>Win Rate</dt><dd style={{ color: ensemble.win_rate >= 0.5 ? '#1fe3a3' : '#ff5b6b' }}>
                {(ensemble.win_rate * 100).toFixed(1)}%
              </dd></div>
              <div><dt>Total PnL</dt><dd style={{ color: ensemble.total_pnl_pct >= 0 ? '#1fe3a3' : '#ff5b6b' }}>
                {ensemble.total_pnl_pct >= 0 ? '+' : ''}{ensemble.total_pnl_pct.toFixed(2)}%
              </dd></div>
              <div><dt>Avg PnL/Trade</dt><dd>{ensemble.avg_pnl_per_trade.toFixed(3)}%</dd></div>
            </dl>
            <section style={{ marginTop: 8 }}>
              <h3 style={{ fontSize: 11, color: '#888', margin: '4px 0' }}>Model Weights</h3>
              <div style={{ display: 'flex', gap: 6 }}>
                {Object.entries(ensemble.model_weights || {}).map(([name, weight]) => (
                  <div key={name} style={{
                    flex: 1, background: 'rgba(255,255,255,0.05)', borderRadius: 4, padding: '4px 6px',
                    textAlign: 'center', fontSize: 10,
                  }}>
                    <div style={{ color: '#888', textTransform: 'capitalize' }}>{name}</div>
                    <div style={{ fontWeight: 600, color: '#fff' }}>{((weight as number) * 100).toFixed(0)}%</div>
                  </div>
                ))}
              </div>
            </section>
            {ensemble.regime_weights && Object.keys(ensemble.regime_weights).length > 0 && (
              <section style={{ marginTop: 8 }}>
                <h3 style={{ fontSize: 11, color: '#888', margin: '4px 0' }}>Regime Weights</h3>
                <dl className="facts compact">
                  {Object.entries(ensemble.regime_weights).flatMap(([model, regimes]) =>
                    Object.entries(regimes as Record<string, number>).slice(0, 3).map(([regime, w]) => (
                      <div key={`${model}-${regime}`}>
                        <dt style={{ textTransform: 'capitalize' }}>{model} / {regime}</dt>
                        <dd>{((w as number) * 100).toFixed(0)}%</dd>
                      </div>
                    ))
                  )}
                </dl>
              </section>
            )}
          </>
        ) : <p style={{ color: '#555', fontSize: 11 }}>No ensemble data yet</p>}
      </section>

      {/* ── SELF-OPTIMIZER ── */}
      <section>
        <h2><Zap size={13} /> Self-Optimizer</h2>
        {optimizer ? (
          <>
            <dl className="facts compact">
              <div><dt>Optimization Attempts</dt><dd>{optimizer.total_attempts}</dd></div>
              <div><dt>Kept (Improved)</dt><dd style={{ color: optimizer.kept_attempts > 0 ? '#1fe3a3' : '#888' }}>
                {optimizer.kept_attempts}
              </dd></div>
            </dl>
            {optimizer.current_params && (
              <section style={{ marginTop: 8 }}>
                <h3 style={{ fontSize: 11, color: '#888', margin: '4px 0' }}>Adaptive Parameters</h3>
                <dl className="facts compact">
                  <div><dt>Min Confidence</dt><dd>{(optimizer.current_params.min_confidence * 100).toFixed(0)}%</dd></div>
                  <div><dt>Min Edge</dt><dd>{(optimizer.current_params.min_edge * 100).toFixed(0)}%</dd></div>
                  <div><dt>SL Multiplier</dt><dd>{optimizer.current_params.sl_multiplier_base?.toFixed(1)}</dd></div>
                  <div><dt>TP Multiplier</dt><dd>{optimizer.current_params.tp_multiplier_base?.toFixed(1)}</dd></div>
                  <div><dt>Cooldown</dt><dd>{optimizer.current_params.cooldown_minutes}m</dd></div>
                  <div><dt>Risk/Trade</dt><dd>{(optimizer.current_params.risk_per_trade_pct * 100).toFixed(1)}%</dd></div>
                </dl>
              </section>
            )}
            {optimizer.regime_performance && Object.keys(optimizer.regime_performance).length > 0 && (
              <section style={{ marginTop: 8 }}>
                <h3 style={{ fontSize: 11, color: '#888', margin: '4px 0' }}>Regime Performance</h3>
                <dl className="facts compact">
                  {Object.entries(optimizer.regime_performance).map(([regime, data]: [string, any]) => (
                    <div key={regime}>
                      <dt style={{ textTransform: 'capitalize' }}>{regime}</dt>
                      <dd style={{ color: data.win_rate >= 0.5 ? '#1fe3a3' : '#ff5b6b' }}>
                        {(data.win_rate * 100).toFixed(0)}% ({data.trades} trades)
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
          </>
        ) : <p style={{ color: '#555', fontSize: 11 }}>No optimizer data yet</p>}
      </section>

      {/* ── ANOMALY DETECTOR ── */}
      <section>
        <h2><AlertTriangle size={13} /> Anomaly Detector</h2>
        {anomaly ? (
          <dl className="facts compact">
            <div><dt>Observations</dt><dd>{anomaly.observations}</dd></div>
            <div><dt>Anomalies Detected</dt><dd style={{ color: anomaly.anomaly_count > 0 ? '#f59f43' : '#1fe3a3' }}>
              {anomaly.anomaly_count}
            </dd></div>
            <div><dt>Baseline Return μ</dt><dd>{(anomaly.baseline_return_mean * 10000).toFixed(1)} bps</dd></div>
            <div><dt>Baseline Return σ</dt><dd>{(anomaly.baseline_return_std * 10000).toFixed(1)} bps</dd></div>
            <div><dt>Current Volatility</dt><dd>{(anomaly.current_volatility * 10000).toFixed(1)} bps</dd></div>
          </dl>
        ) : <p style={{ color: '#555', fontSize: 11 }}>No anomaly data yet</p>}
      </section>

      {/* ── RISK / KELLY ── */}
      <section>
        <h2><Shield size={13} /> Risk & Kelly Sizing</h2>
        {scalpRisk ? (
          <dl className="facts compact">
            <div><dt>Balance</dt><dd>${scalpRisk.current_balance?.toLocaleString()}</dd></div>
            <div><dt>Peak Balance</dt><dd>${scalpRisk.peak_balance?.toLocaleString()}</dd></div>
            <div><dt>Drawdown</dt><dd style={{ color: (scalpRisk.drawdown_pct ?? 0) > 5 ? '#ff5b6b' : '#1fe3a3' }}>
              {scalpRisk.drawdown_pct?.toFixed(1)}%
            </dd></div>
            <div><dt>Daily PnL</dt><dd style={{ color: (scalpRisk.daily_pnl ?? 0) >= 0 ? '#1fe3a3' : '#ff5b6b' }}>
              ${(scalpRisk.daily_pnl ?? 0).toFixed(2)}
            </dd></div>
            <div><dt>Daily Trades</dt><dd>{scalpRisk.daily_trades}</dd></div>
            <div><dt>Daily Win Rate</dt><dd>{((scalpRisk.daily_win_rate ?? 0) * 100).toFixed(0)}%</dd></div>
            <div><dt>Consecutive Losses</dt><dd style={{ color: (scalpRisk.consecutive_losses ?? 0) >= 3 ? '#ff5b6b' : '#fff' }}>
              {scalpRisk.consecutive_losses}
            </dd></div>
            <div><dt>Total Trades</dt><dd>{scalpRisk.total_trades}</dd></div>
            <div><dt>Total Win Rate</dt><dd>{((scalpRisk.total_win_rate ?? 0) * 100).toFixed(1)}%</dd></div>
            <div><dt>Kelly Fraction</dt><dd>{((scalpRisk.kelly_fraction ?? 0) * 100).toFixed(1)}%</dd></div>
            <div><dt>Daily Loss Hit</dt><dd style={{ color: scalpRisk.daily_loss_hit ? '#ff5b6b' : '#1fe3a3' }}>
              {scalpRisk.daily_loss_hit ? 'YES - STOPPED' : 'No'}
            </dd></div>
          </dl>
        ) : <p style={{ color: '#555', fontSize: 11 }}>No risk data</p>}
      </section>

      {/* ── AI BRAIN STATUS ── */}
      <section>
        <h2><Target size={13} /> AI Brain Status</h2>
        {stats && (
          <dl className="facts compact">
            <div><dt>Closed Candles</dt><dd>{stats.closed_candles}</dd></div>
            <div><dt>Active Signals</dt><dd>{stats.signals}</dd></div>
            <div><dt>Scalp Signals</dt><dd>{stats.scalp_signals}</dd></div>
            <div><dt>Blocked</dt><dd>{stats.scalp_blocked}</dd></div>
            <div><dt>Regime</dt><dd>{stats.fear_greed}</dd></div>
            <div><dt>Readability</dt><dd>{stats.readability_grade}</dd></div>
          </dl>
        )}
      </section>
    </div>
  )
}
