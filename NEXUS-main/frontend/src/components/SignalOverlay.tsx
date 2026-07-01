import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import type { TradeSignal } from '../types/market'
import { toChartTime } from '../types/market'

type ChartTradeSignal = TradeSignal & {
  entry_zone_low?: number
  entry_zone_high?: number
  target_2?: number
}

interface SignalOverlayProps {
  chart: IChartApi | null
  series: ISeriesApi<'Candlestick'> | null
  width: number
  height: number
  version: number
  signals: ChartTradeSignal[]
}

interface SignalLine {
  id: string
  className: string
  label: string
  top: number
  left: number
  width: number
}

import { memo } from 'react'
export const SignalOverlay = memo(function SignalOverlay({ chart, series, width, height, version, signals }: SignalOverlayProps) {
  void version

  if (!chart || !series || width <= 0 || height <= 0) return null

  const chartApi = chart
  const candleSeries = series
  const timeScale = chartApi.timeScale()
  const lines: SignalLine[] = []

  function xFor(timestamp: number) {
    const coordinate = timeScale.timeToCoordinate(toChartTime(timestamp))
    if (coordinate === null) return null
    return Math.max(0, Math.min(width, coordinate))
  }

  function yFor(price: number) {
    const coordinate = candleSeries.priceToCoordinate(price)
    if (coordinate === null) return null
    return Math.max(0, Math.min(height, coordinate))
  }

  function formatPrice(price: number) {
    return `$${price.toLocaleString(undefined, { maximumFractionDigits: 1 })}`
  }

  function addLine(signal: ChartTradeSignal, kind: 'entry' | 'tp1' | 'tp2' | 'sl', price: number) {
    const x = xFor(signal.timestamp)
    const y = yFor(price)
    if (x === null || y === null) return

    const labelPrefix = kind === 'entry'
      ? signal.entry_zone_low && signal.entry_zone_high
        ? `ENTRY ${formatPrice(signal.entry_zone_low)}-${formatPrice(signal.entry_zone_high)}`
        : `ENTRY ${formatPrice(price)}`
      : kind === 'tp1'
        ? `TP1 ${formatPrice(price)}`
        : kind === 'tp2'
          ? `TP2 ${formatPrice(price)}`
        : 'SL'
    lines.push({
      id: `${signal.id}-${kind}`,
      className: `signal-line ${kind} ${signal.side}`,
      label: labelPrefix,
      top: y,
      left: x,
      width: Math.max(36, width - x),
    })
  }

  signals.forEach((signal) => {
    addLine(signal, 'entry', signal.entry)
    addLine(signal, 'tp1', signal.exit_price)
    if (signal.target_2) {
      addLine(signal, 'tp2', signal.target_2)
    }
    addLine(signal, 'sl', signal.trailing_stop ?? signal.stop_loss)
  })

  return (
    <div className="signal-overlay" aria-hidden="true">
      {lines.map((line) => (
        <div
          key={line.id}
          className={line.className}
          style={{
            top: line.top,
            left: line.left,
            width: line.width,
          }}
        >
          <span>{line.label}</span>
        </div>
      ))}
    </div>
  )
})
