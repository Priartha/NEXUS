import { useState } from 'react'
import {
  Settings,
  Save,
  RotateCcw,
  Info,
  AlertTriangle,
  CheckCircle,
  Sliders,
  Target,
  TrendingUp,
  Clock,
  Shield,
  Zap,
} from 'lucide-react'

interface StrategyConfig {
  stopLossMultiplier: number
  adxThreshold: number
  useAdxFilter: boolean
  useLimitOrders: boolean
  minConfidence: number
  signalCooldown: number
  breakevenThreshold: number
  partialTp1R: number
  partialTp2R: number
  maxHoldBars: number
  positionSizePct: number
  maxConcurrent: number
}

const DEFAULT_CONFIG: StrategyConfig = {
  stopLossMultiplier: 0.5,
  adxThreshold: 20.0,
  useAdxFilter: true,
  useLimitOrders: true,
  minConfidence: 0.55,
  signalCooldown: 12,
  breakevenThreshold: 0.5,
  partialTp1R: 1.0,
  partialTp2R: 1.5,
  maxHoldBars: 12,
  positionSizePct: 2.0,
  maxConcurrent: 1,
}

const PRESETS: Record<string, { name: string; config: StrategyConfig; description: string }> = {
  combo3: {
    name: 'Combo3 (Recommended)',
    description: 'Tight stops, quick exits - Best backtest results (PF=3.17)',
    config: {
      stopLossMultiplier: 0.5,
      adxThreshold: 20.0,
      useAdxFilter: true,
      useLimitOrders: true,
      minConfidence: 0.55,
      signalCooldown: 12,
      breakevenThreshold: 0.5,
      partialTp1R: 1.0,
      partialTp2R: 1.5,
      maxHoldBars: 12,
      positionSizePct: 2.0,
      maxConcurrent: 1,
    },
  },
  sl05: {
    name: 'SL0.5 Conservative',
    description: 'Tight stops with standard exits (PF=1.36)',
    config: {
      stopLossMultiplier: 0.5,
      adxThreshold: 20.0,
      useAdxFilter: true,
      useLimitOrders: true,
      minConfidence: 0.55,
      signalCooldown: 12,
      breakevenThreshold: 0.75,
      partialTp1R: 1.0,
      partialTp2R: 2.0,
      maxHoldBars: 25,
      positionSizePct: 2.0,
      maxConcurrent: 1,
    },
  },
  wide: {
    name: 'Wide Stops (Old)',
    description: 'Previous configuration with wider stops (PF=0.26)',
    config: {
      stopLossMultiplier: 2.5,
      adxThreshold: 20.0,
      useAdxFilter: true,
      useLimitOrders: true,
      minConfidence: 0.55,
      signalCooldown: 12,
      breakevenThreshold: 0.75,
      partialTp1R: 1.0,
      partialTp2R: 2.0,
      maxHoldBars: 25,
      positionSizePct: 2.0,
      maxConcurrent: 1,
    },
  },
}

