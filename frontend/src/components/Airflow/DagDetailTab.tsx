import { useState, useEffect } from 'react'
import { RefreshCw, Loader2 } from 'lucide-react'
import { fetchDagRuns, fetchDagTasks } from '../../api/airflow'
import type { AirflowRun, AirflowTask } from '../../types'
import RunHistory from './RunHistory'
import DagGraph from './DagGraph'

interface Props {
  dagId: string
  env: string
  onOpenSqlTab: (dagId: string, taskId: string, env: string, runId?: string, operatorFull?: string) => void
}

export default function DagDetailTab({ dagId, env, onOpenSqlTab }: Props) {
  const [runs, setRuns]             = useState<AirflowRun[]>([])
  const [tasks, setTasks]           = useState<AirflowTask[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [loading, setLoading]       = useState(true)
  const [tasksLoading, setTasksLoading] = useState(false)
  const [error, setError]           = useState<string | null>(null)

  async function load(runId?: string) {
    setLoading(true)
    setError(null)
    try {
      const [runsData, tasksData] = await Promise.all([
        fetchDagRuns(dagId, env, 5),
        fetchDagTasks(dagId, env, runId),
      ])
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
        <div>
          <h2 className="text-base font-semibold text-gray-800">{dagId}</h2>
          <span className="text-xs text-gray-400">{env} — last 5 runs</span>
        </div>
        <button
          onClick={() => load(selectedRunId ?? undefined)}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 px-3 py-1.5 rounded-lg"
        >
          <RefreshCw size={13} /> Refresh
        </button>
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
