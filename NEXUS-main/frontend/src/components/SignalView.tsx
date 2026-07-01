import { memo } from 'react'
import { Gauge, Activity, Target, Zap, Settings } from 'lucide-react'
import { useChartStore } from '../store/chartStore'
import { formatPrice, formatTimestamp } from '../types/market'

export const SignalView = memo(function SignalView() {
  const candles = useChartStore((s) => s.candles)
  const lastApiCandle = useChartStore((s) => s.lastApiCandle)
  const metrics = useChartStore((s) => s.metrics)
  const regime = useChartStore((s) => s.regime)
  const projection = useChartStore((s) => s.projection)
  const sentiment = useChartStore((s) => s.sentiment)
  const aiIct = useChartStore((s) => s.aiIct)
  const liquidityEvents = useChartStore((s) => s.liquidityEvents)
  const scalpContext = useChartStore((s) => s.scalpContext)
  const primaryScalpSignal = scalpContext?.signals?.[0] ?? null
  const sentimentOverride = sentiment && sentiment.score > 0.3 && sentiment.confidence > 0.3
  const latest = candles.at(-1)
  const latestLiquidityEvent = liquidityEvents.at(-1)
  const fallbackSR = (() => {
    const recent = candles.slice(-48)
    if (recent.length < 5) return null
    const high = Math.max(...recent.map((c) => c.high))
    const low = Math.min(...recent.map((c) => c.low))
    const close = recent[recent.length - 1].close
    const pivot = (high + low + close) / 3
    return {
      resistance: +(high - (pivot - low) + pivot).toFixed(1),
      support: +(low - (high - pivot) + pivot).toFixed(1),
      projected_high: +(pivot + (high - low)).toFixed(1),
      projected_low: +(pivot - (high - low)).toFixed(1),
    }
  })()

  const srResistance = regime?.range_high ?? projection?.expected_high ?? fallbackSR?.resistance
  const srSupport = regime?.range_low ?? projection?.expected_low ?? fallbackSR?.support
  const srProjectedHigh = projection?.expected_high ?? fallbackSR?.projected_high
  const srProjectedLow = projection?.expected_low ?? fallbackSR?.projected_low

  return (
    <div className="panel-content">
      <section>
        <h2>Session</h2>
        <dl className="facts">
          <div><dt>Open</dt><dd>{formatPrice(latest?.open)}</dd></div>
          <div><dt>High</dt><dd>{formatPrice(latest?.high)}</dd></div>
          <div><dt>Low</dt><dd>{formatPrice(latest?.low)}</dd></div>
          <div><dt>Volume</dt><dd>{formatPrice(lastApiCandle?.volume ?? latest?.volume)}</dd></div>
          <div><dt>Updated</dt><dd>{formatTimestamp(lastApiCandle?.timestamp)}</dd></div>
        </dl>
      </section>

      <section>
        <h2><Gauge size={13} /> Signal Math</h2>
        <dl className="facts compact">
          <div><dt>ATR14</dt><dd>{formatPrice(metrics?.atr14)}</dd></div>
          <div><dt>VWAP</dt><dd>{formatPrice(metrics?.vwap)}</dd></div>
          <div><dt>RSI14</dt><dd>{metrics ? metrics.rsi14.toFixed(1) : '--'}</dd></div>
          <div><dt>Expected Move</dt><dd>{formatPrice(metrics?.expected_move)}</dd></div>
          <div><dt>Bias</dt><dd>{metrics?.institutional_bias ?? '--'}</dd></div>
          <div><dt>Liquidity</dt><dd>{latestLiquidityEvent ? `${(latestLiquidityEvent.engineered_score * 100).toFixed(0)}%` : '--'}</dd></div>
          <div><dt>Sentiment</dt><dd>{sentiment?.label ?? '--'} {sentiment ? `${(sentiment.confidence * 100).toFixed(0)}%` : ''}</dd></div>
          <div><dt>Expected Range</dt><dd>{formatPrice(projection?.expected_low)} - {formatPrice(projection?.expected_high)}</dd></div>
        </dl>
        <div className="signal-notes">
          {regime?.reason && <p className="note">{regime.reason}</p>}
          {sentiment?.summary && <p className="note">{sentiment.summary}</p>}
        </div>
      </section>

      {regime && (
        <section>
          <h2><Activity size={13} /> Regime Detail</h2>
          <dl className="facts compact">
            <div><dt>Phase</dt><dd>{regime.phase.replaceAll('_', ' ')}</dd></div>
            <div><dt>Bias</dt><dd className={regime.bias === 'bullish' ? 'bullish' : regime.bias === 'bearish' ? 'bearish' : ''}>{regime.bias} {sentimentOverride ? <span className="bias-source sentiment">(sentiment)</span> : <span className="bias-source technical">(technical)</span>}</dd></div>
            <div><dt>Confidence</dt><dd>{(regime.confidence * 100).toFixed(0)}%</dd></div>
            <div><dt>Volume State</dt><dd className={`vol-${regime.volume_state}`}>{regime.volume_state}</dd></div>
            <div><dt>Efficiency</dt><dd>{regime.efficiency_ratio.toFixed(2)}</dd></div>
            <div><dt>ATR Compression</dt><dd>{regime.atr_compression.toFixed(2)}</dd></div>
            <div><dt>Width %</dt><dd>{(regime.width_pct * 100).toFixed(1)}%</dd></div>
            <div><dt>Range High</dt><dd>{formatPrice(regime.range_high)}</dd></div>
            <div><dt>Range Low</dt><dd>{formatPrice(regime.range_low)}</dd></div>
            {primaryScalpSignal && (
              <div><dt>Trend Aligned</dt><dd className={(primaryScalpSignal.signal_type.includes('LONG') && regime.bias === 'bullish') || (primaryScalpSignal.signal_type.includes('SHORT') && regime.bias === 'bearish') ? 'bullish' : 'trend-blocked'}>{(primaryScalpSignal.signal_type.includes('LONG') && regime.bias === 'bullish') || (primaryScalpSignal.signal_type.includes('SHORT') && regime.bias === 'bearish') ? 'YES' : 'BLOCKED'}</dd></div>
            )}
          </dl>
        </section>
      )}

      {(srResistance || srSupport) && (
        <section>
          <h2><Target size={13} /> Support & Resistance</h2>
          <div className="sr-grid">
            <div className="sr-item resistance">
              <span className="sr-label">Resistance</span>
              <strong className="sr-value">${formatPrice(srResistance)}</strong>
            </div>
            <div className="sr-item">
              <span className="sr-label">Projected High</span>
              <strong className="sr-value">${formatPrice(srProjectedHigh)}</strong>
            </div>
            <div className="sr-item">
              <span className="sr-label">Projected Low</span>
              <strong className="sr-value">${formatPrice(srProjectedLow)}</strong>
            </div>
            <div className="sr-item support">
              <span className="sr-label">Support</span>
              <strong className="sr-value">${formatPrice(srSupport)}</strong>
            </div>
          </div>
        </section>
      )}

      {latestLiquidityEvent && (
        <section>
          <h2><Zap size={13} /> Liquidity Event</h2>
          <dl className="facts compact">
            <div><dt>Side</dt><dd>{latestLiquidityEvent.side.replace('_', ' ')}</dd></div>
            <div><dt>Depth</dt><dd>{formatPrice(latestLiquidityEvent.sweep_depth)}</dd></div>
            <div><dt>Displacement</dt><dd>{(latestLiquidityEvent.displacement * 100).toFixed(0)}%</dd></div>
            <div><dt>Engineered</dt><dd>{(latestLiquidityEvent.engineered_score * 100).toFixed(0)}%</dd></div>
            <div><dt>Reclaimed</dt><dd>{latestLiquidityEvent.reclaimed ? 'Yes' : 'No'}</dd></div>
            <div><dt>Sweep Price</dt><dd>{formatPrice(latestLiquidityEvent.sweep_price)}</dd></div>
          </dl>
          {latestLiquidityEvent.reason && (
            <p className="note" style={{ marginTop: 6 }}>{latestLiquidityEvent.reason}</p>
          )}
        </section>
      )}

      {aiIct && aiIct.entry != null && aiIct.stop_loss != null && aiIct.direction !== 'neutral' && (
        <section>
          <h2><Target size={13} /> Trade Levels</h2>
          <div className="trade-levels">
            <div className="tl-entry"><span className="tl-label">Entry</span><strong className="tl-value">${formatPrice(aiIct.entry)}</strong></div>
            <div className="tl-stop"><span className="tl-label">Stop Loss</span><strong className="tl-value">${formatPrice(aiIct.stop_loss)}</strong></div>
            {aiIct.take_profit != null && <div className="tl-target"><span className="tl-label">TP</span><strong className="tl-value">${formatPrice(aiIct.take_profit)}</strong></div>}
            <div className="tl-risk"><span className="tl-label">Risk</span><strong className="tl-value">${formatPrice(Math.abs(aiIct.entry - aiIct.stop_loss))}</strong></div>
          </div>
        </section>
      )}

      <section>
        <h2><Settings size={13} /> Active Strategy</h2>
        <dl className="facts compact">
          <div><dt>Stop Loss</dt><dd>0.5× ATR</dd></div>
          <div><dt>Breakeven</dt><dd>@ 0.5R</dd></div>
          <div><dt>TP1 / TP2</dt><dd>{(() => { if (!regime) return '1.0R / 1.5R'; if (regime.phase === 'range_bound') return '0.5R / 1.0R'; if (regime.phase === 'consolidation') return '0.3R / 0.6R'; if (regime.phase === 'trending') return '1.0R / 2.0R'; return '0.7R / 1.4R'; })()}</dd></div>
          <div><dt>Regime Context</dt><dd>{regime ? `TP tightened for ${regime.phase.replaceAll('_', ' ')}` : '--'}</dd></div>
          <div><dt>Trend Alignment</dt><dd>{regime && regime.bias !== 'neutral' ? `Longs only in ${regime.bias === 'bullish' ? 'bullish' : 'bearish'} bias` : 'No active bias'}</dd></div>
          <div><dt>Max Hold</dt><dd>12 bars (1h)</dd></div>
          <div><dt>ADX Filter</dt><dd>Yes (&gt;20)</dd></div>
          <div><dt>Limit Orders</dt><dd>Yes</dd></div>
          <div><dt>Min Confidence</dt><dd>55%</dd></div>
          <div><dt>Cooldown</dt><dd>12 candles</dd></div>
        </dl>
      </section>
    </div>
  )
})