export function StrategyConfigPanel() {
  const [config, setConfig] = useState<StrategyConfig>(DEFAULT_CONFIG)
  const [activePreset, setActivePreset] = useState<string>('combo3')
  const [saved, setSaved] = useState(false)

  const applyPreset = (key: string) => {
    const preset = PRESETS[key]
    if (preset) {
      setConfig(preset.config)
      setActivePreset(key)
      setSaved(false)
    }
  }

  const updateConfig = (key: keyof StrategyConfig, value: number | boolean) => {
    setConfig((prev) => ({ ...prev, [key]: value }))
    setActivePreset('')
    setSaved(false)
  }

  const handleSave = () => {
    localStorage.setItem('nexus_strategy_config', JSON.stringify(config))
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleReset = () => {
    setConfig(DEFAULT_CONFIG)
    setActivePreset('combo3')
    setSaved(false)
  }

  return (
    <div className="strategy-config-panel">
      {/* Header */}
      <div className="scp-header">
        <h2><Settings size={14} /> Strategy Configuration</h2>
        <div className="scp-header-actions">
          <button className="scp-btn reset" onClick={handleReset} title="Reset to defaults">
            <RotateCcw size={12} /> Reset
          </button>
          <button className={`scp-btn save ${saved ? 'saved' : ''}`} onClick={handleSave}>
            {saved ? <CheckCircle size={12} /> : <Save size={12} />}
            {saved ? 'Saved!' : 'Save'}
          </button>
        </div>
      </div>

      {/* Presets */}
      <div className="scp-section">
        <h3><Sliders size={12} /> Quick Presets</h3>
        <div className="scp-presets">
          {Object.entries(PRESETS).map(([key, preset]) => (
            <button
              key={key}
              className={`scp-preset ${activePreset === key ? 'active' : ''}`}
              onClick={() => applyPreset(key)}
            >
              <div className="scp-preset-header">
                <span className="scp-preset-name">{preset.name}</span>
                {activePreset === key && <CheckCircle size={12} className="scp-preset-check" />}
              </div>
              <p className="scp-preset-desc">{preset.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Risk Management */}
      <div className="scp-section">
        <h3><Shield size={12} /> Risk Management</h3>
        <div className="scp-grid">
          <div className="scp-field">
            <label>
              <Target size={11} />
              Stop Loss (× ATR)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5.0"
              value={config.stopLossMultiplier}
              onChange={(e) => updateConfig('stopLossMultiplier', parseFloat(e.target.value) || 0.5)}
            />
            <span className="scp-hint">Distance from entry to stop loss</span>
          </div>

          <div className="scp-field">
            <label>
              <TrendingUp size={11} />
              Position Size (%)
            </label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              max="10.0"
              value={config.positionSizePct}
              onChange={(e) => updateConfig('positionSizePct', parseFloat(e.target.value) || 2.0)}
            />
            <span className="scp-hint">% of balance per trade</span>
          </div>

          <div className="scp-field">
            <label>
              <Shield size={11} />
              Max Concurrent Trades
            </label>
            <input
              type="number"
              step="1"
              min="1"
              max="5"
              value={config.maxConcurrent}
              onChange={(e) => updateConfig('maxConcurrent', parseInt(e.target.value) || 1)}
            />
            <span className="scp-hint">Maximum open trades at once</span>
          </div>
        </div>
      </div>

      {/* Exit Strategy */}
      <div className="scp-section">
        <h3><Zap size={12} /> Exit Strategy</h3>
        <div className="scp-grid">
          <div className="scp-field">
            <label>
              <TrendingUp size={11} />
              Breakeven Threshold (× R)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="2.0"
              value={config.breakevenThreshold}
              onChange={(e) => updateConfig('breakevenThreshold', parseFloat(e.target.value) || 0.5)}
            />
            <span className="scp-hint">Move SL to BE at this profit multiple</span>
          </div>

          <div className="scp-field">
            <label>
              <Target size={11} />
              Partial TP1 (× R)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.5"
              max="5.0"
              value={config.partialTp1R}
              onChange={(e) => updateConfig('partialTp1R', parseFloat(e.target.value) || 1.0)}
            />
            <span className="scp-hint">Take 50% profit at this level</span>
          </div>

          <div className="scp-field">
            <label>
              <Target size={11} />
              Partial TP2 (× R)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.5"
              max="5.0"
              value={config.partialTp2R}
              onChange={(e) => updateConfig('partialTp2R', parseFloat(e.target.value) || 1.5)}
            />
            <span className="scp-hint">Take remaining 50% at this level</span>
          </div>

          <div className="scp-field">
            <label>
              <Clock size={11} />
              Max Hold (bars)
            </label>
            <input
              type="number"
              step="1"
              min="6"
              max="100"
              value={config.maxHoldBars}
              onChange={(e) => updateConfig('maxHoldBars', parseInt(e.target.value) || 12)}
            />
            <span className="scp-hint">Force exit after N candles</span>
          </div>
        </div>
      </div>

      {/* Signal Filters */}
      <div className="scp-section">
        <h3><Info size={12} /> Signal Filters</h3>
        <div className="scp-grid">
          <div className="scp-field">
            <label>
              <TrendingUp size={11} />
              Min Confidence
            </label>
            <input
              type="number"
              step="0.05"
              min="0.3"
              max="0.9"
              value={config.minConfidence}
              onChange={(e) => updateConfig('minConfidence', parseFloat(e.target.value) || 0.55)}
            />
            <span className="scp-hint">Minimum signal confidence to trade</span>
          </div>

          <div className="scp-field">
            <label>
              <Clock size={11} />
              Signal Cooldown (candles)
            </label>
            <input
              type="number"
              step="1"
              min="1"
              max="48"
              value={config.signalCooldown}
              onChange={(e) => updateConfig('signalCooldown', parseInt(e.target.value) || 12)}
            />
            <span className="scp-hint">Candles between new signals</span>
          </div>

          <div className="scp-field">
            <label>
              <Sliders size={11} />
              ADX Threshold
            </label>
            <input
              type="number"
              step="1"
              min="10"
              max="50"
              value={config.adxThreshold}
              onChange={(e) => updateConfig('adxThreshold', parseFloat(e.target.value) || 20.0)}
            />
            <span className="scp-hint">Minimum ADX for trending market</span>
          </div>
        </div>

        <div className="scp-toggles">
          <label className="scp-toggle">
            <input
              type="checkbox"
              checked={config.useAdxFilter}
              onChange={(e) => updateConfig('useAdxFilter', e.target.checked)}
            />
            <span className="scp-toggle-label">Use ADX Filter</span>
          </label>

          <label className="scp-toggle">
            <input
              type="checkbox"
              checked={config.useLimitOrders}
              onChange={(e) => updateConfig('useLimitOrders', e.target.checked)}
            />
            <span className="scp-toggle-label">Use Limit Orders</span>
          </label>
        </div>
      </div>

      {/* Warning */}
      <div className="scp-warning">
        <AlertTriangle size={14} />
        <div>
          <strong>Important:</strong> Changes to strategy configuration require a backend restart to take effect.
          The current active configuration uses Combo3 parameters (SL=0.5×, BE@0.5R, TP2=1.5R, Hold=12 bars).
        </div>
      </div>
    </div>
  )
}
