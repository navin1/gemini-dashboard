import { useState, useCallback, useEffect } from 'react'
import { Download } from 'lucide-react'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { KPICard } from '../components/Header/KPICard'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import type { Widget, GridLayout, CustomKpi } from '../types'

let _id = 0
function nextId() { return `w_${++_id}_${Date.now()}` }

const DEFAULT_LAYOUT: GridLayout = { i: '', x: 0, y: 0, w: 6, h: 10 }

interface Props {
  tabLabel?: string
  onRegisterAddWidget?: (fn: (widget: Widget) => void) => void
}

export function AIDashboardTab({ tabLabel, onRegisterAddWidget }: Props) {
  const [widgets,    setWidgets]    = useState<Widget[]>([])
  const [customKpis, setCustomKpis] = useState<CustomKpi[]>([])
  const [exporting,  setExporting]  = useState(false)

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

      {/* ── KPI row + export bar ─────────────────────────────────────────── */}
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

      {/* ── Chart / table widget grid ────────────────────────────────────── */}
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
