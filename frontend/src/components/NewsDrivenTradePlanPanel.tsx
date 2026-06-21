import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  Minus,
  Globe,
  MessageSquare,
  Calendar,
  Activity,
  Zap,
  Target,
  Radio,
  Newspaper,
} from 'lucide-react'
import { useChartStore } from '../store/chartStore'
import { formatTimestamp } from '../types/market'
import type { NewsDrivenPlan, NewsActivityEntry, NewsTradePlanSnapshot, FastHeadline } from '../types/market'

function getDirectionColor(dir: string) {
  switch (dir) {
    case 'bullish': return 'var(--accent-green)'
    case 'bearish': return 'var(--accent-red)'
    default: return 'var(--accent-yellow)'
  }
}

function getDirectionIcon(dir: string) {
  switch (dir) {
    case 'bullish': return <TrendingUp size={12} />
    case 'bearish': return <TrendingDown size={12} />
    default: return <Minus size={12} />
  }
}

function getImpactBadge(impact: string) {
  switch (impact) {
    case 'high': return <span className="badge badge-high">HIGH</span>
    case 'medium': return <span className="badge badge-med">MED</span>
    case 'low': return <span className="badge badge-low">LOW</span>
    default: return <span className="badge badge-low">{impact.toUpperCase()}</span>
  }
}

function getEventTypeIcon(type: string) {
  switch (type) {
    case 'headline': return <MessageSquare size={11} />
    case 'sentiment_shift': return <Activity size={11} />
    case 'macro_event': return <Calendar size={11} />
    case 'volatility_anomaly': return <Zap size={11} />
    case 'trade_plan': return <Target size={11} />
    default: return <Activity size={11} />
  }
}

function formatSecondsAgo(ts: number) {
  const diff = Date.now() - ts
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return `${Math.floor(diff / 86400000)}d ago`
}

function PlanCard({ plan }: { plan: NewsDrivenPlan }) {
  return (
    <div className={`ntp-plan-card ${plan.direction}`}>
      <div className="ntp-plan-header">
        <span className="ntp-plan-direction" style={{ color: getDirectionColor(plan.direction) }}>
          {getDirectionIcon(plan.direction)}
          {plan.direction.toUpperCase()}
        </span>
        {getImpactBadge(plan.impact)}
        <span className="ntp-plan-time">{formatSecondsAgo(plan.timestamp)}</span>
      </div>
      <div className="ntp-plan-headline">{plan.headline}</div>
      <div className="ntp-plan-meta">
        <span className="ntp-plan-source">{plan.source}</span>
        <span className="ntp-plan-conf">{(plan.confidence * 100).toFixed(0)}% confidence</span>
        <span className={`ntp-plan-status ${plan.status}`}>{plan.status}</span>
      </div>
      {plan.entry_zone_low != null && (
        <div className="ntp-plan-levels">
          <div className="ntp-level">
            <span className="ntp-level-label">Entry</span>
            <span className="ntp-level-value">${plan.entry_zone_low.toLocaleString()}–${plan.entry_zone_high?.toLocaleString()}</span>
          </div>
          {plan.stop_loss != null && (
            <div className="ntp-level">
              <span className="ntp-level-label">SL</span>
              <span className="ntp-level-value sl">${plan.stop_loss.toLocaleString()}</span>
            </div>
          )}
          {plan.target_1 != null && (
            <div className="ntp-level">
              <span className="ntp-level-label">TP1</span>
              <span className="ntp-level-value tp">${plan.target_1.toLocaleString()}</span>
            </div>
          )}
          {plan.target_2 != null && (
            <div className="ntp-level">
              <span className="ntp-level-label">TP2</span>
              <span className="ntp-level-value tp">${plan.target_2.toLocaleString()}</span>
            </div>
          )}
        </div>
      )}
      {plan.rationale && (
        <p className="ntp-plan-reason">{plan.rationale}</p>
      )}
    </div>
  )
}

function ActivityRow({ entry }: { entry: NewsActivityEntry }) {
  return (
    <div className="ntp-activity-row">
      <span className="ntp-activity-icon" style={{ color: getDirectionColor(entry.direction) }}>
        {getEventTypeIcon(entry.event_type)}
      </span>
      <div className="ntp-activity-body">
        <div className="ntp-activity-title">{entry.title}</div>
        <div className="ntp-activity-meta">
          <span className="ntp-activity-source">{entry.source}</span>
          <span className="ntp-activity-time">{formatSecondsAgo(entry.timestamp)}</span>
        </div>
      </div>
    </div>
  )
}

