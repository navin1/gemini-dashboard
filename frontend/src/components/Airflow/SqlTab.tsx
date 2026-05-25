import { useState, useEffect } from 'react'
import { fetchTaskSql } from '../../api/airflow'
import type { TaskSqlResult } from '../../types'
import SqlViewer from './SqlViewer'

interface Props {
  dagId: string
  taskId: string
  env: string
  runId?: string
  operatorFull?: string
  onAnalyzeWithGemini?: (sql: string) => void
}

export default function SqlTab({ dagId, taskId, env, runId, operatorFull, onAnalyzeWithGemini }: Props) {
  const [result, setResult]   = useState<TaskSqlResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchTaskSql(dagId, taskId, env, runId)
      .then(r => { if (!cancelled) { setResult(r); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError((e as Error).message ?? 'Failed to fetch SQL'); setLoading(false) } })
    return () => { cancelled = true }
  }, [dagId, taskId, env, runId])

  return (
    <div className="flex flex-col h-full min-h-0" style={{ background: '#0F172A' }}>
      <SqlViewer
        taskId={taskId}
        operatorFull={operatorFull ?? ''}
        state={null}
        lastRunStart={null}
        sqlResult={result}
        loading={loading}
        error={error}
        onAnalyzeWithGemini={onAnalyzeWithGemini}
      />
    </div>
  )
}
