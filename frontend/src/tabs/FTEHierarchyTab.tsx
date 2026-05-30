import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { KPICard } from '../components/Header/KPICard'
import { DashboardGrid } from '../components/Dashboard/DashboardGrid'
import { LoadingOverlay } from '../components/common/LoadingSpinner'
import { fetchFTEScorecard } from '../api/scorecard'
import { createFavorite } from '../api/favorites'
import { exportPDF } from '../api/pdf'
import type { Widget, GridLayout, KPIData, ScorecardFTE, CustomKpi } from '../types'


const SEED_IDS = ['fte_spend_class', 'fte_capital_combo', 'fte_expense_combo', 'fte_table', 'fte_donut', 'fte_cap_exp_ftp']
const STORAGE_KEY = 'gd_ws_fte'

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

function sql(data: ScorecardFTE | null, key: string, suffix = '') {
  const q = data?._sql?.[key] ?? ''
  return suffix ? `${q}\n-- ${suffix}` : q
}

function makeSeeds(data: ScorecardFTE | null, fetchError?: string): Widget[] {
  const e = (key: string) => fetchError ?? data?._errors?.[key]
  return [
    // Left column — 3 stacked charts (w=4)
    {
      id: 'fte_spend_class', title: 'Spend by Capital / Expense',
      chart_type: 'stacked_bar', x_axis: 'month', y_axis: [], color_field: 'Project_Class',
      stacked: true, dual_axis: false,
      ai_description: 'Monthly capital vs expense spend trend across all 12 months.',
      sql: sql(data, 'monthly_capital_expense'), data: data?.monthly_capital_expense ?? [],
      error: e('monthly_capital_expense'),
      layout: { i: 'fte_spend_class', x: 0, y: 0, w: 4, h: 5 },
    },
    {
      id: 'fte_capital_combo', title: 'Capital Spend vs FTE',
      chart_type: 'combo', x_axis: 'month', y_axis: ['Capital', 'FTP'], secondary_y: 'FTP',
      stacked: false, dual_axis: true,
      ai_description: 'Monthly capital spend (bars) overlaid with total FTE headcount (line).',
      sql: sql(data, 'monthly_cap_exp_ftp', 'fte_capital_combo'), data: data?.monthly_cap_exp_ftp ?? [],
      error: e('monthly_cap_exp_ftp'),
      layout: { i: 'fte_capital_combo', x: 0, y: 8, w: 4, h: 5 },
    },
    {
      id: 'fte_expense_combo', title: 'Expense Spend vs FTE',
      chart_type: 'combo', x_axis: 'month', y_axis: ['Expense', 'FTP'], secondary_y: 'FTP',
      stacked: false, dual_axis: true,
      ai_description: 'Monthly expense spend (bars) overlaid with total FTE headcount (line).',
      sql: sql(data, 'monthly_cap_exp_ftp', 'fte_expense_combo'), data: data?.monthly_cap_exp_ftp ?? [],
      error: e('monthly_cap_exp_ftp'),
      layout: { i: 'fte_expense_combo', x: 0, y: 16, w: 4, h: 5 },
    },
    // Center — hierarchy table (tall, spans full left-column height)
    {
      id: 'fte_table', title: 'FTE Hierarchy Summary',
      chart_type: 'table', x_axis: undefined, y_axis: [],
      stacked: false, dual_axis: false,
      ai_description: 'Hierarchy breakdown of headcount, FTE, capital %, and spend by resource VP and manager.',
      sql: sql(data, 'hierarchy_table'), data: data?.hierarchy_table ?? [],
      error: e('hierarchy_table'),
      layout: { i: 'fte_table', x: 4, y: 0, w: 8, h: 15 },
    },
    // Bottom row
    {
      id: 'fte_donut', title: 'Capital vs Expense $ YTD',
      chart_type: 'donut', x_axis: 'type', y_axis: ['amount'],
      stacked: false, dual_axis: false,
      ai_description: 'Year-to-date split between capital and expense spend.',
      sql: sql(data, 'capital_expense_donut'), data: data?.capital_expense_donut ?? [],
      error: e('capital_expense_donut'),
      layout: { i: 'fte_donut', x: 4, y: 24, w: 4, h: 5 },
    },
    {
      id: 'fte_cap_exp_ftp', title: 'Spend by Capital / Expense (with FTP)',
      chart_type: 'combo', x_axis: 'month', y_axis: ['Capital', 'Expense', 'FTP'], secondary_y: 'FTP',
      stacked: true, dual_axis: true,
      ai_description: 'Monthly stacked capital and expense spend with FTE headcount overlay.',
      sql: sql(data, 'monthly_cap_exp_ftp', 'fte_cap_exp_ftp'), data: data?.monthly_cap_exp_ftp ?? [],
      error: e('monthly_cap_exp_ftp'),
      layout: { i: 'fte_cap_exp_ftp', x: 0, y: 24, w: 4, h: 5 },
    },
  ]
}

interface Props { tabLabel?: string; onRegisterAddWidget?: (fn: (w: Widget) => void) => void }

export function FTEHierarchyTab({ tabLabel, onRegisterAddWidget }: Props) {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['scorecard', 'fte'],
    queryFn: fetchFTEScorecard,
    staleTime: 5 * 60 * 1000,
  })

  const [widgets, setWidgets] = useState<Widget[]>(() => loadState().widgets)
  const [customKpis, setCustomKpis] = useState<CustomKpi[]>(() => loadState().customKpis)
  const [exporting, setExporting] = useState(false)

  useEffect(() => { saveState(widgets, customKpis) }, [widgets, customKpis])

  // Mark seed widgets as loading while fetch is in flight
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
    try { await exportPDF(tabLabel ?? 'FTE Hierarchy Scorecard', tabLabel ?? 'FTE Hierarchy', widgets) }
    finally { setExporting(false) }
  }

  const kpi = data?.kpi?.[0] as KPIData | undefined

  if ((isLoading || isFetching) && !widgets.length) return <LoadingOverlay label="Loading FTE Hierarchy Scorecard…" />

  return (
    <div className="flex flex-col gap-4 p-4">
      {isError && !isFetching && (
        <div className="flex items-center gap-2.5 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
          <span className="font-semibold">Failed to load scorecard data.</span>
          <span className="text-red-500">Individual widget errors are shown below.</span>
          <button onClick={() => refetch()} className="ml-auto text-red-600 underline font-medium">Retry</button>
        </div>
      )}
      {(kpi || customKpis.length > 0) && (
        <div className="flex items-center gap-3 flex-wrap">
          {kpi && <>
            <KPICard label="Spend to Date" value={kpi.spend_to_date} />
            <KPICard label="Commit Spend" value={kpi.commit_spend} />
            <KPICard label="% Spend" value={kpi.pct_spend} pct />
          </>}
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
      )}

      <div className="overflow-auto">
        <DashboardGrid widgets={widgets} onRemove={removeWidget} onSaveFavorite={saveFavorite} onLayoutChange={handleLayoutChange} onUpdate={updateWidget} />
      </div>
    </div>
  )
}
