import { useEffect, useRef, useMemo } from 'react'
import { CandlestickSeries, ColorType, createChart, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts'
import type { MtfSnapshot } from '../types/market'

interface Props {
  data: Record<string, MtfSnapshot> | null
}

const TF_ORDER = ['1m', '5m', '15m', '1h']

function MiniChart({ tf, snap }: { tf: string; snap: MtfSnapshot }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const cdata = useMemo(() => {
    return snap.candles.map((c) => ({
      time: Math.floor(c.timestamp / 1000) as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
  }, [snap.candles])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 110,
      layout: {
        attributionLogo: false,
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#6a7689',
        fontFamily: 'Inter, Segoe UI, sans-serif',
        fontSize: 9,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.03)' },
      },
      rightPriceScale: {
        visible: true,
        borderColor: 'rgba(255,255,255,0.06)',
        scaleMargins: { top: 0.15, bottom: 0.15 },
        entireTextOnly: true,
      },
      timeScale: {
        visible: true,
        borderColor: 'rgba(255,255,255,0.06)',
        timeVisible: false,
        secondsVisible: false,
        fixRightEdge: true,
      },
      crosshair: { mode: 0, vertLine: { visible: false }, horzLine: { visible: false } },
      handleScroll: false,
      handleScale: false,
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#36c7a5',
      downColor: '#f1616d',
      borderUpColor: '#36c7a5',
      borderDownColor: '#f1616d',
      wickUpColor: '#36c7a5',
      wickDownColor: '#f1616d',
      priceFormat: { type: 'price', precision: 1, minMove: 0.5 },
    })
    chartRef.current = chart
    seriesRef.current = series
    const resize = () => chart.applyOptions({ width: container.clientWidth })
    const ro = new ResizeObserver(resize)
    ro.observe(container)
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null }
  }, [])

  useEffect(() => {
    if (seriesRef.current && cdata.length) {
      seriesRef.current.setData(cdata)
      chartRef.current?.timeScale().fitContent()
    }
  }, [cdata])

  const dir = snap.regime?.bias
  const dirClass = dir === 'bullish' ? 'bullish' : dir === 'bearish' ? 'bearish' : 'neutral'
  const bullishFvgs = snap.fvgs.filter((f) => f.direction === 'bullish').length
  const bearishFvgs = snap.fvgs.filter((f) => f.direction === 'bearish').length
  const bullishObs = snap.order_blocks.filter((b) => b.direction === 'bullish').length
  const bearishObs = snap.order_blocks.filter((b) => b.direction === 'bearish').length
  const aboveLiq = snap.liquidity.filter((l) => l.kind === 'equal_high').length
  const belowLiq = snap.liquidity.filter((l) => l.kind === 'equal_low').length

  return (
    <div className={`mtf-card ${dirClass}`}>
      <div className="mtf-header">
        <strong className="mtf-tf">{tf}</strong>
        {snap.current_price != null && (
          <span className="mtf-price">${snap.current_price.toFixed(1)}</span>
        )}
        {snap.regime && (
          <span className={`mtf-regime ${dirClass}`}>{snap.regime.phase}</span>
        )}
      </div>
      <div ref={containerRef} className="mtf-chart-container" />
      <div className="mtf-stats">
        <div className="mtf-stat-group">
          <span title="Fair Value Gaps">
            FVG <span className="bullish">▲{bullishFvgs}</span> <span className="bearish">▼{bearishFvgs}</span>
          </span>
          <span title="Order Blocks">
            OB <span className="bullish">▲{bullishObs}</span> <span className="bearish">▼{bearishObs}</span>
          </span>
          <span title="Liquidity levels">
            Liq <span className="bullish">↑{aboveLiq}</span> <span className="bearish">↓{belowLiq}</span>
          </span>
        </div>
        {snap.metrics && (
          <div className="mtf-metrics">
            <span>RSI {snap.metrics.rsi14.toFixed(1)}</span>
            <span>ATR ${snap.metrics.atr14.toFixed(1)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function MtfConfluence({ data }: Props) {
  const sortedTfs = useMemo(() => {
    if (!data) return []
    return TF_ORDER.filter((tf) => data[tf])
  }, [data])

  if (!data || sortedTfs.length === 0) {
    return <p className="empty-state">Waiting for multi-frame chart data...</p>
  }

  return (
    <div className="mtf-confluence">
      {sortedTfs.map((tf) => (
        <MiniChart key={tf} tf={tf} snap={data![tf]} />
      ))}
    </div>
  )
}
