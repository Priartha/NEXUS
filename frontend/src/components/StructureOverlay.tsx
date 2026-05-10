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

  const labels = structure
    .filter((item) => item.kind === 'BOS' || item.kind === 'CHoCH')
    .slice(-16)
    .map((item) => {
      const x = chart.timeScale().timeToCoordinate(toChartTime(item.timestamp))
      const y = series.priceToCoordinate(item.price)
      if (x === null || y === null) return null
      return {
        ...item,
        x: Math.max(8, Math.min(width - 72, x)),
        y: Math.max(12, Math.min(height - 18, y)),
      }
    })
    .filter((item): item is StructureLabel & { x: number; y: number } => item !== null)

  return (
    <svg className="structure-overlay" width={width} height={height} aria-hidden="true">
      {labels.map((label) => (
        <g key={`${label.kind}-${label.timestamp}-${label.direction}`} transform={`translate(${label.x}, ${label.y})`}>
          <rect
            className={`structure-chip ${label.direction ?? 'neutral'} ${label.kind === 'CHoCH' ? 'choch' : 'bos'}`}
            x={-6}
            y={-14}
            width={label.kind === 'CHoCH' ? 54 : 36}
            height={18}
            rx={4}
          />
          <text x={0} y={0}>{label.kind}</text>
        </g>
      ))}
    </svg>
  )
}

