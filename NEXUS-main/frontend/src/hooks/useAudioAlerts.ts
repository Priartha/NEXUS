import { useEffect, useRef } from 'react'
import type { Alert } from '../types/market'

let ctx: AudioContext | null = null
function getCtx(): AudioContext {
  if (!ctx) {
    ctx = new AudioContext()
    document.addEventListener('click', () => ctx?.resume(), { once: true })
  }
  return ctx
}

function playBeep(frequency = 880, duration = 150, type: OscillatorType = 'sine') {
  try {
    const c = getCtx()
    const osc = c.createOscillator()
    const gain = c.createGain()
    osc.type = type
    osc.frequency.value = frequency
    gain.gain.setValueAtTime(0.3, c.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.01, c.currentTime + duration / 1000)
    osc.connect(gain)
    gain.connect(c.destination)
    osc.start()
    osc.stop(c.currentTime + duration / 1000)
  } catch {
    // Audio not available
  }
}

export function useAudioAlerts() {
  const lastAlertTs = useRef(0)

  useEffect(() => {
    let cancelled = false
    let pollTimer: ReturnType<typeof setTimeout>

    async function poll() {
      if (cancelled) return
      try {
        const res = await fetch('/alerts?unread_only=true&limit=5')
        if (!res.ok) return
        const alerts: Alert[] = await res.json()
        const highSev = alerts.filter(
          (a) => (a.severity === 'high' || a.severity === 'critical') && a.timestamp > lastAlertTs.current
        )
        for (const alert of highSev) {
          if (alert.timestamp > lastAlertTs.current) {
            lastAlertTs.current = alert.timestamp
            playBeep(alert.severity === 'critical' ? 1200 : 880, 200, 'square')
          }
        }
      } catch {
        // ignore poll errors
      }
      if (!cancelled) pollTimer = setTimeout(poll, 10000)
    }

    pollTimer = setTimeout(poll, 5000)

    return () => {
      cancelled = true
      clearTimeout(pollTimer)
    }
  }, [])
}
