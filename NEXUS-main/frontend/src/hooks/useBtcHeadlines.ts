import { useEffect, useState } from 'react'
import { useChartStore } from '../store/chartStore'

export interface BtcHeadline {
  title: string
  source: string
  url: string
  published_at: number
  sentiment: 'bullish' | 'bearish' | 'neutral'
  score?: number
  source_reputation?: number
  body?: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export function useBtcHeadlines() {
  const [headlines, setHeadlines] = useState<BtcHeadline[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeSource, setActiveSource] = useState<string>('')
  const sentiment = useChartStore((state) => state.sentiment)

  useEffect(() => {
    let cancelled = false

    async function fetchHeadlines() {
      try {
        setLoading(true)
        setError(null)
        const url = `${API_BASE || ''}/news/btc`
        const response = await fetch(url)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data = await response.json()

        if (!cancelled && Array.isArray(data) && data.length > 0) {
          const withSentiment: BtcHeadline[] = data.map((item) => ({
            title: item.title,
            source: item.source,
            url: item.url,
            published_at: item.published_at,
            score: item.score,
            source_reputation: item.source_reputation,
            body: item.body ?? '',
            sentiment: inferSentiment(item.title, sentiment?.label, item.score),
          }))
          setHeadlines(withSentiment)
          setActiveSource('NEXUS Proxy')
          setError(null)
        } else if (!cancelled) {
          throw new Error('No headlines returned')
        }
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to fetch'
          console.warn('BTC headlines fetch failed:', msg)
          setError(`Using fallback headlines (${msg})`)
          setActiveSource('fallback')
          setHeadlines(getFallbackHeadlines(sentiment?.label))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchHeadlines()
    const interval = setInterval(fetchHeadlines, 120000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [sentiment?.label])

  return { headlines, loading, error, activeSource }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function getFallbackHeadlines(_marketSentiment?: string): BtcHeadline[] {
  const now = Math.floor(Date.now() / 1000)
  return [
    {
      title: 'Bitcoin network hash rate remains strong — miners continue securing the blockchain',
      source: 'NEXUS',
      url: '#',
      published_at: now,
      sentiment: 'bullish',
      score: 0.5,
      source_reputation: 1.0,
    },
    {
      title: 'On-chain metrics: BTC exchange reserves declining — long-term holders accumulating',
      source: 'NEXUS',
      url: '#',
      published_at: now - 3600,
      sentiment: 'bullish',
      score: 0.4,
      source_reputation: 1.0,
    },
    {
      title: 'BTC dominance holding steady — market in consolidation phase',
      source: 'NEXUS',
      url: '#',
      published_at: now - 7200,
      sentiment: 'neutral',
      score: 0.0,
      source_reputation: 1.0,
    },
    {
      title: 'Lightning Network capacity reaches new highs — adoption growing',
      source: 'NEXUS',
      url: '#',
      published_at: now - 10800,
      sentiment: 'bullish',
      score: 0.6,
      source_reputation: 1.0,
    },
    {
      title: 'BTC institutional inflows continue — ETF demand remains steady',
      source: 'NEXUS',
      url: '#',
      published_at: now - 14400,
      sentiment: 'bullish',
      score: 0.3,
      source_reputation: 1.0,
    },
  ]
}

function inferSentiment(title: string, marketSentiment?: string, backendScore?: number): 'bullish' | 'bearish' | 'neutral' {
  if (backendScore != null) {
    if (backendScore > 0.1) return 'bullish'
    if (backendScore < -0.1) return 'bearish'
  }
  const text = title.toLowerCase()
  const bullishKeywords = ['surge', 'rally', 'bull', 'breakout', 'all-time high', 'ath', 'gain', 'up', 'rise', 'soar', 'adoption', 'institutional', 'etf', 'halving', 'accumulation', 'accumulating', 'hash rate', 'lightning', 'growing', 'new high', 'strong', 'robust', 'outflow', 'declining reserves', 'inflows', 'demand']
  const bearishKeywords = ['crash', 'dump', 'bear', 'breakdown', 'sell-off', 'selloff', 'drop', 'down', 'fall', 'plunge', 'regulation', 'ban', 'hack', 'scam', 'fraud', 'liquidation', 'fear', 'weak', 'decline', 'inflow rising reserves']

  let bullScore = 0
  let bearScore = 0

  for (const kw of bullishKeywords) {
    if (text.includes(kw)) bullScore++
  }
  for (const kw of bearishKeywords) {
    if (text.includes(kw)) bearScore++
  }

  if (bullScore > bearScore) return 'bullish'
  if (bearScore > bullScore) return 'bearish'
  if (marketSentiment === 'bullish') return 'bullish'
  if (marketSentiment === 'bearish') return 'bearish'
  return 'neutral'
}
