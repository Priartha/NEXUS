import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import type { TradeSignal } from '../types/market'
import { toChartTime } from '../types/market'

interface SignalOverlayProps {
  chart: IChartApi | null
  series: ISeriesApi<'Candlestick'> | null
  width: number
  height: number
  version: number
  signals: TradeSignal[]
}

interface SignalLine {
  id: string
  className: string
  label: string
  top: number
  left: number
  width: number
}

interface SignalBadge {
  id: string
  className: string
  label: string
  top: number
  left: number
}

export function SignalOverlay({ chart, series, width, height, version, signals }: SignalOverlayProps) {
  void version

  if (!chart || !series || width <= 0 || height <= 0) return null

  const chartApi = chart
  const candleSeries = series
  const timeScale = chartApi.timeScale()
  const lines: SignalLine[] = []
  const badges: SignalBadge[] = []

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

  function addLine(signal: TradeSignal, kind: 'entry' | 'exit' | 'sl', price: number) {
    const x = xFor(signal.timestamp)
    const y = yFor(price)
    if (x === null || y === null) return

    const labelPrefix = kind === 'entry'
      ? 'ENTRY'
      : kind === 'exit'
        ? `TP 1:${signal.risk_reward?.toFixed(0) ?? 3}`
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
    addLine(signal, 'exit', signal.exit_price)
    addLine(signal, 'sl', signal.trailing_stop ?? signal.stop_loss)

    const x = xFor(signal.timestamp)
    const y = yFor(signal.entry)
    if (x !== null && y !== null) {
      badges.push({
        id: signal.id,
        className: `signal-badge ${signal.side}`,
        label: `${signal.side.toUpperCase()} ${(signal.confidence * 100).toFixed(0)}%`,
        top: Math.max(12, Math.min(height - 28, y - 16)),
        left: Math.max(12, Math.min(width - 120, x + 8)),
      })
    }
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
      {badges.map((badge) => (
        <div key={badge.id} className={badge.className} style={{ top: badge.top, left: badge.left }}>
          {badge.label}
        </div>
      ))}
    </div>
  )
}
