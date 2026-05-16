import { useEffect, useState, useCallback } from 'react'
import {
  Bell,
  Plus,
  Trash2,
  Save,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  XCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Gauge,
  Zap,
  Shield,
  Activity,
} from 'lucide-react'

interface AlertRule {
  id: string
  name: string
  type: 'price' | 'volume' | 'rsi' | 'atr' | 'signal' | 'drawdown' | 'custom'
  condition: 'above' | 'below' | 'crosses_above' | 'crosses_below' | 'equals' | 'changed'
  threshold: number
  enabled: boolean
  cooldown_minutes: number
  last_triggered: number | null
  trigger_count: number
  created_at: number
}

interface AlertConfig {
  rules: AlertRule[]
  sound_enabled: boolean
  notification_enabled: boolean
  max_alerts_per_hour: number
}

const ALERT_TYPE_ICONS: Record<string, React.ReactNode> = {
  price: <TrendingUp size={12} />,
  volume: <Activity size={12} />,
  rsi: <Gauge size={12} />,
  atr: <Zap size={12} />,
  signal: <Bell size={12} />,
  drawdown: <Shield size={12} />,
  custom: <Activity size={12} />,
}

const CONDITION_LABELS: Record<string, string> = {
  above: 'Above',
  below: 'Below',
  crosses_above: 'Crosses Above',
  crosses_below: 'Crosses Below',
  equals: 'Equals',
  changed: 'Changed',
}

const TYPE_COLORS: Record<string, string> = {
  price: '#1fe3a3',
  volume: '#8ab4f8',
  rsi: '#f59f43',
  atr: '#ff5b6b',
  signal: '#c084fc',
  drawdown: '#ff5b6b',
  custom: '#888',
}

const EMPTY_RULE: Omit<AlertRule, 'id' | 'last_triggered' | 'trigger_count' | 'created_at'> = {
  name: '',
  type: 'price',
  condition: 'above',
  threshold: 0,
  enabled: true,
  cooldown_minutes: 5,
}

