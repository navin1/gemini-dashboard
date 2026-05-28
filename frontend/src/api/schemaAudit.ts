import client from './client'

export interface SchemaAuditSummary {
  table_name: string
  col_count_diff: number
  col_name_mismatches: number
  type_mismatches: number
  pos_mismatches: number
  has_mismatch: boolean
  src_missing: boolean
  tgt_missing: boolean
}

export interface SchemaAuditResponse {
  configured: boolean
  tables: SchemaAuditSummary[]
}

export async function fetchSchemaAudit(env: string): Promise<SchemaAuditResponse> {
  const { data } = await client.get<SchemaAuditResponse>(`/schema-audit/${env}`)
  return data
}

export async function downloadSchemaAudit(env: string): Promise<void> {
  const response = await client.get(`/schema-audit/${env}/download`, { responseType: 'blob' })
  const blob = new Blob([response.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const disposition: string = response.headers['content-disposition'] ?? ''
  const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
  const filename = match ? match[1].replace(/['"]/g, '') : `schema_mismatch_${env}.xlsx`
  const url = URL.createObjectURL(blob)
  const a   = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}
