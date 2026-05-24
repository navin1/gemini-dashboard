import { useEffect, useRef, useState } from 'react'
import client from '../api/client'
import type { Widget } from '../types'
import type { LiveStatus } from './useLiveStream'

export type { LiveStatus }

/**
 * Session-based SSE stream for arbitrary custom widgets.
 *
 * Flow:
 *   1. POST /api/stream/session with [{id, sql}] → session_id
 *   2. Open EventSource on /api/stream/custom/{session_id}
 *   3. On each event, call onUpdate(widgetId, freshData) for each widget update
 *
 * Reconnects only when the set of widget IDs changes (not when data changes),
 * so adding a widget reopens the stream while rearranging widgets does not.
 */
export function useCustomWidgetStream(
  widgets: Widget[],
  enabled: boolean,
  onUpdate: (id: string, data: Record<string, unknown>[]) => void,
): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>('off')
  const esRef = useRef<EventSource | null>(null)
  const onUpdateRef = useRef(onUpdate)
  useEffect(() => { onUpdateRef.current = onUpdate })

  // Keep a ref to the latest widget SQL map so the effect closure can read it
  // without being included in deps (prevents reconnect on data-only changes)
  const widgetSqlRef = useRef<Record<string, string>>({})
  useEffect(() => {
    widgetSqlRef.current = Object.fromEntries(
      widgets.filter(w => w.sql && w.chart_type !== 'kpi').map(w => [w.id, w.sql])
    )
  })

  // Stable key: sorted IDs of streamable widgets — changes only when widgets are added/removed
  const widgetKey = widgets
    .filter(w => w.sql && w.chart_type !== 'kpi')
    .map(w => w.id)
    .sort()
    .join(',')

  useEffect(() => {
    if (!enabled || !widgetKey) {
      esRef.current?.close()
      esRef.current = null
      setStatus('off')
      return
    }

    let cancelled = false

    async function connect() {
      esRef.current?.close()
      esRef.current = null
      setStatus('connecting')

      try {
        const entries = widgetKey.split(',').map(id => ({
          id,
          sql: widgetSqlRef.current[id] ?? '',
        })).filter(e => e.sql)

        if (!entries.length) { setStatus('off'); return }

        const { data } = await client.post<{ session_id: string }>(
          '/stream/session',
          { widgets: entries },
        )
        if (cancelled) return

        const es = new EventSource(`/api/stream/custom/${data.session_id}`)
        esRef.current = es

        es.onopen = () => { if (!cancelled) setStatus('live') }
        es.onmessage = (e: MessageEvent) => {
          if (cancelled) return
          try {
            const payload = JSON.parse(e.data) as { updates: { id: string; data: Record<string, unknown>[]; error: string | null }[] }
            for (const u of payload.updates ?? []) {
              if (!u.error) onUpdateRef.current(u.id, u.data)
            }
          } catch { /* ignore parse errors */ }
        }
        es.onerror = () => { if (!cancelled) setStatus('error') }
      } catch {
        if (!cancelled) setStatus('error')
      }
    }

    connect()

    return () => {
      cancelled = true
      esRef.current?.close()
      esRef.current = null
      setStatus('off')
    }
  }, [enabled, widgetKey])

  return status
}
