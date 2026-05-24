import { useCallback, useMemo, useRef, useState, useEffect, Component } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import GridLayout, { WidthProvider, Layout } from 'react-grid-layout'
import { Sparkles, AlertCircle, RotateCcw } from 'lucide-react'
import { Widget as WidgetComp } from './Widget'
import { listFavorites, createFavorite, deleteFavorite } from '../../api/favorites'
import type { Widget, GridLayout as GridPos, Favorite } from '../../types'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'

const UNDO_DELAY = 5000

const ResponsiveGrid = WidthProvider(GridLayout)

class WidgetErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div className="h-full flex flex-col items-start gap-2 bg-white border border-red-100 rounded-xl shadow-sm p-4">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} className="text-red-500 flex-shrink-0" />
            <p className="text-xs font-semibold text-red-700 uppercase tracking-wide">Render Error</p>
          </div>
          <p className="text-[11px] text-red-600 font-mono break-all leading-relaxed">{this.state.error.message}</p>
        </div>
      )
    }
    return this.props.children
  }
}

interface Props {
  widgets: Widget[]
  onRemove: (id: string) => void
  onSaveFavorite?: (widget: Widget) => void
  onLayoutChange?: (layouts: GridPos[]) => void
  onUpdate?: (widget: Widget) => void
}

function toLayouts(widgets: Widget[]): Layout[] {
  return widgets.map((w, i) => ({
    i: w.id,
    x: w.layout?.x ?? (i * 6) % 12,
    y: w.layout?.y ?? Math.floor(i / 2) * 10,
    w: w.layout?.w ?? 6,
    h: w.layout?.h ?? 10,
    minW: 2,
    minH: w.layout?.minH ?? 3,
  }))
}

export function DashboardGrid({ widgets, onRemove, onLayoutChange, onUpdate }: Props) {
  const queryClient = useQueryClient()

  // ── Undo-removal buffer ───────────────────────────────────────────────────
  const [pendingRemoval, setPendingRemoval] = useState<Widget | null>(null)
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function clearPendingTimer() {
    if (undoTimerRef.current) { clearTimeout(undoTimerRef.current); undoTimerRef.current = null }
  }

  const finalize = useCallback((id: string) => {
    onRemove(id)
    setPendingRemoval(null)
    undoTimerRef.current = null
  }, [onRemove])

  const handleRemove = useCallback((id: string) => {
    const widget = widgets.find(w => w.id === id)
    if (!widget) return
    // Finalize any previous pending removal before starting a new one
    if (pendingRemoval) { clearPendingTimer(); onRemove(pendingRemoval.id) }
    setPendingRemoval(widget)
    undoTimerRef.current = setTimeout(() => finalize(id), UNDO_DELAY)
  }, [widgets, pendingRemoval, onRemove, finalize])

  function handleUndo() {
    clearPendingTimer()
    setPendingRemoval(null)
  }

  // Clean up timer on unmount
  useEffect(() => () => clearPendingTimer(), [])

  const visibleWidgets = pendingRemoval
    ? widgets.filter(w => w.id !== pendingRemoval.id)
    : widgets

  const layouts = toLayouts(visibleWidgets)

  // Track in-flight widget IDs to block duplicate clicks and show spinner
  const inFlight = useRef<Set<string>>(new Set())
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set())

  const { data: favorites = [] } = useQuery({
    queryKey: ['favorites'],
    queryFn: listFavorites,
    staleTime: 5 * 60 * 1000,
  })

  const favBySql = useMemo(() => {
    const m = new Map<string, number>()
    favorites.forEach((f) => { if (f.sql_query) m.set(f.sql_query, f.id) })
    return m
  }, [favorites])

  const toggleFavorite = useCallback(async (widget: Widget) => {
    const sql = widget.sql ?? ''
    if (!sql || inFlight.current.has(widget.id)) return

    inFlight.current.add(widget.id)
    setPendingIds((prev) => new Set(prev).add(widget.id))

    const existingId = favBySql.get(sql)
    const previous = queryClient.getQueryData<Favorite[]>(['favorites']) ?? []

    // Optimistic update — change the cache immediately so the star flips instantly
    if (existingId != null) {
      queryClient.setQueryData<Favorite[]>(
        ['favorites'],
        previous.filter((f) => f.id !== existingId)
      )
    } else {
      const optimistic: Favorite = {
        id: -Date.now(),       // temporary id (negative so it won't clash)
        name: widget.title,
        nl_query: widget.nl_query,
        sql_query: sql,
        chart_type: widget.chart_type,
        is_default: false,
      }
      queryClient.setQueryData<Favorite[]>(['favorites'], [...previous, optimistic])
    }

    try {
      if (existingId != null) {
        await deleteFavorite(existingId)
      } else {
        await createFavorite({
          name: widget.title,
          nl_query: widget.nl_query,
          sql_query: sql,
          chart_type: widget.chart_type,
        })
      }
      // Sync with server to replace optimistic entry with real one
      queryClient.invalidateQueries({ queryKey: ['favorites'] })
    } catch {
      // Roll back optimistic change on error
      queryClient.setQueryData(['favorites'], previous)
    } finally {
      inFlight.current.delete(widget.id)
      setPendingIds((prev) => { const s = new Set(prev); s.delete(widget.id); return s })
    }
  }, [favBySql, queryClient])

  const handleLayoutChange = useCallback(
    (newLayouts: Layout[]) => {
      onLayoutChange?.(newLayouts.map((l) => ({ i: l.i, x: l.x, y: l.y, w: l.w, h: l.h })))
    },
    [onLayoutChange]
  )

  if (!visibleWidgets.length && !pendingRemoval) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-gray-400 gap-4">
        <div className="h-14 w-14 rounded-full bg-blue-50 border border-blue-100 flex items-center justify-center">
          <Sparkles size={22} className="text-blue-400" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-gray-500">Add your custom data/chart(s) here</p>
          <p className="text-xs text-gray-400 mt-1">Use the AI chat panel at the bottom to generate data/chart(s)</p>
        </div>
      </div>
    )
  }

  return (
    <>
      {visibleWidgets.length > 0 && (
        <ResponsiveGrid
          className="layout"
          layout={layouts}
          cols={12}
          rowHeight={48}
          onLayoutChange={handleLayoutChange}
          draggableHandle=".drag-handle"
          resizeHandles={['se', 's', 'e']}
          margin={[14, 14]}
        >
          {visibleWidgets.map((w) => (
            <div key={w.id}>
              <WidgetErrorBoundary>
                <WidgetComp
                  widget={w}
                  onRemove={handleRemove}
                  isFavorited={!!(w.sql && favBySql.has(w.sql))}
                  isFavoritePending={pendingIds.has(w.id)}
                  onFavoriteToggle={() => toggleFavorite(w)}
                  onUpdate={onUpdate}
                />
              </WidgetErrorBoundary>
            </div>
          ))}
        </ResponsiveGrid>
      )}

      {pendingRemoval && createPortal(
        <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-3 bg-gray-900 text-white text-sm px-4 py-2.5 rounded-xl shadow-2xl animate-in fade-in slide-in-from-bottom-2 duration-200">
          <span className="truncate max-w-[200px] text-gray-300">
            <span className="text-white font-medium">"{pendingRemoval.title}"</span> removed
          </span>
          <button
            onClick={handleUndo}
            className="flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 font-semibold transition-colors flex-shrink-0"
          >
            <RotateCcw size={13} />
            Undo
          </button>
        </div>,
        document.body
      )}
    </>
  )
}
