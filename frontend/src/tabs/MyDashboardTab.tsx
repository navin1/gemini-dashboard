import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Wifi, WifiOff } from 'lucide-react'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { KPICard } from '../components/Header/KPICard'
import { LiveBadge } from '../components/common/LiveBadge'
import { useCustomWidgetStream } from '../hooks/useCustomWidgetStream'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import { fetchStreamConfig } from '../api/stream'
import type { Widget, GridLayout, CustomKpi } from '../types'

let _id = 0
function nextId() { return `w_${++_id}_${Date.now()}` }

const DEFAULT_LAYOUT: GridLayout = { i: '', x: 0, y: 0, w: 6, h: 10 }

function storageKey(tabId: string) { return `gd_ws_${tabId}` }

function loadState(tabId: string): { widgets: Widget[]; customKpis: CustomKpi[] } {
  try {
    const raw = localStorage.getItem(storageKey(tabId))
    return raw ? JSON.parse(raw) : { widgets: [], customKpis: [] }
  } catch { return { widgets: [], customKpis: [] } }
}

interface Props {
  tabId?: string
  tabLabel?: string
  onRegisterAddWidget?: (fn: (widget: Widget) => void) => void
}

export function MyDashboardTab({ tabId = 'ai', tabLabel, onRegisterAddWidget }: Props) {
  const saved = loadState(tabId)
  const [widgets,    setWidgets]    = useState<Widget[]>(saved.widgets)
  const [customKpis, setCustomKpis] = useState<CustomKpi[]>(saved.customKpis)
  const [exporting,  setExporting]  = useState(false)

  const { data: streamConfig } = useQuery({
    queryKey: ['stream', 'config'],
    queryFn: fetchStreamConfig,
    staleTime: Infinity,
  })
  const pollInterval = streamConfig?.poll_interval_seconds

  // Persist on every change
  useEffect(() => {
    try { localStorage.setItem(storageKey(tabId), JSON.stringify({ widgets, customKpis })) }
    catch { /* quota exceeded — silent */ }
  }, [tabId, widgets, customKpis])

  const liveStatus = useCustomWidgetStream(
    widgets,
    (id, freshData) => setWidgets(prev =>
      prev.map(w => w.id === id ? { ...w, data: freshData } : w)
    ),
  )

  const eligibleWidgets = widgets.filter(w => (w.sql?.trim() || w.chart_type === 'airflow_dags') && w.chart_type !== 'kpi')
  const anyLive = eligibleWidgets.some(w => w.live)

  function setAllLive(flag: boolean) {
    setWidgets(prev => prev.map(w =>
      (w.sql?.trim() || w.chart_type === 'airflow_dags') && w.chart_type !== 'kpi' ? { ...w, live: flag } : w
    ))
  }

  const addWidget = useCallback((widget: Widget) => {
    if (widget.chart_type === 'kpi') {
      const items: CustomKpi[] = Object.entries(widget.data[0] ?? {})
        .filter(([, v]) => typeof v === 'number')
        .map(([k, v]) => ({ id: `${widget.id || nextId()}_${k}`, label: k.replace(/_/g, ' '), value: v as number }))
      setCustomKpis((prev) => {
        const newItems = items.filter((item) => !prev.some((p) => p.id === item.id))
        return [...prev, ...newItems]
      })
      return
    }
    setWidgets((prev) => {
      const id = widget.id || nextId()
      if (prev.some((w) => w.id === id)) return prev
      const positioned: Widget = {
        ...widget,
        id,
        layout: widget.layout ?? {
          ...DEFAULT_LAYOUT,
          i: id,
          x: (prev.length * 6) % 12,
          y: Math.floor(prev.length / 2) * 10,
        },
      }
      return [...prev, positioned]
    })
  }, [])

  useEffect(() => { onRegisterAddWidget?.(addWidget) }, [onRegisterAddWidget, addWidget])

  const removeWidget    = useCallback((id: string) => setWidgets((prev)    => prev.filter((w) => w.id !== id)), [])
  const removeCustomKpi = useCallback((id: string) => setCustomKpis((prev) => prev.filter((k) => k.id !== id)), [])

  const saveFavorite = useCallback(async (widget: Widget) => {
    try {
      await createFavorite({ name: widget.title, nl_query: widget.nl_query, sql_query: widget.sql, chart_type: widget.chart_type })
    } catch { /* silent */ }
  }, [])

  const handleLayoutChange = useCallback((newLayouts: GridLayout[]) => {
    setWidgets((prev) => prev.map((w) => {
      const l = newLayouts.find((gl) => gl.i === w.id)
      return l ? { ...w, layout: l } : w
    }))
  }, [])

  const updateWidget = useCallback((updated: Widget) => {
    setWidgets((prev) => prev.map((w) => w.id === updated.id ? updated : w))
  }, [])

  async function handleExport() {
    if (!widgets.length) return
    setExporting(true)
    try { await exportPDF(tabLabel ?? 'My Dashboard', tabLabel ?? 'My Dashboard', widgets) }
    finally { setExporting(false) }
  }

  const hasContent = widgets.length > 0 || customKpis.length > 0

  return (
    <div className="flex flex-col gap-4 p-4">

      {/* ── KPI row + toolbar ───────────────────────────────────────────────── */}
      {hasContent && (
        <div className="flex items-center gap-3 flex-wrap">
          {customKpis.map((k) => (
            <KPICard key={k.id} label={k.label} value={k.value} onRemove={() => removeCustomKpi(k.id)} />
          ))}
          <div className="ml-auto flex items-center gap-2">
            {widgets.length > 0 && (
              <span className="text-xs text-gray-400 mr-1">
                {widgets.length} widget{widgets.length !== 1 ? 's' : ''} · {widgets.reduce((s, w) => s + w.data.length, 0).toLocaleString()} rows
              </span>
            )}
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
            <button
              onClick={handleExport}
              disabled={exporting || !widgets.length}
              className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              <Download size={15} />
              {exporting ? 'Exporting…' : 'Export PDF'}
            </button>
          </div>
        </div>
      )}

      {/* ── Widget grid ─────────────────────────────────────────────────────── */}
      <DashboardGrid
        widgets={widgets}
        onRemove={removeWidget}
        onSaveFavorite={saveFavorite}
        onLayoutChange={handleLayoutChange}
        onUpdate={updateWidget}
      />

      {/* Empty state */}
      {!hasContent && (
        <div className="flex flex-col items-center justify-center py-24 text-center text-gray-400 gap-3">
          <p className="text-sm font-medium">Your dashboard is empty</p>
          <p className="text-xs max-w-xs">Ask the AI Analyst below to create charts, tables, or KPI metrics — they'll appear here.</p>
        </div>
      )}
    </div>
  )
}
