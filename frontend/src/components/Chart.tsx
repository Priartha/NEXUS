import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useChartStore } from '../store/chartStore'
import { DEMO_PATTERNS, toChartTime, type ChartCandle, type TradeSignal } from '../types/market'
import { SignalOverlay } from './SignalOverlay'
import { StructureOverlay } from './StructureOverlay'
import { ZoneRenderer } from './ZoneRenderer'

type CandleData = { time: Time; open: number; high: number; low: number; close: number }
type LineData = { time: Time; value: number }

const INITIAL_VISIBLE_BARS = 140
const RIGHT_OFFSET_BARS = 8

export function Chart({ targetRiskReward }: { targetRiskReward: number | 'best' }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const patternMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const ema9Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema23Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema99Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const [chartApi, setChartApi] = useState<IChartApi | null>(null)
  const [seriesApi, setSeriesApi] = useState<ISeriesApi<'Candlestick'> | null>(null)
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 })
  const [version, setVersion] = useState(0)
  const [showMarks, setShowMarks] = useState(true)
  const [showPatterns, setShowPatterns] = useState(true)
  const [showStructure, setShowStructure] = useState(true)
  const [showEMAs, setShowEMAs] = useState(true)
  const [tooltip, setTooltip] = useState<{
    x: number
    y: number
    data: ChartCandle | null
  } | null>(null)
  const fittedRef = useRef(false)

  const candles = useChartStore((state) => state.candles)
  const fvgs = useChartStore((state) => state.fvgs)
  const orderBlocks = useChartStore((state) => state.orderBlocks)
  const liquidity = useChartStore((state) => state.liquidity)
  const structure = useChartStore((state) => state.structure)
  const aiIct = useChartStore((state) => state.aiIct)
  const btcPatterns = useChartStore((state) => state.btcPatterns) ?? DEMO_PATTERNS

  const featuredSignals = useMemo<TradeSignal[]>(() => {
    if (!aiIct || aiIct.direction === 'neutral' || aiIct.grade === 'NO_TRADE' || aiIct.entry == null || aiIct.stop_loss == null) {
      return []
    }
    const side = aiIct.direction === 'bullish' ? 'buy' : 'sell'
    const risk = Math.abs(aiIct.entry - aiIct.stop_loss)
    const selectedRr = targetRiskReward === 'best' ? aiIct.risk_reward ?? 3 : targetRiskReward
    const exitPrice = side === 'buy' ? aiIct.entry + risk * selectedRr : aiIct.entry - risk * selectedRr
    return [{
      id: `ai-${aiIct.timeframe}-${aiIct.timestamp}`,
      timestamp: aiIct.timestamp, side,
      entry: aiIct.entry, stop_loss: aiIct.stop_loss, exit_price: exitPrice,
      risk_reward: selectedRr, confidence: aiIct.confidence,
      reason: aiIct.summary, status: aiIct.readiness === 'avoid' ? 'pending' : 'open',
      institutional_score: aiIct.setup_score, liquidity_score: aiIct.setup_score,
      bias_score: aiIct.setup_score, expected_move: Math.abs(exitPrice - aiIct.entry),
      model: aiIct.model ?? aiIct.provider,
    }]
  }, [aiIct, targetRiskReward])

  const latestCandle = candles.at(-1)

  const focusRecent = useCallback(() => {
    if (!chartRef.current || candles.length === 0) return
    const from = Math.max(0, candles.length - INITIAL_VISIBLE_BARS)
    chartRef.current.timeScale().setVisibleLogicalRange({ from, to: candles.length + RIGHT_OFFSET_BARS })
    setVersion((v) => v + 1)
  }, [candles.length])

  const fitAll = useCallback(() => {
    chartRef.current?.timeScale().fitContent()
    setVersion((v) => v + 1)
  }, [])

  const resetChart = useCallback(() => {
    fittedRef.current = false
    fitAll()
  }, [fitAll])

  function calculateEMA(data: CandleData[], period: number): LineData[] {
    if (data.length < period) return []
    const ema: LineData[] = []
    const multiplier = 2 / (period + 1)
    let emaValue = data.slice(0, period).reduce((sum, c) => sum + c.close, 0) / period
    ema.push({ time: data[period - 1].time, value: emaValue })
    for (let i = period; i < data.length; i++) {
      emaValue = (data[i].close - emaValue) * multiplier + emaValue
      ema.push({ time: data[i].time, value: emaValue })
    }
    return ema
  }

  // ─── Init chart ────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        attributionLogo: false,
        background: { type: ColorType.Solid, color: '#080b10' },
        textColor: '#8a96a8',
        fontFamily: 'Inter, Segoe UI, sans-serif',
      },
      grid: {
        vertLines: { color: '#10161f' },
        horzLines: { color: '#10161f' },
      },
      rightPriceScale: {
        borderColor: '#1a2230',
        scaleMargins: { top: 0.12, bottom: 0.12 },
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: '#1a2230',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: RIGHT_OFFSET_BARS,
        barSpacing: 8,
        minBarSpacing: 3,
      },
      crosshair: {
        mode: 0 as unknown as CrosshairMode,
        vertLine: { color: '#4a5568', style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a202c' },
        horzLine: { color: '#4a5568', style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a202c' },
      },
      handleScroll: { vertTouchDrag: true, pressedMouseMove: true, horzTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
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
      color: '#ff6b6b', lineWidth: 2, title: 'EMA 9',
    })
    const ema23Series = chart.addSeries(LineSeries, {
      color: '#4ecdc4', lineWidth: 2, title: 'EMA 23',
    })
    const ema99Series = chart.addSeries(LineSeries, {
      color: '#45b7d1', lineWidth: 2, title: 'EMA 99',
    })

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    chartRef.current = chart
    seriesRef.current = series
    ema9Ref.current = ema9Series
    ema23Ref.current = ema23Series
    ema99Ref.current = ema99Series
    volumeRef.current = volumeSeries
    markersRef.current = createSeriesMarkers(series, [], { autoScale: true })
    patternMarkersRef.current = createSeriesMarkers(series, [], { autoScale: true })
    setChartApi(chart)
    setSeriesApi(series)

    const resize = () => {
      const next = { width: container.clientWidth, height: container.clientHeight }
      chart.applyOptions({ width: next.width, height: next.height })
      setDimensions(next)
      setVersion((v) => v + 1)
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(container)

    chart.timeScale().subscribeVisibleTimeRangeChange(() => setVersion((v) => v + 1))

    // ── Crosshair tooltip ──
    const tooltipEl = tooltipRef.current
    if (tooltipEl) {
      chart.subscribeCrosshairMove((param) => {
        if (!param.time || !param.point) {
          setTooltip(null)
          return
        }
        const data = param.seriesData.get(series) as CandleData | undefined
        if (!data) {
          setTooltip(null)
          return
        }
        const candle: ChartCandle = { time: param.time as UTCTimestamp, open: data.open, high: data.high, low: data.low, close: data.close, volume: 0, isClosed: true }
        setTooltip({ x: param.point.x, y: param.point.y, data: candle })
      })
    }

    // Initial sizing
    resize()

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      ema9Ref.current = null
      ema23Ref.current = null
      ema99Ref.current = null
      volumeRef.current = null
      markersRef.current = null
      patternMarkersRef.current = null
      setChartApi(null)
      setSeriesApi(null)
    }
  }, [])

  // ─── Candle + volume updates ───────────────────────────
  useEffect(() => {
    if (!seriesRef.current || candles.length === 0) return
    seriesRef.current.setData(candles)
    volumeRef.current?.setData(
      candles.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? 'rgba(54,199,165,0.3)' : 'rgba(241,97,109,0.3)' }))
    )
    if (!fittedRef.current) {
      const from = Math.max(0, candles.length - INITIAL_VISIBLE_BARS)
      chartRef.current?.timeScale().setVisibleLogicalRange({ from, to: candles.length + RIGHT_OFFSET_BARS })
      fittedRef.current = true
    }
    setVersion((v) => v + 1)
  }, [candles])

  // ─── Signal markers ────────────────────────────────────
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

  // ─── Pattern markers ───────────────────────────────────
  useEffect(() => {
    const patternMarkers: SeriesMarker<Time>[] = []
    if (showPatterns && btcPatterns?.patterns) {
      btcPatterns.patterns.forEach((p) => {
        patternMarkers.push({
          time: toChartTime(p.timestamp),
          position: p.direction === 'bullish' ? 'belowBar' : p.direction === 'bearish' ? 'aboveBar' : 'inBar',
          shape: 'circle',
          color: p.direction === 'bullish' ? '#1fe3a3' : p.direction === 'bearish' ? '#ff5b6b' : '#8ab4f8',
          text: p.name.slice(0, 12).replaceAll('_', ' '),
        })
      })
    }
    patternMarkersRef.current?.setMarkers(patternMarkers)
  }, [showPatterns, btcPatterns])

  // ─── EMA updates ───────────────────────────────────────
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

  // ─── Right-click reset ─────────────────────────────────
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    resetChart()
  }, [resetChart])

  // ─── Keyboard shortcuts ────────────────────────────────
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      switch (e.key.toLowerCase()) {
        case 'r': focusRecent(); break
        case 'f': fitAll(); break
        case '1': setShowMarks((v) => !v); break
        case '2': setShowPatterns((v) => !v); break
        case '3': setShowStructure((v) => !v); break
        case '4': setShowEMAs((v) => !v); break
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [focusRecent, fitAll])

  // ─── Tooltip positioning ───────────────────────────────
  const tooltipStyle = tooltip && tooltip.data
    ? {
        left: Math.min(tooltip.x + 14, (dimensions.width || 600) - 160),
        top: Math.max(tooltip.y - 40, 8),
      }
    : null

  return (
    <div className="chart-shell" onContextMenu={handleContextMenu}>
      <div ref={containerRef} className="chart-canvas" />

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className={`chart-tooltip ${tooltip && tooltip.data ? 'visible' : ''}`}
        style={tooltipStyle ?? undefined}
      >
        {tooltip?.data && (
          <>
            <div className="tt-time">
              {new Date((tooltip.data.time as number) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
            <div className="tt-row">
              <span className="tt-label">O</span>
              <span className="tt-value">{tooltip.data.open.toFixed(1)}</span>
              <span className="tt-label">H</span>
              <span className="tt-value">{tooltip.data.high.toFixed(1)}</span>
            </div>
            <div className="tt-row">
              <span className="tt-label">L</span>
              <span className="tt-value">{tooltip.data.low.toFixed(1)}</span>
              <span className="tt-label">C</span>
              <span className={`tt-value ${tooltip.data.close >= tooltip.data.open ? 'up' : 'down'}`}>
                {tooltip.data.close.toFixed(1)}
              </span>
            </div>
            <div className="tt-row">
              <span className="tt-label">Vol</span>
              <span className="tt-value">{(tooltip.data.volume ?? 0) > 1000 ? `${((tooltip.data.volume ?? 0) / 1000).toFixed(0)}K` : (tooltip.data.volume ?? 0).toFixed(0)}</span>
              <span className="tt-label">Ch</span>
              <span className={`tt-value ${tooltip.data.close >= tooltip.data.open ? 'up' : 'down'}`}>
                {tooltip.data.open ? `${((tooltip.data.close - tooltip.data.open) / tooltip.data.open * 100).toFixed(2)}%` : '--'}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Watermark */}
      <div className="chart-watermark">
        <span className="wm-label">NEXUS</span>
        <span className="wm-price">{latestCandle?.close.toFixed(1) ?? '--'}</span>
      </div>

      {/* Overlays */}
      {showMarks ? (
        <ZoneRenderer
          chart={chartApi} series={seriesApi}
          width={dimensions.width} height={dimensions.height} version={version}
          fvgs={fvgs.slice(-5)} orderBlocks={orderBlocks.slice(-4)} liquidity={liquidity.slice(-4)}
        />
      ) : null}
      {showStructure ? (
        <StructureOverlay
          chart={chartApi} series={seriesApi}
          width={dimensions.width} height={dimensions.height} version={version}
          structure={structure.slice(-18)}
        />
      ) : null}
      <SignalOverlay
        chart={chartApi} series={seriesApi}
        width={dimensions.width} height={dimensions.height} version={version}
        signals={featuredSignals}
      />

      <div className="chart-controls">
        <button type="button" onClick={resetChart} title="Reset view (right-click)">Fit</button>
        <button type="button" onClick={focusRecent} title="Recent candles (R)">Latest</button>
        <div className="ctrl-sep" />
        <button type="button" className={showMarks ? 'active' : ''} onClick={() => setShowMarks((v) => !v)}>
          ICT
        </button>
        <button type="button" className={showPatterns ? 'active' : ''} onClick={() => setShowPatterns((v) => !v)}>
          Pat.
        </button>
        <button type="button" className={showStructure ? 'active' : ''} onClick={() => setShowStructure((v) => !v)}>
          Struct.
        </button>
        <button type="button" className={showEMAs ? 'active' : ''} onClick={() => setShowEMAs((v) => !v)}>
          EMAs
        </button>
      </div>
    </div>
  )
}
