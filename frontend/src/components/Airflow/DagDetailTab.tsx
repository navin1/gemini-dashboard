import { useState, useEffect, useRef } from 'react'
import { RefreshCw, Loader2, Play, PauseCircle, Clock } from 'lucide-react'
import { fetchDagMeta, fetchDagRuns, fetchDagTasks, triggerDagRun, fetchRunState } from '../../api/airflow'
import type { AirflowRun, AirflowTask } from '../../types'
import type { DagMeta } from '../../api/airflow'
import RunHistory from './RunHistory'
import DagGraph from './DagGraph'

interface Props {
  dagId: string
  env: string
  onOpenSqlTab: (dagId: string, taskId: string, env: string, runId?: string, operatorFull?: string) => void
}

export default function DagDetailTab({ dagId, env, onOpenSqlTab }: Props) {
  const [meta, setMeta]                   = useState<DagMeta | null>(null)
  const [runs, setRuns]                   = useState<AirflowRun[]>([])
  const [tasks, setTasks]                 = useState<AirflowTask[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [loading, setLoading]             = useState(true)
  const [tasksLoading, setTasksLoading]   = useState(false)
  const [error, setError]                 = useState<string | null>(null)
  const [triggering, setTriggering]       = useState(false)
  const [triggerMsg, setTriggerMsg]       = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load(runId?: string) {
    setLoading(true)
    setError(null)
    try {
      // Mirrors Chrome extension's loadDag(): fetchDagMeta + fetchDagTasks in parallel
      const [metaData, runsData, tasksData] = await Promise.all([
        fetchDagMeta(dagId, env),
        fetchDagRuns(dagId, env, 5),
        fetchDagTasks(dagId, env, runId),
      ])
      setMeta(metaData)
      setRuns(runsData.runs)
      setTasks(tasksData.tasks)
      const effectiveRun = runId ?? tasksData.run_id ?? runsData.runs[0]?.run_id ?? null
      setSelectedRunId(effectiveRun)
    } catch (e: unknown) {
      setError((e as Error).message ?? 'Failed to load DAG data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [dagId, env])

  // Stop polling on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  async function handleSelectRun(runId: string) {
    setSelectedRunId(runId)
    setSelectedTaskId(null)
    setTasksLoading(true)
    try {
      const tasksData = await fetchDagTasks(dagId, env, runId)
      setTasks(tasksData.tasks)
    } catch { /* non-fatal */ }
    finally { setTasksLoading(false) }
  }

  function handleTaskClick(taskId: string, operatorFull: string) {
    setSelectedTaskId(taskId)
    onOpenSqlTab(dagId, taskId, env, selectedRunId ?? undefined, operatorFull)
  }

  async function handleTrigger() {
    setTriggering(true)
    setTriggerMsg(null)
    try {
      const { run_id } = await triggerDagRun(dagId, env)
      setTriggerMsg(`Run triggered: ${run_id}`)
      // Poll state every 5s until terminal
      pollRef.current = setInterval(async () => {
        try {
          const state = await fetchRunState(dagId, run_id, env)
          setTriggerMsg(`Run ${run_id}: ${state}`)
          if (['success', 'failed', 'upstream_failed'].includes(state)) {
            clearInterval(pollRef.current!)
            pollRef.current = null
            load()
          }
        } catch { /* non-fatal */ }
      }, 5000)
    } catch (e: unknown) {
      setTriggerMsg(`Trigger failed: ${(e as Error).message}`)
    } finally {
      setTriggering(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-full gap-2 text-gray-400">
      <Loader2 size={18} className="animate-spin" />
      <span className="text-sm">Loading DAG data…</span>
    </div>
  )

  if (error) return (
    <div className="flex flex-col items-center justify-center h-full gap-3 p-8 text-center">
      <span className="text-red-500 text-sm font-medium">{error}</span>
      <button onClick={() => load()} className="text-xs text-brand-600 underline">Retry</button>
    </div>
  )

  return (
    <div className="flex flex-col h-full gap-4 p-4 min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-gray-800">{dagId}</h2>
            {meta?.is_paused && (
              <span className="flex items-center gap-1 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full">
                <PauseCircle size={10} /> Paused
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-400">
            <span>{env} — last 5 runs</span>
            {meta?.schedule_interval && (
              <span className="flex items-center gap-1">
                <Clock size={10} /> {meta.schedule_interval}
              </span>
            )}
            {meta?.last_run_state && (
              <span className={`font-medium ${meta.last_run_state === 'success' ? 'text-emerald-600' : meta.last_run_state === 'failed' ? 'text-red-500' : 'text-gray-500'}`}>
                last: {meta.last_run_state}
              </span>
            )}
          </div>
          {triggerMsg && (
            <span className="text-xs text-brand-600 mt-0.5">{triggerMsg}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="flex items-center gap-1.5 text-sm text-white bg-brand-600 hover:bg-brand-700 disabled:opacity-50 px-3 py-1.5 rounded-lg"
          >
            {triggering ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            Trigger
          </button>
          <button
            onClick={() => load(selectedRunId ?? undefined)}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1.5 rounded-lg"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* Run history */}
      <div className="flex-shrink-0">
        <RunHistory runs={runs} selectedRunId={selectedRunId} onSelectRun={handleSelectRun} />
      </div>

      {/* DAG graph */}
      <div className="flex-1 min-h-0 rounded-xl border border-gray-200 overflow-hidden bg-slate-50 relative" style={{ minHeight: 360 }}>
        {tasksLoading && (
          <div className="absolute inset-0 bg-white/70 flex items-center justify-center z-10">
            <Loader2 size={20} className="animate-spin text-brand-500" />
          </div>
        )}
        <DagGraph tasks={tasks} onTaskClick={handleTaskClick} selectedTaskId={selectedTaskId} />
      </div>

      <p className="text-xs text-gray-400 flex-shrink-0">Click a task node to open its SQL in a new tab.</p>
    </div>
  )
}