export function NewsDrivenTradePlanPanel() {
  const wsSnapshot = useChartStore((s) => s.newsTradePlan)
  const wsFastNews = useChartStore((s) => s.fastNews)
  const [snapshot, setSnapshot] = useState<NewsTradePlanSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'plans' | 'activity' | 'events'>('plans')

  const fastNews = wsFastNews
  const breakingHeadlines = fastNews?.breaking ?? []
  const recentFastHeadlines = fastNews?.headlines?.slice(0, 10) ?? []

  const fetchPlan = useCallback(async () => {
    try {
      const res = await fetch('/news/trade-plan')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      if (json && typeof json === 'object') {
        setSnapshot(json)
        setError(null)
      }
    } catch (e: any) {
      if (!wsSnapshot) setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [wsSnapshot])

  useEffect(() => {
    if (!wsSnapshot) {
      fetchPlan()
      const interval = setInterval(fetchPlan, 120000)
      return () => clearInterval(interval)
    } else {
      setLoading(false)
      setError(null)
    }
  }, [fetchPlan, wsSnapshot])

  const display = wsSnapshot ?? snapshot

  return (
    <div className="ntp-panel">
      <div className="dsp-header">
        <h2><Globe size={14} /> News Trade Plan</h2>
        <div className="dsp-controls">
          <button className="dsp-btn" onClick={fetchPlan} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchPlan}>Retry</button>
        </div>
      )}

      {display && (
        <div className="dsp-summary">
          <div className="dsp-stat">
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Sentiment</span>
              <span className="dsp-stat-value" style={{ color: getDirectionColor(display.sentiment_label) }}>
                {getDirectionIcon(display.sentiment_label)}
                {display.sentiment_label.toUpperCase()}
              </span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Score</span>
              <span className="dsp-stat-value">{display.sentiment_score.toFixed(3)}</span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Active Plans</span>
              <span className="dsp-stat-value">{display.active_plans.length}</span>
            </div>
          </div>
          <div className="dsp-stat">
            <div className="dsp-stat-info">
              <span className="dsp-stat-label">Sources</span>
              <span className="dsp-stat-value">{display.source_count}</span>
            </div>
          </div>
        </div>
      )}

      {/* ─── BREAKING NEWS TICKER ─── */}
      {breakingHeadlines.length > 0 && (
        <div className="ntp-breaking-bar">
          <Radio size={12} className="ntp-breaking-icon" />
          <div className="ntp-breaking-scroll">
            {breakingHeadlines.map((h, i) => (
              <span key={i} className="ntp-breaking-item">
                <strong>{h.source}</strong>: {h.title}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ─── LIVE HEADLINES ─── */}
      {recentFastHeadlines.length > 0 && (
        <div className="ntp-section">
          <h3><Newspaper size={12} /> Live Headlines</h3>
          <div className="ntp-live-list">
            {recentFastHeadlines.map((h, i) => (
              <div key={i} className={`ntp-live-item ${h.is_breaking ? 'breaking' : ''}`}>
                <span className="ntp-live-source">{h.source}</span>
                <span className="ntp-live-title">{h.title}</span>
                <span className="ntp-live-score" style={{ color: h.score > 0 ? 'var(--accent-green)' : h.score < 0 ? 'var(--accent-red)' : 'var(--text-muted)' }}>
                  {h.score > 0 ? '+' : ''}{h.score.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {display && display.macro_events.length > 0 && (
        <div className="ntp-section">
          <h3><Calendar size={12} /> Upcoming Macro Events</h3>
          <div className="ntp-events-list">
            {display.macro_events.slice(0, 5).map((ev, i) => (
              <div key={i} className="ntp-event-row">
                <span className="ntp-event-name">{ev.name}</span>
                <span className={`ntp-event-impact ${ev.impact}`}>{ev.impact.toUpperCase()}</span>
                <span className="ntp-event-hours">{ev.hours_until > 0 ? `${ev.hours_until.toFixed(0)}h` : 'NOW'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ─── TABS ─── */}
      <div className="ntp-tabs">
        <button className={`ntp-tab ${tab === 'plans' ? 'active' : ''}`} onClick={() => setTab('plans')}>
          Plans ({display?.active_plans.length ?? 0})
        </button>
        <button className={`ntp-tab ${tab === 'activity' ? 'active' : ''}`} onClick={() => setTab('activity')}>
          Activity ({display?.recent_activity.length ?? 0})
        </button>
        <button className={`ntp-tab ${tab === 'events' ? 'active' : ''}`} onClick={() => setTab('events')}>
          Events
        </button>
      </div>

      <div className="ntp-content">
        {tab === 'plans' && (
          <>
            {!display || display.active_plans.length === 0 ? (
              <p className="empty-state">No active news-driven trade plans.</p>
            ) : (
              display.active_plans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} />
              ))
            )}
          </>
        )}

        {tab === 'activity' && (
          <>
            {!display || display.recent_activity.length === 0 ? (
              <p className="empty-state">No recent news activity.</p>
            ) : (
              <div className="ntp-activity-list">
                {[...display.recent_activity].reverse().map((entry) => (
                  <ActivityRow key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </>
        )}

        {tab === 'events' && (
          <>
            {!display || display.macro_events.length === 0 ? (
              <p className="empty-state">No macro events in the next 48h.</p>
            ) : (
              <div className="ntp-events-list ntp-events-detailed">
                {display.macro_events.map((ev, i) => (
                  <div key={i} className="ntp-event-row">
                    <div className="ntp-event-info">
                      <span className="ntp-event-name">{ev.name}</span>
                      <span className="ntp-event-date">{ev.date}</span>
                    </div>
                    <span className={`ntp-event-impact ${ev.impact}`}>{ev.impact.toUpperCase()}</span>
                    <span className="ntp-event-hours">{ev.hours_until > 0 ? `${ev.hours_until.toFixed(0)}h` : 'NOW'}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {loading && !display && (
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading news trade plan...</span>
        </div>
      )}
    </div>
  )
}
