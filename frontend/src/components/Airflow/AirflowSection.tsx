import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronUp, ChevronDown, ChevronsUpDown, Loader2 } from 'lucide-react'
import { fetchDagsStatus } from '../../api/airflow'
import { fetchStreamConfig } from '../../api/stream'
import { useTabTheme } from '../../context/TabThemeContext'
import type { LiveStatus } from '../../hooks/useLiveStream'
import type { DagStatus } from '../../types'

type SortKey = 'dag_id' | 'state' | 'last_run_time'
type SortDir = 'asc' | 'desc'

const STATE_BADGE: Record<string, { bg: string; text: string; label: string }> = {
  success:         { bg: 'bg-emerald-50',  text: 'text-emerald-700',  label: '✓ success' },
  failed:          { bg: 'bg-red-50',      text: 'text-red-700',      label: '✗ failed' },
  running:         { bg: 'bg-blue-50',     text: 'text-blue-700',     label: '↻ running' },
  queued:          { bg: 'bg-amber-50',    text: 'text-amber-700',    label: '◎ queued' },
  up_for_retry:    { bg: 'bg-orange-50',   text: 'text-orange-700',   label: '↺ up for retry' },
  skipped:         { bg: 'bg-gray-50',     text: 'text-gray-500',     label: '⇥ skipped' },
  upstream_failed: { bg: 'bg-red-50',      text: 'text-red-600',      label: '✗ upstream failed' },
  error:           { bg: 'bg-red-50',      text: 'text-red-500',      label: '! error' },
}

