import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Bell, CheckCircle, Info, XCircle, BellOff } from 'lucide-react'
import type { Alert } from '../types/market'

const SEV_META: Record<string, { icon: typeof Bell; cls: string }> = {
  critical: { icon: XCircle, cls: 'sev-critical' },
  high: { icon: AlertTriangle, cls: 'sev-high' },
  medium: { icon: Bell, cls: 'sev-medium' },
  low: { icon: Info, cls: 'sev-low' },
}

export default function AlertsPanel() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await fetch('/alerts?limit=50')
      setAlerts(await res.json())
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const initial = setTimeout(() => void fetchAlerts(), 0)
    const interval = setInterval(fetchAlerts, 15000)
    return () => {
      clearTimeout(initial)
      clearInterval(interval)
    }
  }, [fetchAlerts])

  const acknowledge = async (id: string) => {
    try {
      await fetch(`/alerts/${id}/acknowledge`, { method: 'POST' })
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: 1 } : a)))
    } catch { /* ignore */ }
  }

  if (loading) return <p className="empty-state">Loading alerts...</p>

  const unread = alerts.filter((a) => !a.acknowledged)
  const read = alerts.filter((a) => a.acknowledged)

  return (
    <div className="alerts-panel">
      <div className="alerts-panel-hdr">
        <Bell size={13} />
        <span>Alerts</span>
        {unread.length > 0 && <span className="alerts-count">{unread.length}</span>}
      </div>

      {alerts.length === 0 && (
        <div className="alerts-empty">
          <BellOff size={20} className="alerts-empty-icon" />
          <p>No alerts yet.</p>
        </div>
      )}

      {unread.length > 0 && (
        <div className="alerts-section">
          <div className="alerts-section-hdr">Unread</div>
          {unread.map((a) => <AlertRow key={a.id} alert={a} onAck={acknowledge} />)}
        </div>
      )}

      {read.length > 0 && (
        <div className="alerts-section">
          <div className="alerts-section-hdr acknowledged">Acknowledged</div>
          {read.slice(0, 15).map((a) => <AlertRow key={a.id} alert={a} onAck={acknowledge} />)}
        </div>
      )}
    </div>
  )
}

function AlertRow({ alert, onAck }: { alert: Alert; onAck: (id: string) => void }) {
  const meta = SEV_META[alert.severity] ?? SEV_META.low
  const Icon = meta.icon

  return (
    <div className={`alert-row ${meta.cls} ${alert.acknowledged ? 'acknowledged' : ''}`}>
      <div className="alert-row-icon"><Icon size={13} /></div>
      <div className="alert-row-body">
        <div className="alert-row-title">{alert.title}</div>
        {alert.message && <div className="alert-row-msg">{alert.message}</div>}
        <div className="alert-row-meta">
          <span className={`alert-row-sev ${meta.cls}`}>{alert.severity}</span>
          <span>{new Date(alert.timestamp).toLocaleTimeString()}</span>
        </div>
      </div>
      {!alert.acknowledged && (
        <button className="alert-row-ack" onClick={() => onAck(alert.id)} title="Acknowledge">
          <CheckCircle size={13} />
        </button>
      )}
    </div>
  )
}
