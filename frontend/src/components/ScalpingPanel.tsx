import { memo, useMemo } from 'react'
import { Activity, AlertTriangle, BarChart3, Clock, Crosshair, Layers, Shield, Target, TrendingDown, TrendingUp, Zap } from 'lucide-react'
import { useChartStore } from '../store/chartStore'

export const ScalpingPanel = memo(function ScalpingPanel() {
  const scalp = useChartStore((state) => state.scalpContext)
  const scalpRisk = useChartStore((state) => state.scalpRisk)
  const regime = useChartStore((state) => state.regime)

  const data = useMemo(() => {
    if (!scalp) return null

    return {
      rsi3: scalp.rsi_3 ?? 50,
      rsi3Zone: (scalp.rsi_3 ?? 50) < 20 ? 'extreme_oversold' : (scalp.rsi_3 ?? 50) < 30 ? 'oversold' : (scalp.rsi_3 ?? 50) > 80 ? 'extreme_overbought' : (scalp.rsi_3 ?? 50) > 70 ? 'overbought' : 'neutral',
      orderFlow: scalp.order_flow,
      funding: scalp.funding,
      openInterest: scalp.open_interest,
      vwap: scalp.vwap,
      volumeProfile: scalp.volume_profile,
      liquidationLevels: scalp.liquidation_levels ?? [],
      liquiditySweeps: scalp.liquidity_sweeps ?? [],
      signals: scalp.signals ?? [],
      blockers: scalp.trade_blocked_reasons ?? [],
      spotVolumeOk: scalp.spot_volume_ok,
      macroBlocked: scalp.macro_event_block,
      risk: scalpRisk,
      bias: regime?.bias ?? 'neutral',
    }
  }, [scalp, scalpRisk, regime])

  if (!data) {
    return (
      <div className="scalping-panel">
        <div className="scalping-empty">Waiting for scalping data...</div>
      </div>
    )
  }

  const getRsi3Color = (rsi: number) =>
    rsi < 20 ? '#22c55e' : rsi < 30 ? '#3b82f6' : rsi > 80 ? '#ef4444' : rsi > 70 ? '#f59e0b' : '#94a3b8'

  const getConfidenceColor = (conf: string) =>
    conf === 'HIGH' ? '#22c55e' : conf === 'MEDIUM' ? '#f59e0b' : '#ef4444'

  const getSignalTypeColor = (type: string) => {
    if (type.includes('LONG')) return '#22c55e'
    if (type.includes('SHORT')) return '#ef4444'
    return '#94a3b8'
  }
  const isTrendAligned = (type: string, bias: string) => {
    if (bias === 'neutral') return true
    if (type.includes('LONG') && bias === 'bullish') return true
    if (type.includes('SHORT') && bias === 'bearish') return true
    return false
  }

  return (
    <div className="scalping-panel">
      {/* Trade Blockers */}
      {data.blockers.length > 0 && (
        <div className="scalping-section scalping-blockers">
          <h3 className="scalping-section-title">
            <AlertTriangle size={14} color="#ef4444" /> Trade Blockers
          </h3>
          <div className="blocker-list">
            {data.blockers.map((reason, i) => (
              <div key={i} className="blocker-item">
                <span className="blocker-dot" />
                <span className="blocker-text">{reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* RSI (3) Exhaustion */}
      <div className="scalping-section">
        <h3 className="scalping-section-title">
          <Zap size={14} /> RSI (3) Exhaustion
        </h3>
        <div className="scalping-grid">
          <div className="scalping-metric">
            <span className="scalping-label">RSI (3-period)</span>
            <span className="scalping-value" style={{ color: getRsi3Color(data.rsi3) }}>
              {data.rsi3.toFixed(1)}
            </span>
            <span className="scalping-sub">{data.rsi3Zone.replace('_', ' ')}</span>
          </div>
          <div className="scalping-metric">
            <span className="scalping-label">RSI Bar</span>
            <div className="scalping-bar-container">
              <div
                className="scalping-bar"
                style={{
                  width: `${data.rsi3}%`,
                  background: getRsi3Color(data.rsi3),
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Order Flow */}
      {data.orderFlow && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Activity size={14} /> Order Flow
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">Delta</span>
              <span className="scalping-value" style={{ color: data.orderFlow.delta > 0 ? '#22c55e' : '#ef4444' }}>
                {data.orderFlow.delta > 0 ? '+' : ''}{data.orderFlow.delta.toFixed(4)}
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">CVD</span>
              <span className="scalping-value" style={{ color: data.orderFlow.cvd > 0 ? '#22c55e' : '#ef4444' }}>
                {data.orderFlow.cvd.toFixed(4)}
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">CVD Slope</span>
              <span className="scalping-value" style={{ color: data.orderFlow.cvd_slope > 0 ? '#22c55e' : '#ef4444' }}>
                {data.orderFlow.cvd_slope > 0 ? '+' : ''}{data.orderFlow.cvd_slope.toFixed(4)}
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Absorption</span>
              <span className="scalping-value">{data.orderFlow.absorption_ratio.toFixed(3)}</span>
              <span className="scalping-sub">{data.orderFlow.absorption_ratio < 0.35 ? 'Low — directional' : 'High — absorption'}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Vol Delta Ratio</span>
              <span className="scalping-value">{data.orderFlow.volume_delta_ratio.toFixed(3)}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Footprint Imb</span>
              <span className="scalping-value">{data.orderFlow.footprint_imbalance.toFixed(3)}</span>
            </div>
          </div>
        </div>
      )}

      {/* VWAP */}
      {data.vwap && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Layers size={14} /> VWAP Bands
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">VWAP</span>
              <span className="scalping-value">${data.vwap.vwap.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Deviation</span>
              <span className="scalping-value">{data.vwap.price_deviation_pct.toFixed(3)}%</span>
              <span className="scalping-sub">{data.vwap.is_compressed ? 'Compressed — expansion imminent' : 'Normal'}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">+1 SD</span>
              <span className="scalping-value">${data.vwap.upper_band_1sd.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">-1 SD</span>
              <span className="scalping-value">${data.vwap.lower_band_1sd.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">+2 SD</span>
              <span className="scalping-value">${data.vwap.upper_band_2sd.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">-2 SD</span>
              <span className="scalping-value">${data.vwap.lower_band_2sd.toLocaleString()}</span>
            </div>
          </div>
        </div>
      )}

      {/* Volume Profile */}
      {data.volumeProfile && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <BarChart3 size={14} /> Volume Profile
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">POC</span>
              <span className="scalping-value">${data.volumeProfile.poc.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">VAH</span>
              <span className="scalping-value">${data.volumeProfile.vah.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">VAL</span>
              <span className="scalping-value">${data.volumeProfile.val.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">VA Width</span>
              <span className="scalping-value">{data.volumeProfile.value_area_width_pct.toFixed(3)}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Funding Rate */}
      {data.funding && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Clock size={14} /> Funding Rate
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">Current</span>
              <span className="scalping-value" style={{ color: data.funding.is_extreme ? '#ef4444' : '#94a3b8' }}>
                {(data.funding.current_rate * 100).toFixed(4)}%
              </span>
              {data.funding.is_extreme && <span className="scalping-sub" style={{ color: '#ef4444' }}>EXTREME</span>}
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Projected 8H</span>
              <span className="scalping-value">{(data.funding.projected_8h * 100).toFixed(4)}%</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Bias</span>
              <span className="scalping-value" style={{ color: data.funding.contrarian_bias === 'bullish' ? '#22c55e' : data.funding.contrarian_bias === 'bearish' ? '#ef4444' : '#94a3b8' }}>
                {data.funding.contrarian_bias.toUpperCase()}
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Next Reset</span>
              <span className="scalping-value">
                {data.funding.next_reset_ms ? new Date(data.funding.next_reset_ms).toLocaleTimeString() : '--'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Open Interest */}
      {data.openInterest && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <TrendingUp size={14} /> Open Interest
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">Current OI</span>
              <span className="scalping-value">{data.openInterest.current_oi.toLocaleString()}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Change</span>
              <span className="scalping-value" style={{ color: data.openInterest.oi_change_pct > 0 ? '#22c55e' : '#ef4444' }}>
                {data.openInterest.oi_change_pct > 0 ? '+' : ''}{data.openInterest.oi_change_pct.toFixed(2)}%
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Trend</span>
              <span className="scalping-value">{data.openInterest.oi_trend}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Momentum</span>
              <span className="scalping-value" style={{ color: data.openInterest.momentum_confirmation ? '#22c55e' : '#94a3b8' }}>
                {data.openInterest.momentum_confirmation ? 'CONFIRMED' : 'NEUTRAL'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Liquidity Sweeps */}
      {data.liquiditySweeps.length > 0 && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Crosshair size={14} /> Liquidity Sweeps
          </h3>
          <div className="scalping-sweeps">
            {data.liquiditySweeps.map((sweep, i) => (
              <div key={i} className={`scalping-sweep ${sweep.side}`}>
                <div className="sweep-header">
                  <span className={`sweep-side ${sweep.side}`}>
                    {sweep.side === 'long' ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                    {sweep.side.toUpperCase()}
                  </span>
                  <span className="sweep-strength">{(sweep.strength * 100).toFixed(0)}%</span>
                </div>
                <div className="sweep-details">
                  <span>Level: ${sweep.level.toLocaleString()}</span>
                  <span>Type: {sweep.sweep_type}</span>
                  <span>{sweep.reclaimed ? 'Reclaimed' : 'Not reclaimed'}</span>
                  {sweep.entry_trigger && <span style={{ color: '#22c55e' }}>ENTRY TRIGGER</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Signals */}
      {data.signals.length > 0 && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Target size={14} /> Scalp Signals
          </h3>
          <div className="scalping-signals">
            {data.signals.map((signal) => (
              <div key={signal.id} className="scalping-signal">
                <div className="signal-header">
                  <span className="signal-type" style={{ color: getSignalTypeColor(signal.signal_type) }}>
                    {signal.signal_type}
                  </span>
                  {data.bias !== 'neutral' && (
                    <span className={`signal-trend ${isTrendAligned(signal.signal_type, data.bias) ? 'aligned' : 'blocked'}`}>
                      {isTrendAligned(signal.signal_type, data.bias) ? 'TREND' : 'BLOCKED'}
                    </span>
                  )}
                  <span className="signal-confidence" style={{ color: getConfidenceColor(signal.confidence) }}>
                    {signal.confidence}
                  </span>
                </div>
                <div className="signal-zones">
                  <div className="zone-row">
                    <span className="zone-label">Entry:</span>
                    <span className="zone-value">${signal.entry_zone_low.toLocaleString()} - ${signal.entry_zone_high.toLocaleString()}</span>
                  </div>
                  <div className="zone-row">
                    <span className="zone-label">SL:</span>
                    <span className="zone-value" style={{ color: '#ef4444' }}>${signal.sl_level.toLocaleString()}</span>
                  </div>
                  <div className="zone-row">
                    <span className="zone-label">T1 (70%):</span>
                    <span className="zone-value" style={{ color: '#22c55e' }}>${signal.target_1.toLocaleString()}</span>
                  </div>
                  <div className="zone-row">
                    <span className="zone-label">T2 (30%):</span>
                    <span className="zone-value" style={{ color: '#22c55e' }}>${signal.target_2.toLocaleString()}</span>
                  </div>
                </div>
                <div className="signal-meta">
                  {signal.leverage > 0 && <span>Lev: {signal.leverage}x</span>}
                  <span>RR: 1:{signal.risk_reward.toFixed(2)}</span>
                  <span>Max: {signal.max_hold_minutes}m</span>
                </div>
                <div className="signal-reason">{signal.reason}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Risk Summary */}
      {data.risk && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Shield size={14} /> Risk Status
          </h3>
          <div className="scalping-grid">
            <div className="scalping-metric">
              <span className="scalping-label">Daily PnL</span>
              <span className="scalping-value" style={{ color: data.risk.daily_pnl >= 0 ? '#22c55e' : '#ef4444' }}>
                ${data.risk.daily_pnl.toFixed(2)}
              </span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Daily Trades</span>
              <span className="scalping-value">{data.risk.daily_trades}</span>
              <span className="scalping-sub">W: {data.risk.daily_wins} / L: {data.risk.daily_losses}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Win Rate</span>
              <span className="scalping-value">{(data.risk.daily_win_rate * 100).toFixed(1)}%</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Daily Loss</span>
              <span className="scalping-value" style={{ color: data.risk.daily_loss_hit ? '#ef4444' : '#94a3b8' }}>
                {data.risk.daily_loss_pct.toFixed(2)}% / {data.risk.max_daily_loss_pct.toFixed(2)}%
              </span>
              {data.risk.daily_loss_hit && <span className="scalping-sub" style={{ color: '#ef4444' }}>STOPPED</span>}
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Consec. Losses</span>
              <span className="scalping-value">{data.risk.consecutive_losses}</span>
            </div>
            <div className="scalping-metric">
              <span className="scalping-label">Open Positions</span>
              <span className="scalping-value">{data.risk.total_open} / {data.risk.max_positions}</span>
              <span className="scalping-sub">Futures: {data.risk.open_futures}</span>
            </div>
          </div>
        </div>
      )}

      {/* Liquidity Levels */}
      {data.liquidationLevels.length > 0 && (
        <div className="scalping-section">
          <h3 className="scalping-section-title">
            <Crosshair size={14} /> Liquidation Levels
          </h3>
          <div className="scalping-liquidations">
            {data.liquidationLevels.slice(0, 6).map((level, i) => (
              <div key={i} className={`liq-level ${level.side}`}>
                <span className="liq-price">${level.price.toLocaleString()}</span>
                <span className="liq-distance">{level.distance_pct.toFixed(2)}%</span>
                <span className="liq-strength">{(level.cluster_strength * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
})