function StateBadge({ state }: { state: string | null }) {
  if (!state) return <span className="text-gray-400 text-xs">—</span>
  const cfg = STATE_BADGE[state]
  if (!cfg) return <span className="text-xs text-gray-500">{state}</span>
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${cfg.bg} ${cfg.text}`}>
      {cfg.label}
    </span>
  )
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const ms = Date.now() - d.getTime()
    const mins  = Math.floor(ms / 60_000)
    const hours = Math.floor(mins / 60)
    const days  = Math.floor(hours / 24)
    const abs = d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    const rel = days > 0 ? `${days}d ago` : hours > 0 ? `${hours}h ago` : mins > 0 ? `${mins}m ago` : 'just now'
    return `${abs} (${rel})`
  } catch { return iso }
}

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (col !== sortKey) return <ChevronsUpDown size={12} className="text-gray-300" />
  return sortDir === 'asc' ? <ChevronUp size={12} className="text-brand-500" /> : <ChevronDown size={12} className="text-brand-500" />
}

interface Props {
  live: boolean
  onLiveStatusChange: (status: LiveStatus) => void
  onRegisterRefresh: (fn: () => void) => void
  airflowEnvOverride?: string
}

export default function AirflowSection({ live, onLiveStatusChange, onRegisterRefresh, airflowEnvOverride }: Props) {
  const { airflowEnv: ctxAirflowEnv, onOpenDagTab } = useTabTheme()
  const airflowEnv = airflowEnvOverride ?? ctxAirflowEnv
  const [dags, setDags]             = useState<DagStatus[]>([])
  const [fetching, setFetching]     = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const [liveStatus, setLiveStatus] = useState<LiveStatus>('off')
  const [sortKey, setSortKey]       = useState<SortKey>('dag_id')
  const [sortDir, setSortDir]       = useState<SortDir>('asc')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Ref so async callbacks always see current live value without stale closure
  const liveRef = useRef(live)
  liveRef.current = live

  const { data: streamConfig } = useQuery({
    queryKey: ['stream', 'config'],
    queryFn: fetchStreamConfig,
    staleTime: Infinity,
  })
  const pollMs = (streamConfig?.poll_interval_seconds ?? 60) * 1000

  const loadStatus = useCallback(async (env: string) => {
    setFetching(true)
    setFetchError(null)
    try {
      const { dags: fresh } = await fetchDagsStatus(env)
      setDags(fresh)
      if (liveRef.current) setLiveStatus('live')
    } catch (e: unknown) {
      setFetchError((e as Error).message ?? 'Failed to fetch DAG status')
      if (liveRef.current) setLiveStatus('error')
    } finally {
      setFetching(false)
    }
  }, []) // stable — reads liveRef for current value

  // Report liveStatus changes up to Widget header
  useEffect(() => {
    onLiveStatusChange(liveStatus)
  }, [liveStatus, onLiveStatusChange])

  // Register refresh function with Widget
  useEffect(() => {
    onRegisterRefresh(() => { if (airflowEnv) loadStatus(airflowEnv) })
  }, [airflowEnv, loadStatus, onRegisterRefresh])

  // Initial load and env change
  useEffect(() => {
    if (!airflowEnv) return
    loadStatus(airflowEnv)
  }, [airflowEnv]) // eslint-disable-line react-hooks/exhaustive-deps

  // Live polling — responds to controlled `live` prop
  useEffect(() => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null }
    if (!live || !airflowEnv) { setLiveStatus('off'); return }

    setLiveStatus('connecting')
    loadStatus(airflowEnv)

    intervalRef.current = setInterval(() => {
      if (airflowEnv) loadStatus(airflowEnv)
    }, pollMs)

    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [live, airflowEnv]) // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const sorted = [...dags].sort((a, b) => {
    let av = '', bv = ''
    if (sortKey === 'dag_id')        { av = a.dag_id;              bv = b.dag_id }
    if (sortKey === 'state')         { av = a.state ?? '';          bv = b.state ?? '' }
    if (sortKey === 'last_run_time') { av = a.last_run_time ?? '';  bv = b.last_run_time ?? '' }
    return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
  })

  const thClass = 'px-3 py-2 text-left text-xs font-semibold text-gray-600 cursor-pointer select-none hover:bg-gray-100 whitespace-nowrap'

  return (
    <div className="flex flex-col gap-1 h-full">
      {/* Inline status — only visible when loading or errored */}
      {(fetching || fetchError) && (
        <div className="flex items-center gap-2 mb-1">
          {fetching && <Loader2 size={13} className="animate-spin text-gray-400" />}
          {fetchError && <span className="text-xs text-red-500">{fetchError}</span>}
        </div>
      )}

      {/* Table */}
      <div className="overflow-auto flex-1 rounded border border-gray-200">
        {!airflowEnv && (
          <div className="text-xs text-gray-400 py-6 text-center">No Airflow environment configured for this tab.</div>
        )}
        {airflowEnv && dags.length === 0 && !fetching && !fetchError && (
          <div className="text-xs text-gray-400 py-6 text-center">No DAGs configured. Add DAG IDs to AIRFLOW_DAGS in .env</div>
        )}
        {airflowEnv && (dags.length > 0 || fetching) && (
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className={thClass} onClick={() => toggleSort('dag_id')}>
                  <span className="flex items-center gap-1">DAG Name <SortIcon col="dag_id" sortKey={sortKey} sortDir={sortDir} /></span>
                </th>
                <th className={thClass} onClick={() => toggleSort('state')}>
                  <span className="flex items-center gap-1">Last Run Status <SortIcon col="state" sortKey={sortKey} sortDir={sortDir} /></span>
                </th>
                <th className={thClass} onClick={() => toggleSort('last_run_time')}>
                  <span className="flex items-center gap-1">Last Run Time <SortIcon col="last_run_time" sortKey={sortKey} sortDir={sortDir} /></span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((dag, i) => (
                <tr key={dag.dag_id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="px-3 py-2 text-gray-700">
                    <button
                      onClick={() => onOpenDagTab(dag.dag_id, airflowEnv)}
                      className="text-gray-700 underline hover:text-gray-900 text-xs text-left"
                    >
                      {dag.dag_id}
                    </button>
                  </td>
                  <td className="px-3 py-2"><StateBadge state={dag.state} /></td>
                  <td className="px-3 py-2 text-gray-700">{formatTime(dag.last_run_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
