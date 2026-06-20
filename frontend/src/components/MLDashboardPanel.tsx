import { useEffect, useState, useCallback } from 'react'
import {
  RefreshCw,
  AlertTriangle,
  Brain,
  Activity,
  Cpu,
  Target,
  Shield,
  DollarSign,
} from 'lucide-react'

interface XGBState {
  is_trained: boolean
  model_version: number
  total_predictions: number
  accuracy: number
  last_train_ts?: number
  feature_count: number
  top_features: Array<[string, number]>
  threshold_long: number
  threshold_short: number
}

interface RLState {
  is_trained: boolean
  total_steps: number
  recent_decisions: any[]
  model_version: number
  episodes: number
  avg_reward: number
}

interface FundingState {
  current_position: string | null
  position_entry_ts: number
  history_length: number
  entry_zscore: number
  exit_zscore: number
  max_leverage: number
}

interface CVDState {
  active_divergences: number
  last_divergence_ts?: number
  price_history: number
  cvd_history: number
}

interface AdaptiveSLTPState {
  sl_quantile_default: number
  tp_quantile_default: number
  regime_sl_mult: Record<string, number>
  regime_tp_mult: Record<string, number>
}

export function MLDashboardPanel() {
  const [xgboost, setXGBoost] = useState<XGBState | null>(null)
  const [rl, setRL] = useState<RLState | null>(null)
  const [funding, setFunding] = useState<FundingState | null>(null)
  const [cvd, setCVD] = useState<CVDState | null>(null)
  const [adaptive, setAdaptive] = useState<AdaptiveSLTPState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [trainMsg, setTrainMsg] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setTrainMsg(null)
    try {
      const [xgbRes, rlRes, fundRes, cvdRes, adaptRes] = await Promise.allSettled([
        fetch('/ml/xgboost/state'),
        fetch('/rl/sizing'),
        fetch('/funding/strategy/state'),
        fetch('/cvd/divergence'),
        fetch('/adaptive-sltp/state'),
      ])

      if (xgbRes.status === 'fulfilled') {
        const json = await xgbRes.value.json()
        setXGBoost(json)
      }
      if (rlRes.status === 'fulfilled') {
        const json = await rlRes.value.json()
        setRL(json)
      }
      if (fundRes.status === 'fulfilled') {
        const json = await fundRes.value.json()
        setFunding(json)
      }
      if (cvdRes.status === 'fulfilled') {
        const json = await cvdRes.value.json()
        setCVD(json)
      }
      if (adaptRes.status === 'fulfilled') {
        const json = await adaptRes.value.json()
        setAdaptive(json)
      }
      setError(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 30000)
    return () => clearInterval(interval)
  }, [fetchAll])

  const triggerTrain = async () => {
    try {
      const res = await fetch('/ml/xgboost/train', { method: 'POST' })
      const json = await res.json()
      setTrainMsg(json.status === 'ok' ? `Trained: accuracy=${json.result?.accuracy?.toFixed(3) ?? '?'}` : `Error: ${json.detail}`)
      fetchAll()
    } catch (e: any) {
      setTrainMsg(`Failed: ${e.message}`)
    }
  }

  if (loading) {
    return (
      <div className="ml-dashboard-panel">
        <div className="dsp-loading">
          <RefreshCw size={16} className="dsp-loading-spinner" />
          <span>Loading ML dashboard...</span>
        </div>
      </div>
    )
  }

  const ModelCard = ({ title, icon, children, onAction, actionLabel }: {
    title: string; icon: React.ReactNode; children: React.ReactNode;
    onAction?: () => void; actionLabel?: string
  }) => (
    <div className="ml-card">
      <div className="ml-card-header">
        {icon}
        <span className="ml-card-title">{title}</span>
        {onAction && (
          <button className="dsp-btn ml-card-action" onClick={onAction}>
            {actionLabel ?? 'Action'}
          </button>
        )}
      </div>
      <div className="ml-card-body">{children}</div>
    </div>
  )

  const StatRow = ({ label, value, color }: { label: string; value: string; color?: string }) => (
    <div className="ml-stat-row">
      <span className="ml-stat-label">{label}</span>
      <span className="ml-stat-value" style={color ? { color } : undefined}>{value}</span>
    </div>
  )

  return (
    <div className="ml-dashboard-panel">
      <div className="dsp-header">
        <h2><Cpu size={14} /> ML Model Dashboard</h2>
        <div className="dsp-controls">
          {trainMsg && <span className="dsp-badge">{trainMsg}</span>}
          <button className="dsp-btn" onClick={fetchAll} title="Refresh">
            <RefreshCw size={12} />
          </button>
        </div>
      </div>

      {error && (
        <div className="dsp-error">
          <AlertTriangle size={12} />
          <span>{error}</span>
          <button className="dsp-btn" onClick={fetchAll}>Retry</button>
        </div>
      )}

      <div className="ml-dashboard-grid">
        <ModelCard title="XGBoost Classifier" icon={<Brain size={14} />} onAction={triggerTrain} actionLabel="Retrain">
          <StatRow label="Trained" value={xgboost?.is_trained ? 'Yes' : 'No'} color={xgboost?.is_trained ? '#22c55e' : '#ef4444'} />
          <StatRow label="Accuracy" value={xgboost?.accuracy !== null && xgboost?.accuracy !== undefined ? `${(xgboost.accuracy * 100).toFixed(1)}%` : '--'} />
          <StatRow label="Predictions" value={xgboost?.total_predictions?.toLocaleString() ?? '0'} />
          {(xgboost?.last_train_ts ?? 0) > 0 && <StatRow label="Last Train" value={new Date(xgboost!.last_train_ts!).toLocaleString()} />}
          {xgboost?.top_features && xgboost.top_features.length > 0 && (
            <div className="ml-features">
              <span className="ml-stat-label">Top Features:</span>
              {xgboost.top_features.slice(0, 5).map(([name, imp]) => (
                <div key={name} className="ml-feature-row">
                  <span className="ml-feature-name">{name}</span>
                  <div className="regime-prob-bar-bg">
                    <div className="regime-prob-bar" style={{ width: `${(imp * 100).toFixed(1)}%`, backgroundColor: '#3b82f6' }} />
                  </div>
                  <span className="ml-feature-imp">{(imp * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          )}
        </ModelCard>

        <ModelCard title="RL Position Sizing" icon={<Target size={14} />}>
          <StatRow label="Trained" value={rl?.is_trained ? 'Yes' : 'No'} color={rl?.is_trained ? '#22c55e' : '#ef4444'} />
          <StatRow label="Total Steps" value={rl?.total_steps?.toLocaleString() ?? '0'} />
          <StatRow label="Episodes" value={rl?.episodes?.toLocaleString() ?? '0'} />
          <StatRow label="Avg Reward" value={rl?.avg_reward !== undefined ? rl.avg_reward.toFixed(4) : '0'} />
          <StatRow label="Version" value={`v${rl?.model_version ?? 0}`} />
        </ModelCard>

        <ModelCard title="Funding Rate Strategy" icon={<DollarSign size={14} />}>
          <StatRow label="Current Position" value={funding?.current_position ?? 'none'} color={
            funding?.current_position === 'long' ? '#22c55e' : funding?.current_position === 'short' ? '#ef4444' : undefined
          } />
          <StatRow label="Entry Z-Score" value={funding?.entry_zscore?.toFixed(2) ?? '--'} />
          <StatRow label="Exit Z-Score" value={funding?.exit_zscore?.toFixed(2) ?? '--'} />
          <StatRow label="Max Leverage" value={`${funding?.max_leverage ?? 0}x`} />
          <StatRow label="History" value={`${funding?.history_length ?? 0} samples`} />
        </ModelCard>

        <ModelCard title="Adaptive SL/TP" icon={<Shield size={14} />}>
          <StatRow label="SL Default" value={adaptive?.sl_quantile_default?.toFixed(2) ?? '--'} />
          <StatRow label="TP Default" value={adaptive?.tp_quantile_default?.toFixed(2) ?? '--'} />
          {adaptive?.regime_sl_mult && Object.keys(adaptive.regime_sl_mult).length > 0 && (
            <div className="ml-features">
              <span className="ml-stat-label">SL Multipliers:</span>
              {Object.entries(adaptive.regime_sl_mult).slice(0, 4).map(([regime, mult]) => (
                <div key={regime} className="ml-feature-row">
                  <span className="ml-feature-name">{regime.replace('_', ' ')}</span>
                  <span className="ml-feature-imp">{(mult as number).toFixed(2)}x</span>
                </div>
              ))}
            </div>
          )}
        </ModelCard>

        <ModelCard title="CVD Divergence" icon={<Activity size={14} />}>
          <StatRow label="Active Divergences" value={(cvd?.active_divergences ?? 0).toString()} color={(cvd?.active_divergences ?? 0) > 0 ? '#ef4444' : '#22c55e'} />
          <StatRow label="Price History" value={cvd?.price_history?.toString() ?? '0'} />
          <StatRow label="CVD History" value={cvd?.cvd_history?.toString() ?? '0'} />
          {(cvd?.last_divergence_ts ?? 0) > 0 && (
            <StatRow label="Last Divergence" value={new Date(cvd!.last_divergence_ts!).toLocaleString()} />
          )}
        </ModelCard>
      </div>
    </div>
  )
}
