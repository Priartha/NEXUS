import type { IChartApi, ISeriesApi } from 'lightweight-charts'
import type { FVG, LiquidityLevel, OrderBlock } from '../types/market'
import { formatPrice, toChartTime } from '../types/market'

interface ZoneRendererProps {
  chart: IChartApi | null
  series: ISeriesApi<'Candlestick'> | null
  width: number
  height: number
  version: number
  fvgs: FVG[]
  orderBlocks: OrderBlock[]
  liquidity: LiquidityLevel[]
}

interface Band {
  id: string
  className: string
  label: string
  top: number
  left: number
  width: number
  height: number
  kind: string
  direction: string
  count?: number
}

interface Line {
  id: string
  className: string
  label: string
  top: number
}

export function ZoneRenderer({
  chart,
  series,
  width,
  height,
  version,
  fvgs,
  orderBlocks,
  liquidity,
}: ZoneRendererProps) {
  void version

  if (!chart || !series || width <= 0 || height <= 0) return null

  const bands: Band[] = []
  const lines: Line[] = []
  const chartApi = chart
  const candleSeries = series
  const timeScale = chartApi.timeScale()

  function xFor(timestamp: number) {
    const coordinate = timeScale.timeToCoordinate(toChartTime(timestamp))
    if (coordinate === null) return 0
    return Math.max(0, Math.min(width, coordinate))
  }

  function yFor(price: number) {
    const coordinate = candleSeries.priceToCoordinate(price)
    if (coordinate === null) return null
    return Math.max(0, Math.min(height, coordinate))
  }

  function addBand(
    id: string,
    className: string,
    label: string,
    timestamp: number,
    topPrice: number,
    bottomPrice: number,
    kind: string,
    direction: string,
  ) {
    const topY = yFor(topPrice)
    const bottomY = yFor(bottomPrice)
    if (topY === null || bottomY === null) return
    const left = xFor(timestamp)
    const top = Math.min(topY, bottomY)
    bands.push({
      id,
      className,
      label,
      top,
      left,
      width: Math.max(16, width - left),
      height: Math.max(3, Math.abs(bottomY - topY)),
      kind,
      direction,
    })
  }

  fvgs.forEach((fvg) => {
    addBand(
      fvg.id,
      `zone zone-fvg zone-${fvg.direction}`,
      `${fvg.direction === 'bullish' ? 'Bull FVG' : 'Bear FVG'} ${formatPrice(fvg.bottom)}-${formatPrice(fvg.top)}`,
      fvg.timestamp,
      fvg.top,
      fvg.bottom,
      'FVG',
      fvg.direction,
    )
  })

  orderBlocks.forEach((block) => {
    addBand(
      block.id,
      `zone zone-ob zone-${block.direction}`,
      `${block.direction === 'bullish' ? 'Bull OB' : 'Bear OB'} ${formatPrice(block.bottom)}-${formatPrice(block.top)}`,
      block.timestamp,
      block.top,
      block.bottom,
      'OB',
      block.direction,
    )
  })

  const clusters = bands.reduce<Band[]>((result, band) => {
    const match = result.find((cluster) =>
      cluster.direction === band.direction &&
      Math.abs(cluster.top - band.top) < 24 &&
      Math.abs(cluster.left - band.left) < 56
    )
    if (match) {
      match.count = (match.count ?? 1) + 1
      match.label = `${match.count}× ${match.direction === 'bullish' ? 'Bull' : 'Bear'} ${match.kind}`
      match.width = Math.max(match.width, band.left + band.width - match.left)
      match.height = Math.max(match.height, band.height)
      return result
    }

    return [...result, { ...band, count: 1 }]
  }, [])

  liquidity.forEach((level) => {
    const y = yFor(level.price)
    if (y === null) return
    lines.push({
      id: level.id,
      className: `liquidity-line ${level.kind}`,
      label: `${level.kind === 'equal_high' ? 'EQH' : 'EQL'} ${formatPrice(level.price)}`,
      top: y,
    })
  })

  return (
    <div className="chart-overlay" aria-hidden="true">
      {clusters.map((band) => (
        <div
          key={band.id}
          className={band.className}
          style={{
            top: band.top,
            left: band.left,
            width: band.width,
            height: band.height,
          }}
        >
          <span>{band.label}</span>
          <span className="zone-count">{band.label.includes('+') ? 'cluster' : ''}</span>
        </div>
      ))}
      {lines.map((line) => (
        <div key={line.id} className={line.className} style={{ top: line.top }}>
          <span>{line.label}</span>
        </div>
      ))}
    </div>
  )
}
