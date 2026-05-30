import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { KPICard } from '../components/Header/KPICard'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { LoadingOverlay } from '../components/common/LoadingSpinner'
import { fetchVendorScorecard } from '../api/scorecard'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import type { Widget, GridLayout, ScorecardVendor, CustomKpi } from '../types'


const SEED_IDS = ['vendor_tier_breakdown', 'vendor_offshore', 'vendor_billtype_bar', 'vendor_table', 'vendor_spend_by_tier', 'vendor_monthly', 'vendor_cap_exp_ftp', 'vendor_resource_count']
const STORAGE_KEY = 'gd_ws_vendor'

function loadState(): { widgets: Widget[]; customKpis: CustomKpi[] } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : { widgets: [], customKpis: [] }
  } catch { return { widgets: [], customKpis: [] } }
}

function saveState(widgets: Widget[], customKpis: CustomKpi[]) {
  try {
    const toSave = widgets.map(w => SEED_IDS.includes(w.id) ? { ...w, data: [] } : w)
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ widgets: toSave, customKpis }))
  } catch { /* quota exceeded */ }
}

function sql(data: ScorecardVendor | null, key: string) {
  return data?._sql?.[key] ?? ''
}

function makeSeeds(data: ScorecardVendor | null, fetchError?: string): Widget[] {
  const e = (key: string) => fetchError ?? data?._errors?.[key]
  return [
    // ── Trend charts row ──
    {
      id: 'vendor_spend_by_tier', title: 'Spend by Tier',
      chart_type: 'line', x_axis: 'month', y_axis: ['Dollars'], color_field: 'Resource_Category',
      stacked: false, dual_axis: false,
      ai_description: 'Monthly spend trend broken down by resource tier (Tier 1–4).',
      sql: sql(data, 'spend_by_tier_monthly'), data: data?.spend_by_tier_monthly ?? [],
      error: e('spend_by_tier_monthly'),
      layout: { i: 'vendor_spend_by_tier', x: 0, y: 3, w: 4, h: 6 },
    },
    {
      id: 'vendor_monthly', title: 'Spend by Fixed Fee | TM',
      chart_type: 'stacked_bar', x_axis: 'month', y_axis: [], color_field: 'BillType',
      stacked: true, dual_axis: false,
      ai_description: 'Monthly spend trend split by TM and Fixed Fee billing models.',
      sql: sql(data, 'monthly_vendor_spend'), data: data?.monthly_vendor_spend ?? [],
      error: e('monthly_vendor_spend'),
      layout: { i: 'vendor_monthly', x: 4, y: 3, w: 4, h: 5 },
    },
    {
      id: 'vendor_cap_exp_ftp', title: 'Spend by Capital / Expense',
      chart_type: 'combo', x_axis: 'month', y_axis: ['Capital', 'Expense', 'FTP'], secondary_y: 'FTP',
      stacked: true, dual_axis: true,
      ai_description: 'Monthly stacked capital and expense spend with total FTP headcount overlay.',
      sql: sql(data, 'monthly_cap_exp_ftp'), data: data?.monthly_cap_exp_ftp ?? [],
      error: e('monthly_cap_exp_ftp'),
      layout: { i: 'vendor_cap_exp_ftp', x: 8, y: 3, w: 4, h: 5 },
    },
    // ── Resource count bar + billtype bar ──
    {
      id: 'vendor_resource_count', title: 'Resource Count by Vendor (excl. Internal)',
      chart_type: 'bar', x_axis: 'Vendor', y_axis: ['Resource_Count'],
      stacked: false, dual_axis: false,
      ai_description: 'Headcount per external vendor (top 15), showing which vendors contribute the most resources.',
      sql: sql(data, 'vendor_resource_count'), data: data?.vendor_resource_count ?? [],
      error: e('vendor_resource_count'),
      layout: { i: 'vendor_resource_count', x: 0, y: 9, w: 4, h: 6 },
    },
    {
      id: 'vendor_billtype_bar', title: 'Fixed Fee / TM Spend',
      chart_type: 'horizontal_bar', x_axis: 'BillType', y_axis: ['Spend'],
      stacked: false, dual_axis: false,
      ai_description: 'Spend breakdown between Time & Materials and Fixed Fee billing.',
      sql: sql(data, 'billtype_bar'), data: data?.billtype_bar ?? [],
      error: e('billtype_bar'),
      layout: { i: 'vendor_billtype_bar', x: 8, y: 9, w: 4, h: 6 },
    },
    // ── Left column — tier + offshore bars; Center/right — vendor table ──
    {
      id: 'vendor_offshore', title: 'Offshore / Onshore FTE',
      chart_type: 'horizontal_bar', x_axis: 'FOB', y_axis: ['FTE'],
      stacked: false, dual_axis: false,
      ai_description: 'FTE distribution between offshore and onshore locations.',
      sql: sql(data, 'offshore_onshore_bar'), data: data?.offshore_onshore_bar ?? [],
      error: e('offshore_onshore_bar'),
      layout: { i: 'vendor_offshore', x: 0, y: 16, w: 4, h: 5 },
    },
    {
      id: 'vendor_tier_breakdown', title: 'Tier Breakdown — Offshore / Fixed Fee / Capital',
      chart_type: 'table', x_axis: undefined, y_axis: [],
      stacked: false, dual_axis: false,
      ai_description: 'Per-tier summary of offshore %, fixed fee %, and capital % with headcount and spend.',
      sql: sql(data, 'tier_breakdown'), data: data?.tier_breakdown ?? [],
      error: e('tier_breakdown'),
      layout: { i: 'vendor_tier_breakdown', x: 0, y: 21, w: 4, h: 8 },
    },
    {
      id: 'vendor_table', title: 'Vendor Summary',
      chart_type: 'table', x_axis: undefined, y_axis: [],
      stacked: false, dual_axis: false,
      ai_description: 'Vendor breakdown including FTP, offshore/onshore ratio, TM %, fixed fee %, capital %, and committed spend.',
      sql: sql(data, 'vendor_table'), data: data?.vendor_table ?? [],
      error: e('vendor_table'),
      layout: { i: 'vendor_table', x: 4, y: 16, w: 8, h: 14 },
    },
  ]
}

