import { useCallback, useEffect, useRef, useState } from 'react'
import { useChartStore } from '../store/chartStore'
import { parseMarketMessage } from '../utils/marketMessage'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
const WS_URL = import.meta.env.VITE_WS_URL ?? 'ws://127.0.0.1:8000/ws/chart'

export function useMarketSocket() {
  const applyMessage = useChartStore((state) => state.applyMessage)
  const setConnectionStatus = useChartStore((state) => state.setConnectionStatus)
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const websocketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const heartbeatRef = useRef<number | null>(null)
  const retryRef = useRef(1000)
  const [session, setSession] = useState(0)

  const reconnect = useCallback(() => {
    websocketRef.current?.close()
    setSession((value) => value + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function loadSnapshot() {
      try {
        const response = await fetch(`${API_BASE}/snapshot?tf=${encodeURIComponent(selectedTimeframe)}`)
        if (!response.ok) throw new Error(`Snapshot failed: ${response.status}`)
        const data = parseMarketMessage(await response.json())
        if (!data) throw new Error('Snapshot payload validation failed')
        if (!cancelled) applyMessage(data)
      } catch (error) {
        if (!cancelled) {
          applyMessage({
            update_type: 'status',
            status: 'snapshot_error',
            message: error instanceof Error ? error.message : String(error),
          })
        }
      }
    }

    loadSnapshot()
    return () => {
      cancelled = true
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
      heartbeatRef.current = window.setInterval(() => {
        if (websocket.readyState === WebSocket.OPEN) websocket.send('ping')
      }, 15000)
    }

    websocket.onmessage = (event) => {
      try {
        const message = parseMarketMessage(JSON.parse(event.data))
        if (!message) throw new Error('WebSocket payload validation failed')
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
