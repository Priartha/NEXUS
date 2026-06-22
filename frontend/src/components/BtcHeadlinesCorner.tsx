import { useCallback, useEffect, useRef, useState } from 'react'
import { ExternalLink, Globe, GripVertical, TrendingDown, TrendingUp, Minus, X, RefreshCw } from 'lucide-react'
import { useBtcHeadlines } from '../hooks/useBtcHeadlines'
import type { BtcHeadline } from '../hooks/useBtcHeadlines'

const SENTIMENT_COLORS: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  bullish: { bg: 'rgba(31, 227, 163, 0.08)', border: 'rgba(31, 227, 163, 0.25)', text: '#1fe3a3', icon: '#1fe3a3' },
  bearish: { bg: 'rgba(255, 91, 107, 0.08)', border: 'rgba(255, 91, 107, 0.25)', text: '#ff5b6b', icon: '#ff5b6b' },
  neutral: { bg: 'rgba(138, 180, 248, 0.08)', border: 'rgba(138, 180, 248, 0.25)', text: '#8ab4f8', icon: '#8ab4f8' },
}

const DEFAULT_POSITION = { x: window.innerWidth - 340, y: window.innerHeight - 420 }

function SentimentIcon({ sentiment, size = 12 }: { sentiment: string; size?: number }) {
  if (sentiment === 'bullish') return <TrendingUp size={size} color={SENTIMENT_COLORS.bullish.icon} />
  if (sentiment === 'bearish') return <TrendingDown size={size} color={SENTIMENT_COLORS.bearish.icon} />
  return <Minus size={size} color={SENTIMENT_COLORS.neutral.icon} />
}

function HeadlineItem({ headline }: { headline: BtcHeadline }) {
  const colors = SENTIMENT_COLORS[headline.sentiment] ?? SENTIMENT_COLORS.neutral
  const timeAgo = getTimeAgo(headline.published_at)
  const rep = headline.source_reputation ?? 0.5

  return (
    <a
      href={headline.url}
      target="_blank"
      rel="noopener noreferrer"
      className="headline-item"
      style={{ background: colors.bg, borderColor: colors.border }}
    >
      <div className="headline-header">
        <div className="headline-sentiment" style={{ color: colors.text }}>
          <SentimentIcon sentiment={headline.sentiment} size={11} />
          <span>{headline.sentiment.toUpperCase()}</span>
          {headline.score != null && (
            <span className="headline-backend-score" style={{ color: headline.score > 0 ? 'var(--accent-green)' : headline.score < 0 ? 'var(--accent-red)' : 'var(--text-muted)', fontSize: 9, marginLeft: 4 }}>
              {headline.score > 0 ? '+' : ''}{headline.score.toFixed(2)}
            </span>
          )}
        </div>
        <div className="headline-meta">
          <span className="headline-source">{headline.source}</span>
          {rep >= 0.9 && <span className="headline-trusted-badge" title="Trusted source">✓</span>}
          <span className="headline-time">{timeAgo}</span>
        </div>
      </div>
      <p className="headline-title">{headline.title}</p>
      <div className="headline-link">
        <ExternalLink size={9} />
        <span>Read more</span>
      </div>
    </a>
  )
}

function getTimeAgo(timestamp: number | string): string {
  const now = Date.now()
  let then: number

  if (typeof timestamp === 'string') {
    then = new Date(timestamp).getTime()
  } else if (timestamp > 1e12) {
    then = timestamp
  } else {
    then = timestamp * 1000
  }

  if (!then || Number.isNaN(then)) return ''

  const diffMs = now - then
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  return `${diffDays}d ago`
}

export function BtcHeadlinesCorner() {
  const { headlines, loading, error, activeSource } = useBtcHeadlines()
  const [position, setPosition] = useState(() => {
    try {
      const saved = localStorage.getItem('nexus-headlines-pos')
      if (saved) {
        const parsed = JSON.parse(saved)
        return { x: Math.max(0, Math.min(parsed.x, window.innerWidth - 320)), y: Math.max(0, Math.min(parsed.y, window.innerHeight - 400)) }
      }
    } catch { /* ignore */ }
    return DEFAULT_POSITION
  })
  const [isDragging, setIsDragging] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 })
  const widgetRef = useRef<HTMLDivElement>(null)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.headline-item, .headlines-actions button')) return
    e.preventDefault()
    setIsDragging(true)
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      posX: position.x,
      posY: position.y,
    }
  }, [position])

  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStartRef.current.x
      const dy = e.clientY - dragStartRef.current.y
      const newX = Math.max(0, Math.min(dragStartRef.current.posX + dx, window.innerWidth - 320))
      const newY = Math.max(0, Math.min(dragStartRef.current.posY + dy, window.innerHeight - 40))
      setPosition({ x: newX, y: newY })
    }

    const handleMouseUp = () => {
      setIsDragging(false)
      try {
        localStorage.setItem('nexus-headlines-pos', JSON.stringify(position))
      } catch { /* ignore */ }
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging, position])

  const handleRefresh = useCallback(() => {
    window.dispatchEvent(new CustomEvent('btc-headlines-refresh'))
  }, [])

  const handleClose = useCallback(() => {
    setIsMinimized(true)
  }, [])

  const handleRestore = useCallback(() => {
    setIsMinimized(false)
    setIsCollapsed(false)
  }, [])

  if (isMinimized) {
    return (
      <button
        type="button"
        className="btc-headlines-minimized"
        onClick={handleRestore}
        title="Show BTC News"
      >
        <Globe size={14} />
        <span>BTC</span>
      </button>
    )
  }

  return (
    <div
      ref={widgetRef}
      className={`btc-headlines-corner ${isDragging ? 'dragging' : ''} ${isCollapsed ? 'collapsed' : ''}`}
      style={{ left: `${position.x}px`, top: `${position.y}px` }}
    >
      <div
        className="headlines-drag-handle"
        onMouseDown={handleMouseDown}
      >
        <div className="headlines-header-left">
          <GripVertical size={12} className="drag-icon" />
          <Globe size={12} />
          <span>BTC LIVE NEWS</span>
          {activeSource && <span className="headlines-source-badge">{activeSource}</span>}
        </div>
        <div className="headlines-actions">
          <button type="button" onClick={() => setIsCollapsed((v) => !v)} title={isCollapsed ? 'Expand' : 'Collapse'}>
            {isCollapsed ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          </button>
          <button type="button" onClick={handleRefresh} title="Refresh">
            <RefreshCw size={12} />
          </button>
          <button type="button" onClick={handleClose} title="Minimize">
            <X size={12} />
          </button>
        </div>
      </div>

      {!isCollapsed && (
        <>
          {loading && headlines.length === 0 && (
            <div className="headlines-loading">
              <div className="loading-spinner" />
              <span>Loading headlines...</span>
            </div>
          )}

          {error && headlines.length === 0 && (
            <div className="headlines-error">
              <span>{error}</span>
              <button type="button" onClick={handleRefresh} className="retry-btn">
                <RefreshCw size={10} />
                Retry
              </button>
            </div>
          )}

          <div className="headlines-list">
            {headlines.map((h, i) => (
              <HeadlineItem key={`${i}-${h.title}`} headline={h} />
            ))}
          </div>
        </>
      )}

      {isCollapsed && (
        <div className="headlines-collapsed-preview">
          {headlines.length > 0 && (
            <div className="collapsed-headline">
              <SentimentIcon sentiment={headlines[0].sentiment} size={10} />
              <span>{headlines[0].title}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