interface Props { tabLabel?: string; onRegisterAddWidget?: (fn: (w: Widget) => void) => void }

export function VendorSummaryTab({ tabLabel, onRegisterAddWidget }: Props) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['scorecard', 'vendor'],
    queryFn: fetchVendorScorecard,
    staleTime: 5 * 60 * 1000,
  })

  const [widgets, setWidgets] = useState<Widget[]>(() => loadState().widgets)
  const [customKpis, setCustomKpis] = useState<CustomKpi[]>(() => loadState().customKpis)
  const [exporting, setExporting] = useState(false)

  useEffect(() => { saveState(widgets, customKpis) }, [widgets, customKpis])

  useEffect(() => {
    if (!isFetching) return
    setWidgets((prev) => prev.map(w => SEED_IDS.includes(w.id) ? { ...w, loading: true } : w))
  }, [isFetching])

  useEffect(() => {
    if (!data) return
    const seeds = makeSeeds(data)
    setWidgets((prev) => {
      const prevMap = new Map(prev.map(w => [w.id, w]))
      const mergedSeeds = seeds.map(s => {
        const p = prevMap.get(s.id)
        return p ? { ...s, layout: p.layout ?? s.layout, loading: false } : s
      })
      const userAdded = prev.filter((w) => !SEED_IDS.includes(w.id))
      return [...mergedSeeds, ...userAdded]
    })
  }, [data])

  useEffect(() => {
    if (!isError || isFetching) return
    setWidgets((prev) => {
      const seeds = makeSeeds(null, 'Failed to load data from server')
      const prevMap = new Map(prev.map(w => [w.id, w]))
      const merged = seeds.map(s => {
        const p = prevMap.get(s.id)
        return p ? { ...p, error: s.error, loading: false } : s
      })
      const userAdded = prev.filter(w => !SEED_IDS.includes(w.id))
      return [...merged, ...userAdded]
    })
  }, [isError, isFetching])

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
    try { await exportPDF(tabLabel ?? 'Vendor Summary Scorecard', tabLabel ?? 'Vendor Summary', widgets) }
    finally { setExporting(false) }
  }

  if ((isLoading || isFetching) && !widgets.length) return <LoadingOverlay label="Loading Vendor Summary…" />

  const kpi = data?.vendor_kpis?.[0] as Record<string, number> | undefined

  return (
    <div className="flex flex-col gap-4 p-4">
      {isError && !isFetching && (
        <div className="flex items-center gap-2.5 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
          <span className="font-semibold">Failed to load scorecard data.</span>
          <span className="text-red-500">Individual widget errors are shown below.</span>
          <button onClick={() => refetch()} className="ml-auto text-red-600 underline font-medium">Retry</button>
        </div>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        {kpi && (
          <>
            <KPICard label="Total Vendors" value={kpi.Total_Vendors} raw />
            <KPICard label="Total Resources" value={kpi.Total_Resources} raw />
            <KPICard label="Total Resources Cost" value={kpi.Total_Cost} />
          </>
        )}
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
