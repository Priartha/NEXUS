import { useCallback, useEffect, useRef, useState } from 'react'
import { useChartStore } from '../store/chartStore'
import { parseMarketMessage } from '../utils/marketMessage'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const LOCAL_WS_URL = 'ws://127.0.0.1:8080/ws/chart'
const WS_URL = import.meta.env.VITE_WS_URL
  ?? (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost' ? LOCAL_WS_URL : '/ws/chart')

export function useMarketSocket() {
  const applyMessage = useChartStore((state) => state.applyMessage)
  const setConnectionStatus = useChartStore((state) => state.setConnectionStatus)
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const websocketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const heartbeatRef = useRef<number | null>(null)
  const retryRef = useRef(1000)
  const wsReceivedRef = useRef(false)
  const [session, setSession] = useState(0)

  const reconnect = useCallback(() => {
    websocketRef.current?.close()
    setSession((value) => value + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    wsReceivedRef.current = false
    let retryCount = 0

    async function loadSnapshot() {
      if (cancelled) return
      try {
        const url = `${API_BASE || ''}/snapshot?tf=${encodeURIComponent(selectedTimeframe)}`
        console.log('Fetching HTTP snapshot from', url)
        const response = await fetch(url)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const json = await response.json()
        const nc = json.candles?.length ?? 0
        console.log('HTTP snapshot:', nc, 'candles, stats:', JSON.stringify(json.stats))
        if (!nc) throw new Error('Snapshot has zero candles')
        const data = parseMarketMessage(json)
        if (!data) throw new Error('Zod validation failed')
        if (!cancelled && !wsReceivedRef.current) {
          console.log('Applying HTTP snapshot:', nc, 'candles')
          applyMessage(data)
        }
      } catch (error) {
        if (!cancelled && !wsReceivedRef.current) {
          console.warn('HTTP snapshot error:', error)
          applyMessage({
            update_type: 'status',
            status: 'snapshot_error',
            message: error instanceof Error ? error.message : String(error),
          })
        }
      }
    }

    // Try HTTP snapshot immediately and retry up to 3 times
    loadSnapshot()
    const retryTimer = window.setInterval(() => {
      if (cancelled || wsReceivedRef.current) return
      retryCount++
      if (retryCount > 3) return window.clearInterval(retryTimer) // eslint-disable-line
      console.log('Retrying HTTP snapshot, attempt', retryCount)
      loadSnapshot()
    }, 4000)

    return () => {
      cancelled = true
      window.clearInterval(retryTimer)
    }
  }, [applyMessage, selectedTimeframe, session])

  useEffect(() => {
    let closedByEffect = false

    function scheduleReconnect() {
      if (closedByEffect) return
      const timeout = retryRef.current
      reconnectTimerRef.current = window.setTimeout(() => {
        setSession((value) => value + 1)
      }, timeout)
      retryRef.current = Math.min(timeout * 1.7, 15000)
    }

    setConnectionStatus('connecting')
    const joiner = WS_URL.includes('?') ? '&' : '?'
    const websocket = new WebSocket(`${WS_URL}${joiner}tf=${encodeURIComponent(selectedTimeframe)}`)
    websocketRef.current = websocket

    websocket.onopen = () => {
      retryRef.current = 1000
      setConnectionStatus('open')
      console.log('WebSocket connected to', WS_URL)
      heartbeatRef.current = window.setInterval(() => {
        if (websocket.readyState === WebSocket.OPEN) websocket.send('ping')
      }, 15000)
    }

    websocket.onmessage = (event) => {
      wsReceivedRef.current = true
      try {
        const parsed = JSON.parse(event.data)
        console.log('WS received:', parsed.update_type, parsed.candles?.length ?? 0, 'candles, stats:', parsed.stats)
        const message = parseMarketMessage(parsed)
        if (!message) return
        applyMessage(message)
      } catch (error) {
        applyMessage({
          update_type: 'status',
          status: 'parse_error',
          message: error instanceof Error ? error.message : String(error),
        })
      }
    }

    websocket.onerror = () => {
      setConnectionStatus('error')
    }

    websocket.onclose = () => {
      console.log('WebSocket closed')
      if (heartbeatRef.current) window.clearInterval(heartbeatRef.current)
      setConnectionStatus('closed')
      scheduleReconnect()
    }

    return () => {
      closedByEffect = true
      if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current)
      if (heartbeatRef.current) window.clearInterval(heartbeatRef.current)
      websocket.close()
    }
  }, [applyMessage, selectedTimeframe, setConnectionStatus, session])

  return { reconnect }
}
