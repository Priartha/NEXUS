import { useCallback, useEffect, useRef, useState } from 'react'
import { useChartStore } from '../store/chartStore'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const LOCAL_WS_URL = 'ws://127.0.0.1:8000/ws/chart'
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
  const snapshotAppliedRef = useRef(false)
  const [session, setSession] = useState(0)

  const reconnect = useCallback(() => {
    websocketRef.current?.close()
    snapshotAppliedRef.current = false
    setSession((value) => value + 1)
  }, [])

  // HTTP snapshot - runs once per session
  useEffect(() => {
    let cancelled = false
    snapshotAppliedRef.current = false

    async function loadSnapshot() {
      if (cancelled) return
      try {
        const url = `${API_BASE || ''}/snapshot?tf=${encodeURIComponent(selectedTimeframe)}`
        const response = await fetch(url)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const json = await response.json()
        const nc = json.candles?.length ?? 0
        if (!nc) throw new Error('No candles in snapshot')
        if (cancelled) return

        // Bypass Zod for HTTP snapshot - apply directly
        applyMessage(json)
        snapshotAppliedRef.current = true
        console.log(`[HTTP] Loaded ${nc} candles`)
      } catch (error) {
        if (!cancelled) {
          console.warn('[HTTP] Snapshot error:', error)
        }
      }
    }

    loadSnapshot()
    const timer = setInterval(() => {
      if (cancelled || snapshotAppliedRef.current) return
      loadSnapshot()
    }, 3000)

    return () => { cancelled = true; clearInterval(timer) }
  }, [applyMessage, selectedTimeframe, session])

  // WebSocket - only for live ticks after HTTP snapshot
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
    const ws = new WebSocket(`${WS_URL}${joiner}tf=${encodeURIComponent(selectedTimeframe)}`)
    websocketRef.current = ws

    ws.onopen = () => {
      retryRef.current = 1000
      setConnectionStatus('open')
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 15000)
    }

    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        const type = parsed.update_type
        const candleCount = parsed.candles?.length ?? (parsed.candle ? 1 : 0)
        console.log(`[WS] Received ${type} message with ${candleCount} candle(s)`)

        // Skip WebSocket snapshots - we already have HTTP candles
        if (type === 'snapshot') {
          if (snapshotAppliedRef.current) {
            console.log('[WS] Skipping snapshot - HTTP already applied')
            return
          }
          // Only apply WS snapshot if HTTP hasn't loaded yet
          const nc = parsed.candles?.length ?? 0
          if (nc > 0) {
            applyMessage(parsed)
            snapshotAppliedRef.current = true
            console.log(`[WS] Loaded ${nc} candles (HTTP not ready)`)
          }
          return
        }

        // Apply tick/close/quote updates
        applyMessage(parsed)
      } catch (error) {
        console.warn('[WS] Parse error:', error)
      }
    }

    ws.onerror = () => setConnectionStatus('error')

    ws.onclose = () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      setConnectionStatus('closed')
      scheduleReconnect()
    }

    return () => {
      closedByEffect = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      ws.close()
    }
  }, [applyMessage, selectedTimeframe, setConnectionStatus, session])

  return { reconnect }
}
