import { useMemo } from 'react'
import type { OrderbookDepthLevel } from '../types/market'
import { formatPrice } from '../types/market'

interface Props {
  depthLevels: OrderbookDepthLevel[]
}

export default function DepthHeatmap({ depthLevels }: Props) {
  const maxSaturation = useMemo(
    () => Math.max(...depthLevels.map((d) => d.saturation), 0.01),
    [depthLevels],
  )

  const bids = depthLevels.filter((d) => d.level_type === 'bid').slice(0, 5)
  const asks = depthLevels.filter((d) => d.level_type === 'ask').slice(0, 5)

  if (depthLevels.length === 0) return null

  return (
    <div className="depth-heatmap">
      <div className="dh-section">
        <span className="dh-label">Bids</span>
        {bids.map((level) => (
          <div key={level.id} className="dh-row">
            <span className="dh-tier">T{level.depth_tier}</span>
            <span className="dh-price bullish">${formatPrice(level.price_level)}</span>
            <div className="dh-bar-track">
              <div
                className="dh-bar bid"
                style={{ width: `${(level.saturation / maxSaturation) * 100}%` }}
              />
            </div>
            <span className="dh-count">{level.order_count} orders</span>
          </div>
        ))}
      </div>
      <div className="dh-divider" />
      <div className="dh-section">
        <span className="dh-label">Asks</span>
        {asks.map((level) => (
          <div key={level.id} className="dh-row">
            <span className="dh-tier">T{level.depth_tier}</span>
            <span className="dh-price bearish">${formatPrice(level.price_level)}</span>
            <div className="dh-bar-track">
              <div
                className="dh-bar ask"
                style={{ width: `${(level.saturation / maxSaturation) * 100}%` }}
              />
            </div>
            <span className="dh-count">{level.order_count} orders</span>
          </div>
        ))}
      </div>
    </div>
  )
}
