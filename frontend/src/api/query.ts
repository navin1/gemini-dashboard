import client from './client'
import type { QueryResponse } from '../types'

export async function runNLQuery(nl_query: string): Promise<QueryResponse> {
  const { data } = await client.post<QueryResponse>('/query', { nl_query })
  return data
}

export async function refineWidget(sql: string, nl_modification: string): Promise<QueryResponse> {
  const { data } = await client.post<QueryResponse>('/query/refine', { sql, nl_modification })
  return data
}

export async function optimizeSql(sql: string): Promise<string> {
  const { data } = await client.post<{ optimized_sql: string }>('/query/optimize-sql', { sql })
  return data.optimized_sql
}
