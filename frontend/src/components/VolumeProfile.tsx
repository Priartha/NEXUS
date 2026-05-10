import { useMemo, useState } from 'react'

interface VolumeBin {
  price: number
  volume: number
  is_poc: boolean
  is_value_area: boolean
}

interface Props {
  bins: VolumeBin[]
  poc: number | null
  value_area_low: number | null
  value_area_high: number | null
  total_volume: number
}

export default function VolumeProfile({ bins, poc, value_area_low, value_area_high, total_volume }: Props) {
  const [expanded, setExpanded] = useState(false)
  const maxVol = useMemo(() => Math.max(...bins.map((b) => b.volume), 0.01), [bins])

  if (!bins.length) return null

  const display = expanded ? bins : bins.slice(-12)

  return (
    <div className="volume-profile">
      <div className="vp-header" onClick={() => setExpanded(!expanded)}>
        <span>Volume Profile {expanded ? '▲' : '▼'}</span>
        {poc != null && <span className="vp-poc">POC ${poc.toFixed(1)}</span>}
        {value_area_low != null && value_area_high != null && (
          <span className="vp-va">VA ${value_area_low.toFixed(1)}-${value_area_high.toFixed(1)}</span>
        )}
      </div>
      <div className="vp-bins">
        {display.map((bin, i) => (
          <div key={i} className={`vp-bin ${bin.is_poc ? 'poc' : ''} ${bin.is_value_area ? 'va' : ''}`}>
            <span className="vp-price">${bin.price.toFixed(1)}</span>
            <div className="vp-bar-track">
              <div className="vp-bar" style={{ width: `${(bin.volume / maxVol) * 100}%` }} />
            </div>
            <span className="vp-vol">{bin.volume.toFixed(1)}</span>
          </div>
        ))}
      </div>
      <div className="vp-footer">
        <span>Total Vol: {total_volume.toFixed(1)}</span>
        <span>{display.length}/{bins.length} bins</span>
      </div>
    </div>
  )
}
