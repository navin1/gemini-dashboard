import axios from 'axios'
import type { AirflowEnv, DagStatus, AirflowRun, AirflowTask, TaskSqlResult } from '../types'

interface AirflowConfig {
  environments: AirflowEnv[]
  dags: string[]
  default_env: string | null
}

export interface DagMeta {
  dag_id: string
  env: string
  schedule_interval: string | null
  is_paused: boolean
  last_run_id: string | null
  last_run_state: string | null
  last_run_start: string | null
  last_success_run_id: string | null
}

export async function fetchAirflowConfig(): Promise<AirflowConfig> {
  const { data } = await axios.get('/api/airflow/config')
  return data
}

export async function fetchDagsStatus(env: string): Promise<{ dags: DagStatus[]; env: string }> {
  const { data } = await axios.get('/api/airflow/dags/status', { params: { env } })
  return data
}

/** DAG metadata: schedule, paused state, last run info. Mirrors fetchDagMeta() in the Chrome extension. */
export async function fetchDagMeta(dagId: string, env: string): Promise<DagMeta> {
  const { data } = await axios.get(`/api/airflow/dag/${dagId}/meta`, { params: { env } })
  return data
}

/** Trigger a new DAG run. Mirrors triggerDagRun() in the Chrome extension. */
export async function triggerDagRun(
  dagId: string,
  env: string,
): Promise<{ run_id: string; execution_date: string }> {
  const { data } = await axios.post(`/api/airflow/dag/${dagId}/trigger`, null, { params: { env } })
  return data
}

/** Poll state of a specific run. Mirrors fetchRunState() in the Chrome extension. */
export async function fetchRunState(dagId: string, runId: string, env: string): Promise<string> {
  const { data } = await axios.get(
    `/api/airflow/dag/${dagId}/runs/${encodeURIComponent(runId)}/state`,
    { params: { env } },
  )
  return data.state
}

export async function fetchDagRuns(dagId: string, env: string, limit = 5): Promise<{ runs: AirflowRun[] }> {
  const { data } = await axios.get(`/api/airflow/dag/${dagId}/runs`, { params: { env, limit } })
  return data
}

export async function fetchDagTasks(
  dagId: string,
  env: string,
  runId?: string,
): Promise<{ tasks: AirflowTask[]; run_id: string | null }> {
  const { data } = await axios.get(`/api/airflow/dag/${dagId}/tasks`, {
    params: { env, ...(runId ? { run_id: runId } : {}) },
  })
  return data
}

export async function fetchDagCode(dagId: string, env: string): Promise<string> {
  const { data } = await axios.get(`/api/airflow/dag/${dagId}/code`, { params: { env } })
  return data.code ?? ''
}

export async function fetchTaskSql(
  dagId: string,
  taskId: string,
  env: string,
  runId?: string,
): Promise<TaskSqlResult> {
  const { data } = await axios.get(`/api/airflow/task/${dagId}/${taskId}/sql`, {
    params: { env, ...(runId ? { run_id: runId } : {}) },
  })
  return { sql: data.sql, source: data.source, truncated: data.truncated }
}
