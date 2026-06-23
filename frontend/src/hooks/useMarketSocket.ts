import { useCallback, useEffect, useRef, useState } from 'react'
import { useChartStore } from '../store/chartStore'
import { parseMarketMessage } from '../utils/marketMessage'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const LOCAL_WS_URL = 'ws://127.0.0.1:8000/ws/chart'
const WS_URL = import.meta.env.VITE_WS_URL
  ?? (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost' ? LOCAL_WS_URL : '/ws/chart')
const STALE_SOCKET_MS = 30000

export function useMarketSocket() {
  const applyMessage = useChartStore((state) => state.applyMessage)
  const setConnectionStatus = useChartStore((state) => state.setConnectionStatus)
  const selectedTimeframe = useChartStore((state) => state.selectedTimeframe)
  const websocketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const heartbeatRef = useRef<number | null>(null)
  const socketWatchdogRef = useRef<number | null>(null)
  const animationFrameRef = useRef<number | null>(null)
  const pendingLiveMessageRef = useRef<ReturnType<typeof parseMarketMessage> | null>(null)
  const retryRef = useRef(1000)
  const lastMessageAtRef = useRef(0)
  const snapshotAppliedRef = useRef(false)
  const [session, setSession] = useState(0)

  const reconnect = useCallback(() => {
    websocketRef.current?.close()
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current)
    if (heartbeatRef.current) window.clearInterval(heartbeatRef.current)
    if (socketWatchdogRef.current) window.clearInterval(socketWatchdogRef.current)
    if (animationFrameRef.current) window.cancelAnimationFrame(animationFrameRef.current)
    reconnectTimerRef.current = null
    heartbeatRef.current = null
    socketWatchdogRef.current = null
    animationFrameRef.current = null
    pendingLiveMessageRef.current = null
    snapshotAppliedRef.current = false
    lastMessageAtRef.current = 0
    setSession((value) => value + 1)
  }, [])

  const applyLiveMessage = useCallback((message: ReturnType<typeof parseMarketMessage>) => {
    if (!message) return
    if (message.update_type !== 'tick' && message.update_type !== 'quote') {
      applyMessage(message)
      return
    }
    pendingLiveMessageRef.current = message
    if (animationFrameRef.current !== null) return
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null
      const pending = pendingLiveMessageRef.current
      pendingLiveMessageRef.current = null
      if (pending) applyMessage(pending)
    })
  }, [applyMessage])

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
        const json = parseMarketMessage(await response.json())
        if (!json || json.update_type !== 'snapshot') throw new Error('Invalid snapshot payload')
        const nc = json.candles?.length ?? 0
        if (!nc) throw new Error('No candles in snapshot')
        if (cancelled) return

        applyMessage(json)
        snapshotAppliedRef.current = true
      } catch (error) {
        if (!cancelled) {
          console.warn('[HTTP] Snapshot error:', error)
        }
      }
    }

    loadSnapshot()
    const timer = window.setInterval(() => {
      if (cancelled || snapshotAppliedRef.current) return
      loadSnapshot()
    }, 3000)

    return () => { cancelled = true; window.clearInterval(timer) }
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
    snapshotAppliedRef.current = false
    const joiner = WS_URL.includes('?') ? '&' : '?'
    const ws = new WebSocket(`${WS_URL}${joiner}tf=${encodeURIComponent(selectedTimeframe)}`)
    websocketRef.current = ws

    ws.onopen = () => {
      retryRef.current = 1000
      lastMessageAtRef.current = Date.now()
      setConnectionStatus('open')
      heartbeatRef.current = window.setInterval(() => {
        try {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        } catch {
          ws.close()
        }
      }, 15000)
      socketWatchdogRef.current = window.setInterval(() => {
        const isStale = Date.now() - lastMessageAtRef.current > STALE_SOCKET_MS
        if (ws.readyState !== WebSocket.OPEN || isStale) {
          ws.close()
        }
      }, 10000)
    }

    ws.onmessage = (event) => {
      try {
        const parsed = parseMarketMessage(JSON.parse(event.data))
        if (!parsed) return
        lastMessageAtRef.current = Date.now()

        if (parsed.update_type === 'snapshot') {
          if (snapshotAppliedRef.current) {
            return
          }
          const nc = parsed.candles?.length ?? 0
          if (nc > 0) {
            applyMessage(parsed)
            snapshotAppliedRef.current = true
          }
          return
        }

          applyLiveMessage(parsed)
      } catch (error) {
        console.warn('[WS] Parse error:', error)
      }
    }

    ws.onerror = () => {
      setConnectionStatus('error')
      ws.close()
    }

    ws.onclose = () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      if (socketWatchdogRef.current) clearInterval(socketWatchdogRef.current)
      heartbeatRef.current = null
      socketWatchdogRef.current = null
      setConnectionStatus('closed')
      scheduleReconnect()
    }

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (heartbeatRef.current) {
          clearInterval(heartbeatRef.current)
          heartbeatRef.current = null
        }
      } else {
        const sock = websocketRef.current
        if (!sock || sock.readyState !== WebSocket.OPEN) {
          reconnect()
        }
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      closedByEffect = true
      document.removeEventListener('visibilitychange', onVisibilityChange)
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      if (socketWatchdogRef.current) clearInterval(socketWatchdogRef.current)
      if (animationFrameRef.current) window.cancelAnimationFrame(animationFrameRef.current)
      heartbeatRef.current = null
      socketWatchdogRef.current = null
      animationFrameRef.current = null
      pendingLiveMessageRef.current = null
      ws.close()
    }
  }, [applyLiveMessage, applyMessage, selectedTimeframe, setConnectionStatus, session, reconnect])

  return { reconnect }
}
