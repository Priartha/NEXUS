import { memo } from 'react'
import { RefreshCw } from 'lucide-react'
import { useChartStore } from '../store/chartStore'
import { formatPrice } from '../types/market'
import { SESSION_COLORS } from './panelConstants'

type TopbarProps = {
  reconnect: () => void
}

export const Topbar = memo(function Topbar({ reconnect }: TopbarProps) {
  const candles = useChartStore((s) => s.candles)
  const quote = useChartStore((s) => s.quote)
  const btcPatterns = useChartStore((s) => s.btcPatterns)
  const availableTimeframes = useChartStore((s) => s.availableTimeframes)
  const selectedTimeframe = useChartStore((s) => s.selectedTimeframe)
  const setTimeframe = useChartStore((s) => s.setTimeframe)
  const connectionStatus = useChartStore((s) => s.connectionStatus)

  const latest = candles.at(-1)
  const previous = candles.at(-2)
  const displayPrice = quote?.mid ?? quote?.last_trade ?? quote?.mark_price ?? latest?.close
  const refPrice = previous?.close ?? latest?.open ?? displayPrice
  const change = displayPrice && refPrice ? displayPrice - refPrice : 0
  const changePct = refPrice && Number.isFinite(refPrice) && refPrice !== 0 ? (change / refPrice) * 100 : 0
  const connected = connectionStatus === 'open'
  const sessionColor = SESSION_COLORS[btcPatterns?.session ?? ''] ?? '#888'

  return (
    <header className="topbar">
      <div className="identity">
        <div className="logo-icon">
          <img src="/logo.svg" alt="NEXUS" className="logo-img" />
        </div>
      </div>
      <div className="market-readout">
        <span className="last-price">{formatPrice(displayPrice)}</span>
        <span className={`change ${change >= 0 ? 'positive' : 'negative'}`}>
          {change >= 0 ? '+' : ''}{formatPrice(change)} ({changePct.toFixed(2)}%)
        </span>
        {btcPatterns && (
          <span className="session-badge" style={{ borderColor: sessionColor, color: sessionColor }}>
            {btcPatterns.session ?? '--'}
          </span>
        )}
        <span className="quote-source">{quote?.source ?? 'candle'}</span>
      </div>
      <div className="toolbar">
        <div className="timeframe-control">
          {availableTimeframes.map((option) => (
            <button key={option} type="button" className={option === selectedTimeframe ? 'active' : ''} onClick={() => setTimeframe(option)}>{option}</button>
          ))}
        </div>
        <div className={`connection-pill ${connected ? 'connected' : 'offline'}`}>
          <span className="status-dot" />
          <span>{connected ? 'Live' : connectionStatus}</span>
        </div>
        <button type="button" className="icon-button" onClick={reconnect} title="Reconnect">
          <RefreshCw size={15} />
        </button>
      </div>
    </header>
  )
})
