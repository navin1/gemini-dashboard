import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Star, Trash2, Play, Loader2 } from 'lucide-react'
import { listFavorites, deleteFavorite, runFavorite } from '../api/favorites'
import { ChartRenderer } from '../components/Charts/ChartRenderer'
import { LoadingOverlay } from '../components/common/LoadingSpinner'
import type { ChartType } from '../types'

export function FavoritesTab() {
  const qc = useQueryClient()
  const [running, setRunning] = useState<number | null>(null)
  const [results, setResults] = useState<Record<number, { chart_type: ChartType; data: Record<string, unknown>[] }>>({})

  const { data: favorites, isLoading } = useQuery({ queryKey: ['favorites'], queryFn: listFavorites })

  const deleteMut = useMutation({
    mutationFn: deleteFavorite,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['favorites'] }),
  })

  async function run(id: number) {
    setRunning(id)
    try {
      const res = await runFavorite(id)
      setResults((prev) => ({ ...prev, [id]: { chart_type: (res.chart_type as ChartType) || 'table', data: res.data } }))
    } catch { /* silent */ }
    finally { setRunning(null) }
  }

  if (isLoading) return <LoadingOverlay label="Loading saved queries…" />

  const defaults = favorites?.filter((f) => f.is_default) ?? []
  const custom = favorites?.filter((f) => !f.is_default) ?? []

  function FavCard({ fav }: { fav: typeof defaults[0] }) {
    const result = results[fav.id]
    return (
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 bg-gray-50 border-b border-gray-200">
          <Star size={14} className={fav.is_default ? 'text-amber-400 fill-amber-400' : 'text-gray-400'} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-800 truncate">{fav.name}</p>
            {fav.nl_query && <p className="text-xs text-gray-500 truncate">{fav.nl_query}</p>}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => run(fav.id)}
              disabled={running === fav.id}
              className="flex items-center gap-1 text-xs bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-2.5 py-1.5 rounded-lg"
            >
              {running === fav.id ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Run
            </button>
            {!fav.is_default && (
              <button onClick={() => deleteMut.mutate(fav.id)} className="p-1.5 text-gray-400 hover:text-red-500 rounded">
                <Trash2 size={13} />
              </button>
            )}
          </div>
        </div>
        <div className="px-4 py-2">
          <code className="text-[10px] text-gray-500 break-all leading-relaxed">{fav.sql_query.slice(0, 200)}{fav.sql_query.length > 200 ? '…' : ''}</code>
        </div>
        {result && (
          <div className="border-t border-gray-100 px-4 py-3">
            <ChartRenderer chart_type={result.chart_type} data={result.data} y_axis={[]} height={220} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="p-4 flex flex-col gap-6">
      {defaults.length > 0 && (
        <section>
          <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">Default Queries</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {defaults.map((f) => <FavCard key={f.id} fav={f} />)}
          </div>
        </section>
      )}
      {custom.length > 0 && (
        <section>
          <h2 className="text-sm font-bold text-gray-700 uppercase tracking-wide mb-3">My Saved Queries</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {custom.map((f) => <FavCard key={f.id} fav={f} />)}
          </div>
        </section>
      )}
      {!defaults.length && !custom.length && (
        <div className="py-16 text-center text-gray-400">
          <Star size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No saved queries yet. Save a query from the My Dashboard tab.</p>
        </div>
      )}
    </div>
  )
}
