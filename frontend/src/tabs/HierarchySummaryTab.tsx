import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { KPICard } from '../components/Header/KPICard'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { LoadingOverlay } from '../components/common/LoadingSpinner'
import { fetchHierarchyScorecard } from '../api/scorecard'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import type { Widget, GridLayout, ScorecardHierarchy, CustomKpi } from '../types'


const SEED_IDS = ['hier_tier_breakdown', 'hier_drill', 'hier_cat_monthly', 'hier_billtype_monthly']

function sql(data: ScorecardHierarchy, key: string) {
  return data._sql?.[key] ?? ''
}

function makeSeeds(data: ScorecardHierarchy): Widget[] {
  return [
    // Left column — tier breakdown metrics
    {
      id: 'hier_tier_breakdown', title: 'Tier Breakdown — Offshore / Fixed Fee / Capital',
      chart_type: 'table', x_axis: undefined, y_axis: [],
      stacked: false, dual_axis: false,
      ai_description: 'Per-tier summary of offshore %, fixed fee %, and capital % with headcount and spend.',
      sql: sql(data, 'tier_breakdown'), data: data.tier_breakdown,
      layout: { i: 'hier_tier_breakdown', x: 0, y: 10, w: 3, h: 8 },
    },
    // Center — hierarchy drill-down table
    {
      id: 'hier_drill', title: 'Hierarchy Drill-Down',
      chart_type: 'table', x_axis: undefined, y_axis: [],
      stacked: false, dual_axis: false,
      ai_description: 'Hierarchy breakdown by VP, vendor, and manager with spend, offshore %, TM %, capital % and expense %.',
      sql: sql(data, 'hierarchy_drill'), data: data.hierarchy_drill,
      layout: { i: 'hier_drill', x: 3, y: 10, w: 9, h: 14 },
    },
    // Bottom row
    {
      id: 'hier_cat_monthly', title: 'Spend by Tier',
      chart_type: 'line', x_axis: 'month', y_axis: ['Dollars'], color_field: 'Resource_Category',
      stacked: false, dual_axis: false,
      ai_description: 'Monthly spend trend broken down by resource tier.',
      sql: sql(data, 'spend_by_tier_monthly'), data: data.spend_by_tier_monthly,
      layout: { i: 'hier_cat_monthly', x: 0, y: 0, w: 4, h: 6 },
    },
    {
      id: 'hier_billtype_monthly', title: 'Spend by Fixed Fee | TM',
      chart_type: 'stacked_bar', x_axis: 'month', y_axis: [], color_field: 'BillType',
      stacked: true, dual_axis: false,
      ai_description: 'Monthly spend trend split by TM and Fixed Fee billing type.',
      sql: sql(data, 'monthly_vendor_spend'), data: data.billtype_monthly,
      layout: { i: 'hier_billtype_monthly', x: 4, y: 0, w: 4, h: 6 },
    },
  ]
}

interface Props { tabLabel?: string; onRegisterAddWidget?: (fn: (w: Widget) => void) => void }

export function HierarchySummaryTab({ tabLabel, onRegisterAddWidget }: Props) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['scorecard', 'hierarchy'],
    queryFn: fetchHierarchyScorecard,
    staleTime: 5 * 60 * 1000,
  })

  const [widgets, setWidgets] = useState<Widget[]>([])
  const [customKpis, setCustomKpis] = useState<CustomKpi[]>([])
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (!data) return
    const seeds = makeSeeds(data)
    setWidgets((prev) => {
      const userAdded = prev.filter((w) => !SEED_IDS.includes(w.id))
      return [...seeds, ...userAdded]
    })
  }, [data])

  const addExternalWidget = useCallback((w: Widget) => {
    if (w.chart_type === 'kpi') {
      const items: CustomKpi[] = Object.entries(w.data[0] ?? {})
        .filter(([, v]) => typeof v === 'number')
        .map(([k, v]) => ({ id: `${w.id}_${k}`, label: k.replace(/_/g, ' '), value: v as number }))
      setCustomKpis((prev) => {
        const newItems = items.filter((item) => !prev.some((p) => p.id === item.id))
        return [...prev, ...newItems]
      })
      return
    }
    setWidgets((prev) => prev.some((x) => x.id === w.id) ? prev : [...prev, w])
  }, [])
  useEffect(() => { onRegisterAddWidget?.(addExternalWidget) }, [onRegisterAddWidget, addExternalWidget])

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
    try { await exportPDF(tabLabel ?? 'Hierarchy Summary Scorecard', tabLabel ?? 'Hierarchy Summary', widgets) }
    finally { setExporting(false) }
  }

  if (isLoading) return <LoadingOverlay label="Loading Hierarchy Summary…" />
  if (isError) return (
    <div className="p-8 text-center">
      <p className="text-red-600 font-medium mb-3">Failed to load hierarchy data</p>
      <button onClick={() => refetch()} className="text-sm text-brand-600 underline">Retry</button>
    </div>
  )

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3 flex-wrap">
        {customKpis.map((k) => (
          <KPICard key={k.id} label={k.label} value={k.value} onRemove={() => removeCustomKpi(k.id)} />
        ))}
        <div className="ml-auto flex gap-2">
          <button onClick={() => refetch()} disabled={isFetching} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-2 rounded-lg">
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={handleExport} disabled={exporting} className="flex items-center gap-1.5 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-lg">
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export PDF'}
          </button>
        </div>
      </div>

      <div className="overflow-auto">
        <DashboardGrid widgets={widgets} onRemove={removeWidget} onSaveFavorite={saveFavorite} onLayoutChange={handleLayoutChange} onUpdate={updateWidget} />
      </div>
    </div>
  )
}
