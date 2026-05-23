import client from './client'
import type { Widget } from '../types'

export async function exportPDF(tabName: string, title: string, widgets: Widget[]): Promise<void> {
  const resp = await client.post(
    '/pdf/export',
    {
      tab_name: tabName,
      title,
      widgets: widgets.map((w) => ({
        title: w.title,
        chart_type: w.chart_type,
        ai_description: w.ai_description,
        data: w.data,
        x_axis: w.x_axis,
        y_axis: w.y_axis ?? [],
        color_field: w.color_field,
        stacked: w.stacked ?? false,
        dual_axis: w.dual_axis ?? false,
        secondary_y: w.secondary_y,
      })),
    },
    { responseType: 'blob' }
  )
  const url = URL.createObjectURL(new Blob([resp.data], { type: 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${tabName.replace(/\s+/g, '_')}_report.pdf`
  a.click()
  URL.revokeObjectURL(url)
}
