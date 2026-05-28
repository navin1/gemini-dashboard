export interface Widget {
  id: string
  title: string
  chart_type: ChartType
  x_axis?: string
  y_axis: string[]
  color_field?: string
  stacked: boolean
  dual_axis: boolean
  secondary_y?: string
  ai_description: string
  sql: string
  data: Record<string, unknown>[]
  nl_query?: string
  live?: boolean          // true = this widget streams live updates
  error?: string          // set when the widget encountered a SQL or render error
  prevH?: number          // stored when widget is collapsed so height can be restored
  homeTabId?: string      // set when widget is moved away from its origin tab
  lockedHeaderBg?: string      // header bg color locked at copy/move time
  lockedHeaderBorder?: string  // header border color locked at copy/move time
  lockedAirflowEnv?: string    // airflow env locked at copy/move time (airflow_dags only)
  lockedTabPrefix?: string     // badge label locked at copy/move time (DEV/UAT/PRD/My)
  // react-grid-layout position
  layout?: GridLayout
}

export type ChartType =
  | 'bar'
  | 'stacked_bar'
  | 'line'
  | 'combo'
  | 'donut'
  | 'pie'
  | 'table'
  | 'kpi'
  | 'horizontal_bar'
  | 'airflow_dags'
  | 'schema_audit'

export interface GridLayout {
  i: string
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

export interface GlossaryTerm {
  id: number
  term: string
  definition: string
  example?: string
  is_default: boolean
  user_id?: string
}

export interface Favorite {
  id: number
  name: string
  nl_query?: string
  sql_query: string
  chart_type?: string
  widget_config?: string
  is_default: boolean
  user_id?: string
}

export interface QueryResponse {
  sql: string
  chart_type: ChartType
  title: string
  x_axis?: string
  y_axis: string[]
  color_field?: string
  stacked: boolean
  dual_axis: boolean
  secondary_y?: string
  ai_description: string
  data: Record<string, unknown>[]
}

export interface CustomKpi {
  id: string
  label: string
  value: number
}

// ── Airflow / Composer types ──────────────────────────────────────────────────

export type AirflowTaskState =
  | 'success' | 'failed' | 'running' | 'queued'
  | 'up_for_retry' | 'skipped' | 'upstream_failed'
  | 'deferred' | 'removed' | null

export interface AirflowEnv {
  name: string
  url: string
}

export interface AirflowTask {
  task_id: string
  operator: string
  downstream_task_ids: string[]
  state?: AirflowTaskState
  duration_seconds?: number
}

export interface AirflowRun {
  run_id: string
  state: string
  execution_date: string
  start_date: string | null
  end_date: string | null
}

export interface DagStatus {
  dag_id: string
  state: string | null
  last_run_time: string | null
  error?: string
}

export interface TaskSqlResult {
  sql: string | null
  source: 'rendered' | 'raw' | 'none'
  truncated: boolean
}

export interface TaskNodeData extends Record<string, unknown> {
  taskId: string
  operatorFull: string
  operatorShort: string
  state: AirflowTaskState
  durationSeconds?: number
  isActiveRun?: boolean
}

export interface AirflowTab {
  id: string
  label: string
  type: 'airflow_dag' | 'airflow_sql'
  dagId: string
  env: string
  runId?: string
  taskId?: string
  operatorFull?: string
}

export interface KPIData {
  spend_to_date: number
  commit_spend: number
  pct_spend: number
}

export interface ScorecardFTE {
  kpi: KPIData[]
  monthly_capital_expense: Record<string, unknown>[]
  monthly_fte: Record<string, unknown>[]
  hierarchy_table: Record<string, unknown>[]
  capital_expense_donut: Record<string, unknown>[]
  monthly_cap_exp_ftp: Record<string, unknown>[]
  _sql: Record<string, string>
}

export interface ScorecardVendor {
  vendor_table: Record<string, unknown>[]
  offshore_onshore_bar: Record<string, unknown>[]
  billtype_bar: Record<string, unknown>[]
  monthly_vendor_spend: Record<string, unknown>[]
  spend_by_tier_monthly: Record<string, unknown>[]
  monthly_cap_exp_ftp: Record<string, unknown>[]
  tier_breakdown: Record<string, unknown>[]
  vendor_resource_count: Record<string, unknown>[]
  vendor_kpis: Record<string, unknown>[]
  _sql: Record<string, string>
}

export interface ScorecardHierarchy {
  hierarchy_drill: Record<string, unknown>[]
  spend_by_tier_monthly: Record<string, unknown>[]
  billtype_monthly: Record<string, unknown>[]
  tier_breakdown: Record<string, unknown>[]
  _sql: Record<string, string>
}
