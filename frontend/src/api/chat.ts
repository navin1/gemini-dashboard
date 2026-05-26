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

export type StreamEvent =
  | { type: 'status'; message: string }
  | { type: 'result'; data: ChatResponse }
  | { type: 'error'; message: string }

export async function* streamChatMessage(
  message: string,
  history: ChatMessage[]
): AsyncGenerator<StreamEvent> {
  const token = localStorage.getItem('google_oauth_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, history }),
  })

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const event = JSON.parse(line.slice(6)) as StreamEvent
        yield event
      } catch {
        // ignore malformed lines
      }
    }
  }
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
