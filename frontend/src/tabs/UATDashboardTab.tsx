import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Wifi, WifiOff } from 'lucide-react'
import { fetchStreamConfig } from '../api/stream'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { LiveBadge } from '../components/common/LiveBadge'
import { useCustomWidgetStream } from '../hooks/useCustomWidgetStream'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import type { Widget, GridLayout } from '../types'
import { TabThemeContext } from '../context/TabThemeContext'

const STORAGE_KEY = 'gd_ws_uat'
const SEED_IDS = ['fte_airflow_dags', 'fte_schema_audit', 'fte_excel_mapping']

const SEEDS: Widget[] = [
  {
    id: 'fte_airflow_dags', title: 'Airflow DAGs',
    chart_type: 'airflow_dags', x_axis: undefined, y_axis: [],
    stacked: false, dual_axis: false, ai_description: '',
    sql: '', data: [],
    layout: { i: 'fte_airflow_dags', x: 0, y: 0, w: 12, h: 9, minH: 6 },
  },
  {
    id: 'fte_schema_audit', title: 'Schema Mismatch',
    chart_type: 'schema_audit', x_axis: undefined, y_axis: [],
    stacked: false, dual_axis: false, ai_description: '',
    sql: '', data: [],
    layout: { i: 'fte_schema_audit', x: 0, y: 9, w: 12, h: 12, minH: 8 },
  },
  {
    id: 'fte_excel_mapping', title: 'Excel Mapping',
    chart_type: 'excel_mapping', x_axis: undefined, y_axis: [],
    stacked: false, dual_axis: false, ai_description: '',
    sql: '', data: [],
    layout: { i: 'fte_excel_mapping', x: 0, y: 21, w: 12, h: 10, minH: 6 },
  },
]

function loadState(): Widget[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return SEEDS
    const parsed = JSON.parse(raw)
    const saved: Widget[] = (parsed.widgets ?? []).map((w: Widget) =>
      w.chart_type === 'airflow_dags' ? { ...w, lockedAirflowEnv: undefined } : w
    )
    const savedMap = new Map(saved.map(w => [w.id, w]))
    const merged = SEEDS.map(s => {
      const p = savedMap.get(s.id)
      return p ? { ...s, live: p.live, layout: p.layout ?? s.layout } : s
    })
    const userAdded = saved.filter(w => !SEED_IDS.includes(w.id))
    return [...merged, ...userAdded]
  } catch { return SEEDS }
}

function saveState(widgets: Widget[]) {
  try {
    const toSave = widgets.map(w => SEED_IDS.includes(w.id) ? { ...w, data: [] } : w)
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ widgets: toSave }))
  } catch { /* quota exceeded */ }
}

interface Props {
  tabLabel?: string
  onRegisterAddWidget?: (fn: (w: Widget) => void) => void
  onOpenDagTab: (dagId: string, env: string) => void
}

export function UATDashboardTab({ tabLabel, onRegisterAddWidget, onOpenDagTab }: Props) {
  const tabTheme = { headerBg: 'bg-yellow-100', headerBorder: 'border-yellow-100', airflowEnv: 'UAT', schemaAuditEnv: 'uat', tabPrefix: 'UAT', onOpenDagTab }

  const [widgets, setWidgets] = useState<Widget[]>(loadState)
  const [exporting, setExporting] = useState(false)

  const { data: streamConfig } = useQuery({ queryKey: ['stream', 'config'], queryFn: fetchStreamConfig, staleTime: Infinity })
  const pollInterval = streamConfig?.poll_interval_seconds

  useEffect(() => { saveState(widgets) }, [widgets])

  const liveStatus = useCustomWidgetStream(
    widgets,
    (id, freshData) => setWidgets(prev => prev.map(w => w.id === id ? { ...w, data: freshData } : w)),
  )

  const eligibleWidgets = widgets.filter(w => (w.sql?.trim() || w.chart_type === 'airflow_dags') && w.chart_type !== 'kpi')
  const anyLive = eligibleWidgets.some(w => w.live)

  function setAllLive(flag: boolean) {
    setWidgets(prev => prev.map(w =>
      (w.sql?.trim() || w.chart_type === 'airflow_dags') && w.chart_type !== 'kpi' ? { ...w, live: flag } : w
    ))
  }

  const addExternalWidget = useCallback((w: Widget) => {
    setWidgets(prev => prev.some(x => x.id === w.id) ? prev : [...prev, w])
  }, [])
  useEffect(() => { onRegisterAddWidget?.(addExternalWidget) }, [onRegisterAddWidget, addExternalWidget])

  const removeWidget = useCallback((id: string) => setWidgets(prev => prev.filter(w => w.id !== id)), [])

  const saveFavorite = useCallback(async (widget: Widget) => {
    try { await createFavorite({ name: widget.title, nl_query: widget.nl_query, sql_query: widget.sql, chart_type: widget.chart_type }) }
    catch { /* silent */ }
  }, [])

  const handleLayoutChange = useCallback((newLayouts: GridLayout[]) => {
    setWidgets(prev => prev.map(w => {
      const l = newLayouts.find(gl => gl.i === w.id)
      return l ? { ...w, layout: l } : w
    }))
  }, [])

  const updateWidget = useCallback((updated: Widget) => {
    setWidgets(prev => prev.map(w => w.id === updated.id ? updated : w))
  }, [])

  async function handleExport() {
    if (!widgets.length) return
    setExporting(true)
    try { await exportPDF(tabLabel ?? 'UAT Dashboard', tabLabel ?? 'UAT Dashboard', widgets) }
    finally { setExporting(false) }
  }

  return (
    <TabThemeContext.Provider value={tabTheme}>
      <div className="flex flex-col gap-4 p-4">
        <div className="flex items-center gap-2 flex-wrap">
          <LiveBadge status={liveStatus} />
          {eligibleWidgets.length > 0 && (
            <div className="flex flex-col items-center gap-0.5">
              <button
                onClick={() => setAllLive(!anyLive)}
                className={`flex items-center gap-1.5 text-sm border px-3 py-2 rounded-lg transition-colors ${anyLive ? 'border-emerald-300 text-emerald-700 bg-emerald-50 hover:bg-emerald-100' : 'border-gray-200 text-gray-500 hover:text-gray-700'}`}
              >
                {anyLive ? <WifiOff size={14} /> : <Wifi size={14} />}
                {anyLive ? 'Stop Live' : 'Go Live'}
              </button>
              {pollInterval && <span className="text-[10px] text-red-500">Every {pollInterval}sec Refresh</span>}
            </div>
          )}
          <button onClick={handleExport} disabled={exporting} className="ml-auto flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg">
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export PDF'}
          </button>
        </div>

        <div className="overflow-auto">
          <DashboardGrid widgets={widgets} onRemove={removeWidget} onSaveFavorite={saveFavorite} onLayoutChange={handleLayoutChange} onUpdate={updateWidget} />
        </div>
      </div>
    </TabThemeContext.Provider>
  )
}
