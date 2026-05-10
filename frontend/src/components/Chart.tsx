import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import { useChartStore } from '../store/chartStore'
import { toChartTime, type TradeSignal } from '../types/market'
import { SignalOverlay } from './SignalOverlay'
import { StructureOverlay } from './StructureOverlay'
import { ZoneRenderer } from './ZoneRenderer'

type CandleData = {
  time: Time
  open: number
  high: number
  low: number
  close: number
}

type LineData = {
  time: Time
  value: number
}

const INITIAL_VISIBLE_BARS = 140
const RIGHT_OFFSET_BARS = 8

export function Chart({ targetRiskReward }: { targetRiskReward: number | 'best' }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const ema9Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema23Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema99Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const [chartApi, setChartApi] = useState<IChartApi | null>(null)
  const [seriesApi, setSeriesApi] = useState<ISeriesApi<'Candlestick'> | null>(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [version, setVersion] = useState(0)
  const [showMarks, setShowMarks] = useState(true)
  const [showStructure, setShowStructure] = useState(true)
  const [showEMAs, setShowEMAs] = useState(true)
  const fittedRef = useRef(false)

  const candles = useChartStore((state) => state.candles)
  const fvgs = useChartStore((state) => state.fvgs)
  const orderBlocks = useChartStore((state) => state.orderBlocks)
  const liquidity = useChartStore((state) => state.liquidity)
  const structure = useChartStore((state) => state.structure)
  const aiIct = useChartStore((state) => state.aiIct)
  const featuredSignals = useMemo<TradeSignal[]>(() => {
    if (
      !aiIct ||
      aiIct.direction === 'neutral' ||
      aiIct.grade === 'NO_TRADE' ||
      aiIct.entry == null ||
      aiIct.stop_loss == null
    ) {
      return []
    }
    const side = aiIct.direction === 'bullish' ? 'buy' : 'sell'
    const risk = Math.abs(aiIct.entry - aiIct.stop_loss)
    const selectedRr = targetRiskReward === 'best' ? aiIct.risk_reward ?? 3 : targetRiskReward
    const exitPrice = side === 'buy'
      ? aiIct.entry + risk * selectedRr
      : aiIct.entry - risk * selectedRr
    return [
      {
        id: `ai-${aiIct.timeframe}-${aiIct.timestamp}`,
        timestamp: aiIct.timestamp,
        side,
        entry: aiIct.entry,
        stop_loss: aiIct.stop_loss,
        exit_price: exitPrice,
        risk_reward: selectedRr,
        confidence: aiIct.confidence,
        reason: aiIct.summary,
        status: aiIct.readiness === 'avoid' ? 'pending' : 'open',
        institutional_score: aiIct.setup_score,
        liquidity_score: aiIct.setup_score,
        bias_score: aiIct.setup_score,
        expected_move: Math.abs(exitPrice - aiIct.entry),
        model: aiIct.model ?? aiIct.provider,
      },
    ]
  }, [aiIct, targetRiskReward])

  function focusRecent() {
    if (!chartRef.current || candles.length === 0) return
    const from = Math.max(0, candles.length - INITIAL_VISIBLE_BARS)
    chartRef.current.timeScale().setVisibleLogicalRange({
      from,
      to: candles.length + RIGHT_OFFSET_BARS,
    })
    setVersion((value) => value + 1)
  }

  function fitAll() {
    chartRef.current?.timeScale().fitContent()
    setVersion((value) => value + 1)
  }

  function calculateEMA(data: CandleData[], period: number): LineData[] {
    if (data.length < period) return []
    const ema: LineData[] = []
    const multiplier = 2 / (period + 1)
    let emaValue = data.slice(0, period).reduce((sum, candle) => sum + candle.close, 0) / period
    ema.push({ time: data[period - 1].time, value: emaValue })
    for (let i = period; i < data.length; i++) {
      emaValue = (data[i].close - emaValue) * multiplier + emaValue
      ema.push({ time: data[i].time, value: emaValue })
    }
    return ema
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: '#080b10' },
        textColor: '#c5ccd8',
        fontFamily: 'Inter, Segoe UI, sans-serif',
      },
      grid: {
        vertLines: { color: '#161c25' },
        horzLines: { color: '#161c25' },
      },
      rightPriceScale: {
        borderColor: '#242d3a',
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: '#242d3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: RIGHT_OFFSET_BARS,
        barSpacing: 8,
        minBarSpacing: 3,
      },
      crosshair: {
        vertLine: { color: '#718096', style: LineStyle.Dashed },
        horzLine: { color: '#718096', style: LineStyle.Dashed },
      },
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

    const ema9Series = chart.addSeries(LineSeries, {
      color: '#ff6b6b',
      lineWidth: 2,
      title: 'EMA 9',
    })
    const ema23Series = chart.addSeries(LineSeries, {
      color: '#4ecdc4',
      lineWidth: 2,
      title: 'EMA 23',
    })
    const ema99Series = chart.addSeries(LineSeries, {
      color: '#45b7d1',
      lineWidth: 2,
      title: 'EMA 99',
    })

    chartRef.current = chart
    seriesRef.current = series
    ema9Ref.current = ema9Series
    ema23Ref.current = ema23Series
    ema99Ref.current = ema99Series
    markersRef.current = createSeriesMarkers(series, [], { autoScale: true })
    setChartApi(chart)
    setSeriesApi(series)

    const resize = () => {
      const next = {
        width: container.clientWidth,
        height: container.clientHeight,
      }
      chart.resize(next.width, next.height)
      setDimensions(next)
      setVersion((value) => value + 1)
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(container)
    chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      setVersion((value) => value + 1)
    })
    resize()

    return () => {
      resizeObserver.disconnect()
      markersRef.current?.detach()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      ema9Ref.current = null
      ema23Ref.current = null
      ema99Ref.current = null
      markersRef.current = null
      setChartApi(null)
      setSeriesApi(null)
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return
    seriesRef.current.setData(candles)
    if (!fittedRef.current) {
      const from = Math.max(0, candles.length - INITIAL_VISIBLE_BARS)
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from,
        to: candles.length + RIGHT_OFFSET_BARS,
      })
      fittedRef.current = true
    }
    setVersion((value) => value + 1)
  }, [candles])

  useEffect(() => {
    const markers: SeriesMarker<Time>[] = []

    featuredSignals.forEach((signal) => {
      markers.push({
        time: toChartTime(signal.timestamp),
        position: signal.side === 'buy' ? 'belowBar' : 'aboveBar',
        shape: signal.side === 'buy' ? 'arrowUp' : 'arrowDown',
        color: signal.side === 'buy' ? '#1fe3a3' : '#ff5b6b',
        text: `${signal.side === 'buy' ? 'BUY' : 'SELL'} ${(signal.confidence * 100).toFixed(0)}%`,
      })
    })

    markersRef.current?.setMarkers(markers)
  }, [featuredSignals])

  useEffect(() => {
    if (!showEMAs || candles.length === 0) {
      ema9Ref.current?.setData([])
      ema23Ref.current?.setData([])
      ema99Ref.current?.setData([])
      return
    }
    const ema9Data = calculateEMA(candles, 9)
    const ema23Data = calculateEMA(candles, 23)
    const ema99Data = calculateEMA(candles, 99)
    ema9Ref.current?.setData(ema9Data)
    ema23Ref.current?.setData(ema23Data)
    ema99Ref.current?.setData(ema99Data)
  }, [showEMAs, candles])

  return (
    <div className="chart-shell">
      <div ref={containerRef} className="chart-canvas" />
      {showMarks ? (
        <ZoneRenderer
          chart={chartApi}
          series={seriesApi}
          width={dimensions.width}
          height={dimensions.height}
          version={version}
          fvgs={fvgs.slice(-5)}
          orderBlocks={orderBlocks.slice(-4)}
          liquidity={liquidity.slice(-4)}
        />
      ) : null}
      {showStructure ? (
        <StructureOverlay
          chart={chartApi}
          series={seriesApi}
          width={dimensions.width}
          height={dimensions.height}
          version={version}
          structure={structure.slice(-18)}
        />
      ) : null}
      <SignalOverlay
        chart={chartApi}
        series={seriesApi}
        width={dimensions.width}
        height={dimensions.height}
        version={version}
        signals={featuredSignals}
      />
      <div className="chart-controls">
        <button type="button" onClick={focusRecent}>Latest</button>
        <button type="button" onClick={fitAll}>Fit</button>
        <button type="button" className={showMarks ? 'active' : ''} onClick={() => setShowMarks((value) => !value)}>
          ICT Marks
        </button>
        <button type="button" className={showStructure ? 'active' : ''} onClick={() => setShowStructure((value) => !value)}>
          Structure
        </button>
        <button type="button" className={showEMAs ? 'active' : ''} onClick={() => setShowEMAs((value) => !value)}>
          EMAs
        </button>
      </div>
    </div>
  )
}