export function AlertConfigPanel() {
  const [config, setConfig] = useState<AlertConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [editingRule, setEditingRule] = useState<Partial<AlertRule> | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch('/alerts/config')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setConfig(json)
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    setSaveMessage(null)
    try {
      const res = await fetch('/alerts/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSaveMessage('Configuration saved')
      setTimeout(() => setSaveMessage(null), 3000)
    } catch (e: any) {
      setSaveMessage(`Save failed: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const handleAddRule = () => {
    setEditingRule({ ...EMPTY_RULE })
    setShowAddForm(true)
  }

  const handleSaveRule = () => {
    if (!config || !editingRule || !editingRule.name) return
    const newRule: AlertRule = {
      id: editingRule.id ?? `rule_${Date.now()}`,
      name: editingRule.name!,
      type: editingRule.type ?? 'price',
      condition: editingRule.condition ?? 'above',
      threshold: editingRule.threshold ?? 0,
      enabled: editingRule.enabled ?? true,
      cooldown_minutes: editingRule.cooldown_minutes ?? 5,
      last_triggered: editingRule.last_triggered ?? null,
      trigger_count: editingRule.trigger_count ?? 0,
      created_at: editingRule.created_at ?? Date.now(),
    }

    if (editingRule.id) {
      setConfig({
        ...config,
        rules: config.rules.map((r) => (r.id === editingRule.id ? newRule : r)),
      })
    } else {
      setConfig({
        ...config,
        rules: [...config.rules, newRule],
      })
    }
    setEditingRule(null)
    setShowAddForm(false)
  }

  const handleDeleteRule = (id: string) => {
    if (!config) return
    setConfig({
      ...config,
      rules: config.rules.filter((r) => r.id !== id),
    })
  }

  const handleToggleRule = (id: string) => {
    if (!config) return
    setConfig({
      ...config,
      rules: config.rules.map((r) =>
        r.id === id ? { ...r, enabled: !r.enabled } : r
      ),
    })
  }

  const handleToggleSound = () => {
    if (!config) return
    setConfig({ ...config, sound_enabled: !config.sound_enabled })
  }

  const handleToggleNotification = () => {
    if (!config) return
    setConfig({ ...config, notification_enabled: !config.notification_enabled })
  }

  if (loading && !config) {
    return (
      <div className="alert-config-panel">
        <div className="acp-loading">
          <RefreshCw size={16} className="acp-loading-spinner" />
          <span>Loading alert configuration...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="alert-config-panel">
      {/* Header */}
      <div className="acp-header">
        <h2>
          <Bell size={14} />
          Alert Configuration
        </h2>
        <div className="acp-controls">
          <button
            className={`acp-btn ${config?.sound_enabled ? 'active' : ''}`}
            onClick={handleToggleSound}
          >
            <Bell size={12} />
            Sound
          </button>
          <button
            className={`acp-btn ${config?.notification_enabled ? 'active' : ''}`}
            onClick={handleToggleNotification}
          >
            <Activity size={12} />
            Notify
          </button>
          <button className="acp-btn primary" onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <RefreshCw size={12} className="acp-btn-spinner" />
                Saving...
              </>
            ) : (
              <>
                <Save size={12} />
                Save All
              </>
            )}
          </button>
        </div>
      </div>

      {/* Save Message */}
      {saveMessage && (
        <div className={`acp-msg ${saveMessage.includes('failed') ? 'error' : 'success'}`}>
          {saveMessage.includes('failed') ? <XCircle size={12} /> : <CheckCircle size={12} />}
          <span>{saveMessage}</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="acp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="acp-btn" onClick={fetchConfig}>Retry</button>
        </div>
      )}

      {/* Global Settings */}
      {config && (
        <div className="acp-section">
          <h3>Global Settings</h3>
          <div className="acp-global-settings">
            <div className="acp-setting-row">
              <span className="acp-setting-label">Sound Alerts</span>
              <button
                className={`acp-toggle ${config.sound_enabled ? 'on' : 'off'}`}
                onClick={handleToggleSound}
              >
                <span className={`acp-toggle-dot ${config.sound_enabled ? 'on' : 'off'}`} />
              </button>
            </div>
            <div className="acp-setting-row">
              <span className="acp-setting-label">Desktop Notifications</span>
              <button
                className={`acp-toggle ${config.notification_enabled ? 'on' : 'off'}`}
                onClick={handleToggleNotification}
              >
                <span className={`acp-toggle-dot ${config.notification_enabled ? 'on' : 'off'}`} />
              </button>
            </div>
            <div className="acp-setting-row">
              <span className="acp-setting-label">Max Alerts/Hour</span>
              <input
                type="number"
                className="acp-input"
                value={config.max_alerts_per_hour}
                onChange={(e) =>
                  setConfig({ ...config, max_alerts_per_hour: Math.max(1, Number(e.target.value)) })
                }
                min={1}
                max={100}
              />
            </div>
          </div>
        </div>
      )}

      {/* Alert Rules */}
      {config && (
        <div className="acp-section">
          <div className="acp-section-header">
            <h3>Alert Rules ({config.rules.length})</h3>
            <button className="acp-btn" onClick={handleAddRule}>
              <Plus size={12} />
              Add Rule
            </button>
          </div>

          {config.rules.length === 0 && (
            <div className="acp-empty-rules">
              <Bell size={20} />
              <p>No alert rules configured</p>
              <p className="acp-empty-hint">Click "Add Rule" to create your first alert</p>
            </div>
          )}

          <div className="acp-rules-list">
            {config.rules.map((rule) => (
              <div
                key={rule.id}
                className={`acp-rule-card ${!rule.enabled ? 'disabled' : ''}`}
              >
                <div className="acp-rule-header">
                  <div className="acp-rule-identity">
                    <span
                      className="acp-rule-icon"
                      style={{ color: TYPE_COLORS[rule.type] ?? '#888' }}
                    >
                      {ALERT_TYPE_ICONS[rule.type] ?? <Activity size={12} />}
                    </span>
                    <span className="acp-rule-name">{rule.name}</span>
                    <span className="acp-rule-type" style={{ color: TYPE_COLORS[rule.type] ?? '#888' }}>
                      {rule.type}
                    </span>
                  </div>
                  <div className="acp-rule-actions">
                    <button
                      className={`acp-rule-toggle ${rule.enabled ? 'on' : 'off'}`}
                      onClick={() => handleToggleRule(rule.id)}
                      title={rule.enabled ? 'Disable' : 'Enable'}
                    />
                    <button
                      className="acp-rule-edit"
                      onClick={() => {
                        setEditingRule({ ...rule })
                        setShowAddForm(false)
                      }}
                      title="Edit"
                    >
                      Edit
                    </button>
                    <button
                      className="acp-rule-delete"
                      onClick={() => handleDeleteRule(rule.id)}
                      title="Delete"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                <div className="acp-rule-details">
                  <div className="acp-rule-detail">
                    <span className="acp-rule-detail-label">Condition</span>
                    <span className="acp-rule-detail-value">
                      {CONDITION_LABELS[rule.condition] ?? rule.condition}
                    </span>
                  </div>
                  <div className="acp-rule-detail">
                    <span className="acp-rule-detail-label">Threshold</span>
                    <span className="acp-rule-detail-value">{rule.threshold}</span>
                  </div>
                  <div className="acp-rule-detail">
                    <span className="acp-rule-detail-label">Cooldown</span>
                    <span className="acp-rule-detail-value">{rule.cooldown_minutes}m</span>
                  </div>
                  <div className="acp-rule-detail">
                    <span className="acp-rule-detail-label">Triggers</span>
                    <span className="acp-rule-detail-value">{rule.trigger_count}</span>
                  </div>
                  {rule.last_triggered && (
                    <div className="acp-rule-detail">
                      <span className="acp-rule-detail-label">Last Triggered</span>
                      <span className="acp-rule-detail-value">
                        {new Date(rule.last_triggered).toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add/Edit Rule Form */}
      {(showAddForm || editingRule) && editingRule && (
        <div className="acp-section acp-rule-form-section">
          <h3>{editingRule.id ? 'Edit Rule' : 'New Alert Rule'}</h3>
          <div className="acp-rule-form">
            <div className="acp-form-row">
              <label className="acp-form-label">Name</label>
              <input
                type="text"
                className="acp-form-input"
                value={editingRule.name ?? ''}
                onChange={(e) => setEditingRule({ ...editingRule, name: e.target.value })}
                placeholder="e.g., BTC above 100k"
              />
            </div>
            <div className="acp-form-row">
              <label className="acp-form-label">Type</label>
              <select
                className="acp-form-select"
                value={editingRule.type}
                onChange={(e) =>
                  setEditingRule({ ...editingRule, type: e.target.value as AlertRule['type'] })
                }
              >
                <option value="price">Price</option>
                <option value="volume">Volume</option>
                <option value="rsi">RSI</option>
                <option value="atr">ATR</option>
                <option value="signal">Signal</option>
                <option value="drawdown">Drawdown</option>
                <option value="custom">Custom</option>
              </select>
            </div>
            <div className="acp-form-row">
              <label className="acp-form-label">Condition</label>
              <select
                className="acp-form-select"
                value={editingRule.condition}
                onChange={(e) =>
                  setEditingRule({ ...editingRule, condition: e.target.value as AlertRule['condition'] })
                }
              >
                <option value="above">Above</option>
                <option value="below">Below</option>
                <option value="crosses_above">Crosses Above</option>
                <option value="crosses_below">Crosses Below</option>
                <option value="equals">Equals</option>
                <option value="changed">Changed</option>
              </select>
            </div>
            <div className="acp-form-row">
              <label className="acp-form-label">Threshold</label>
              <input
                type="number"
                className="acp-form-input"
                value={editingRule.threshold}
                onChange={(e) =>
                  setEditingRule({ ...editingRule, threshold: Number(e.target.value) })
                }
                step="any"
              />
            </div>
            <div className="acp-form-row">
              <label className="acp-form-label">Cooldown (minutes)</label>
              <input
                type="number"
                className="acp-form-input"
                value={editingRule.cooldown_minutes}
                onChange={(e) =>
                  setEditingRule({ ...editingRule, cooldown_minutes: Math.max(1, Number(e.target.value)) })
                }
                min={1}
              />
            </div>
            <div className="acp-form-actions">
              <button className="acp-btn" onClick={() => { setEditingRule(null); setShowAddForm(false) }}>
                Cancel
              </button>
              <button className="acp-btn primary" onClick={handleSaveRule}>
                <Save size={12} />
                {editingRule.id ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
