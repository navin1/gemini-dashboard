import { useState, useEffect, useRef, useCallback } from 'react'
import { RefreshCw, Loader2, Play, PauseCircle, Clock } from 'lucide-react'
import { fetchDagMeta, fetchDagRuns, fetchDagTasks, fetchDagCode, triggerDagRun, fetchRunState } from '../../api/airflow'
import type { AirflowRun, AirflowTask } from '../../types'
import type { DagMeta } from '../../api/airflow'
import RunHistory from './RunHistory'
import DagGraph from './DagGraph'
import DagCodeViewer from './DagCodeViewer'

interface Props {
  dagId: string
  env: string
  onOpenSqlTab: (dagId: string, taskId: string, env: string, runId?: string, operatorFull?: string) => void
  onSendToAgent?: (code: string) => void
}

const MIN_LEFT_PCT  = 20
const MAX_LEFT_PCT  = 70
const DEFAULT_LEFT_PCT = 40

export default function DagDetailTab({ dagId, env, onOpenSqlTab, onSendToAgent }: Props) {
  const [meta, setMeta]                     = useState<DagMeta | null>(null)
  const [runs, setRuns]                     = useState<AirflowRun[]>([])
  const [tasks, setTasks]                   = useState<AirflowTask[]>([])
  const [selectedRunId, setSelectedRunId]   = useState<string | null>(null)
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [loading, setLoading]               = useState(true)
  const [tasksLoading, setTasksLoading]     = useState(false)
  const [error, setError]                   = useState<string | null>(null)
  const [triggering, setTriggering]         = useState(false)
  const [triggerMsg, setTriggerMsg]         = useState<string | null>(null)
  const [code, setCode]                     = useState('')
  const [codeLoading, setCodeLoading]       = useState(true)
  const [codeError, setCodeError]           = useState<string | null>(null)

  // Split pane state
  const [leftPct, setLeftPct] = useState(DEFAULT_LEFT_PCT)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const isDragging = useRef(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load(runId?: string) {
    setLoading(true)
    setError(null)
    try {
      const [metaData, runsData] = await Promise.all([
        fetchDagMeta(dagId, env),
        fetchDagRuns(dagId, env, 5),
      ])
      setMeta(metaData)
      setRuns(runsData.runs)
      const effectiveRun = runId ?? metaData.last_run_id ?? runsData.runs[0]?.run_id ?? null
      setSelectedRunId(effectiveRun)
      if (effectiveRun) {
        const tasksData = await fetchDagTasks(dagId, env, effectiveRun)
        setTasks(tasksData.tasks)
      }
    } catch (e: unknown) {
      setError((e as Error).message ?? 'Failed to load DAG data')
    } finally {
      setLoading(false)
    }
  }

  async function loadCode() {
    setCodeLoading(true)
    setCodeError(null)
    try {
      const src = await fetchDagCode(dagId, env)
      setCode(src)
    } catch (e: unknown) {
      setCodeError((e as Error).message ?? 'Failed to load DAG code')
    } finally {
      setCodeLoading(false)
    }
  }

  useEffect(() => { load(); loadCode() }, [dagId, env])
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

  // ── Drag-to-resize ─────────────────────────────────────────────────────────
  const onDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true

    function onMouseMove(ev: MouseEvent) {
      if (!isDragging.current || !splitContainerRef.current) return
      const rect = splitContainerRef.current.getBoundingClientRect()
      const pct  = ((ev.clientX - rect.left) / rect.width) * 100
      setLeftPct(Math.min(Math.max(pct, MIN_LEFT_PCT), MAX_LEFT_PCT))
    }

    function onMouseUp() {
      isDragging.current = false
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [])

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
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3 flex-shrink-0 border-b border-gray-100">
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
          {triggerMsg && <span className="text-xs text-brand-600 mt-0.5">{triggerMsg}</span>}
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

      {/* ── Split pane ─────────────────────────────────────────────────────── */}
      <div
        ref={splitContainerRef}
        className="flex flex-row flex-1 min-h-0 overflow-hidden"
        style={{ userSelect: isDragging.current ? 'none' : undefined }}
      >
        {/* Left panel: Run History + DAG Code */}
        <div
          className="flex flex-col min-h-0 overflow-hidden p-3 gap-3"
          style={{ width: `${leftPct}%`, flexShrink: 0 }}
        >
          {/* Run history — compact fixed block */}
          <div className="flex-shrink-0">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5 px-0.5">Run History</p>
            <RunHistory runs={runs} selectedRunId={selectedRunId} onSelectRun={handleSelectRun} />
          </div>

          {/* DAG code — fills remaining left-panel height */}
          <div className="flex flex-col flex-1 min-h-0">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5 px-0.5">DAG Code</p>
            <div className="flex flex-col flex-1 min-h-0">
              <DagCodeViewer
                code={code}
                loading={codeLoading}
                error={codeError}
                dagId={dagId}
                onSendToAgent={onSendToAgent
                  ? (c) => onSendToAgent(`Here is the DAG code for \`${dagId}\`. Ask me anything about it:\n\`\`\`python\n${c}\n\`\`\``)
                  : undefined}
              />
            </div>
          </div>
        </div>

        {/* Drag divider */}
        <div
          onMouseDown={onDividerMouseDown}
          className="w-1.5 flex-shrink-0 bg-gray-200 hover:bg-brand-400 active:bg-brand-500 transition-colors cursor-col-resize"
          title="Drag to resize"
        />

        {/* Right panel: Block diagram */}
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden p-3">
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5 px-0.5">DAG Graph</p>
          <div className="flex-1 min-h-0 rounded-xl border border-gray-200 overflow-hidden bg-slate-50 relative">
            {tasksLoading && (
              <div className="absolute inset-0 bg-white/70 flex items-center justify-center z-10">
                <Loader2 size={20} className="animate-spin text-brand-500" />
              </div>
            )}
            <DagGraph tasks={tasks} onTaskClick={handleTaskClick} selectedTaskId={selectedTaskId} />
          </div>
          <p className="text-xs text-gray-400 mt-1.5 flex-shrink-0">Click a task node to open its SQL in a new tab.</p>
        </div>
      </div>
    </div>
  )
}
