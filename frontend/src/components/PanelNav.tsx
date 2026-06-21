import { memo } from 'react'
import {
  Target, Layers, Activity, AlertTriangle, Cpu, Shield, Zap,
  Crosshair, BrainCircuit, Radar, Brain, TrendingUp, Timer,
  Settings, BarChart2, Globe, Database, Bell, BarChart3,
  Users, MessageSquare, Cpu as CpuIcon, Newspaper,
} from 'lucide-react'
import { useChartStore } from '../store/chartStore'
import type { PanelView } from '../App'

type PanelNavProps = {
  panelView: PanelView
  setPanelView: (v: PanelView) => void
}

const NAV_ITEMS: { view: PanelView; icon: typeof Target; label: string; badgeCount?: boolean }[] = [
  { view: 'signals', icon: Target, label: 'Signals' },
  { view: 'scalp', icon: Crosshair, label: 'Scalp' },
  { view: 'brain', icon: BrainCircuit, label: 'AI Brain' },
  { view: 'ai-lab', icon: Radar, label: 'AI Lab' },
  { view: 'ml-dash', icon: CpuIcon, label: 'ML' },
  { view: 'hmm', icon: Activity, label: 'Regime' },
  { view: 'risk', icon: Shield, label: 'Risk' },
  { view: 'momentum', icon: Zap, label: 'Momentum' },
  { view: 'patterns', icon: Layers, label: 'Pats', badgeCount: true },
  { view: 'depth', icon: Activity, label: 'Depth' },
  { view: 'institutional', icon: Cpu, label: 'Inst.' },
  { view: 'trades', icon: TrendingUp, label: 'Paper' },
  { view: 'backtest', icon: Timer, label: 'BT' },
  { view: 'forward', icon: Activity, label: 'Demo' },
  { view: 'position', icon: Target, label: 'Positions' },
  { view: 'log', icon: Activity, label: 'Log' },
  { view: 'nlp', icon: MessageSquare, label: 'NLP' },
  { view: 'news', icon: Newspaper, label: 'News Plan' },
  { view: 'forecast', icon: BarChart3, label: 'Forecast' },
  { view: 'onchain', icon: Users, label: 'OnChain' },
  { view: 'alerts', icon: AlertTriangle, label: 'Alerts' },
  { view: 'alert-config', icon: Bell, label: 'Alert CFG' },
  { view: 'analytics', icon: BarChart2, label: 'Analytics' },
  { view: 'config', icon: Settings, label: 'Config' },
  { view: 'multi-exchange', icon: Globe, label: 'Exchanges' },
  { view: 'model', icon: BrainCircuit, label: 'Model' },
  { view: 'db-status', icon: Database, label: 'DB' },
  { view: 'psychology', icon: Brain, label: 'Psych' },
]

export const PanelNav = memo(function PanelNav({ panelView, setPanelView }: PanelNavProps) {
  const ctx = useChartStore((s) => s.btcPatterns)
  const patternCount = ctx?.patterns?.length ?? 0

  return (
    <div className="panel-nav">
      <div className="panel-switch">
        {NAV_ITEMS.map(({ view, icon: Icon, label, badgeCount }) => (
          <button key={view} className={panelView === view ? 'active' : ''} onClick={() => setPanelView(view)}>
            <Icon size={11} />
            {label}
            {badgeCount && patternCount > 0 && <span className="badge-count">{patternCount}</span>}
          </button>
        ))}
      </div>
    </div>
  )
})
