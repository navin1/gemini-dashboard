import client from './client'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatWidgetDef {
  sql: string
  chart_type: string
  title: string
  x_axis?: string
  y_axis: string[]
  color_field?: string
  stacked: boolean
  dual_axis: boolean
  secondary_y?: string
  ai_description: string
  data: Record<string, unknown>[]
  error?: string
}

export interface ChatResponse {
  text: string
  intent: string
  widget?: ChatWidgetDef
  suggested_questions?: string[]
}

export async function sendChatMessage(
  message: string,
  history: ChatMessage[]
): Promise<ChatResponse> {
  const { data } = await client.post<ChatResponse>('/chat', { message, history })
  return data
}

export async function runSqlQuery(sql: string): Promise<ChatResponse> {
  try {
    const { data } = await client.post<ChatWidgetDef>('/query/sql', { sql })
    return {
      text: `Executed SQL — ${data.data?.length ?? 0} row(s) returned.`,
      intent: 'sql',
      widget: data,
    }
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? ''
    const msg = detail || (err instanceof Error ? err.message : 'SQL execution failed')
    return {
      text: msg,
      intent: 'sql',
      widget: {
        sql,
        error: msg,
        chart_type: 'table',
        title: 'SQL Error',
        y_axis: [],
        stacked: false,
        dual_axis: false,
        ai_description: '',
        data: [],
      },
    }
  }
}
