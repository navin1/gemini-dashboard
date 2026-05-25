import axios from 'axios'
import type { AirflowEnv, DagStatus, AirflowRun, AirflowTask, TaskSqlResult } from '../types'

interface AirflowConfig {
  environments: AirflowEnv[]
  dags: string[]
  default_env: string | null
}

export async function fetchAirflowConfig(): Promise<AirflowConfig> {
  const { data } = await axios.get('/api/airflow/config')
  return data
}

export async function fetchDagsStatus(env: string): Promise<{ dags: DagStatus[]; env: string }> {
  const { data } = await axios.get('/api/airflow/dags/status', { params: { env } })
  return data
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
