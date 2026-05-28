import client from './client'

export interface ExcelMappingFile {
  display_name: string
  total_rows: number | null
  mapped: number | null
  in_progress: number | null
  error: string | null
}

export interface ExcelMappingResponse {
  configured: boolean
  files: ExcelMappingFile[]
}

export async function fetchExcelMapping(): Promise<ExcelMappingResponse> {
  const { data } = await client.get<ExcelMappingResponse>('/excel-mapping')
  return data
}

export async function refreshExcelMapping(): Promise<ExcelMappingResponse> {
  const { data } = await client.post<ExcelMappingResponse>('/excel-mapping/refresh')
  return data
}

export function getPreviewUrl(filename: string): string {
  return `/api/excel-mapping/${encodeURIComponent(filename)}/preview`
}
