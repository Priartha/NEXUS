import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import type { StructureLabel } from '../types/market'
import { toChartTime } from '../types/market'

interface StructureOverlayProps {
  chart: IChartApi | null
  series: ISeriesApi<'Candlestick'> | null
  width: number
  height: number
  version: number
  structure: StructureLabel[]
}

const SIGNAL_KINDS = ['BOS', 'CHoCH'] as const

const CHIP_COLORS: Record<string, { bg: string; text: string }> = {
  HH: { bg: 'rgba(31,227,163,0.7)', text: '#1fe3a3' },
  HL: { bg: 'rgba(31,227,163,0.4)', text: '#6ee7b7' },
  LH: { bg: 'rgba(255,91,107,0.4)', text: '#fca5a5' },
  LL: { bg: 'rgba(255,91,107,0.7)', text: '#ff5b6b' },
  BOS: { bg: 'rgba(138,180,248,0.7)', text: '#8ab4f8' },
  CHoCH: { bg: 'rgba(245,159,67,0.7)', text: '#f59f43' },
}

export function StructureOverlay({
  chart,
  series,
  width,
  height,
  version,
  structure,
}: StructureOverlayProps) {
  void version

  if (!chart || !series || width <= 0 || height <= 0) return null

  const chips = structure
    .slice(-20)
    .map((item) => {
      const x = chart.timeScale().timeToCoordinate(toChartTime(item.timestamp))
      const y = series.priceToCoordinate(item.price)
      if (x === null || y === null) return null
      return {
        ...item,
        x: Math.max(8, Math.min(width - 60, x)),
        y: Math.max(12, Math.min(height - 18, y)),
      }
    })
    .filter((item): item is StructureLabel & { x: number; y: number } => item !== null)

  return (
    <svg className="structure-overlay" width={width} height={height} aria-hidden="true">
      {chips.map((label) => {
        const colors = CHIP_COLORS[label.kind] ?? { bg: 'rgba(255,255,255,0.3)', text: '#ddd' }
        const isSignal = SIGNAL_KINDS.includes(label.kind as typeof SIGNAL_KINDS[number])
        const chipWidth = isSignal ? 54 : 36
        return (
          <g key={`${label.kind}-${label.timestamp}-${label.direction}`} transform={`translate(${label.x}, ${label.y})`}>
            <rect
              x={-6}
              y={-14}
              width={chipWidth}
              height={18}
              rx={4}
              fill={colors.bg}
              stroke={colors.text}
              strokeWidth={1}
              strokeOpacity={0.5}
            />
            <text
              x={0}
              y={0}
              fill={colors.text}
              fontSize={9}
              fontWeight={700}
              fontFamily="Inter, sans-serif"
            >
              {label.kind}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
