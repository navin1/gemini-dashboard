import { useEffect, useRef, useState } from 'react'

export type LiveStatus = 'off' | 'connecting' | 'live' | 'error'

/**
 * Opens an EventSource on /api{path} and calls onData with each parsed event.
 * Passes the stored OAuth token as a query param because EventSource cannot
 * send custom headers.
 */
export function useLiveStream<T>(
  path: string,
  enabled: boolean,
  onData: (data: T) => void,
): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>('off')
  const esRef = useRef<EventSource | null>(null)
  // Stable ref so the effect doesn't re-run when the callback identity changes
  const onDataRef = useRef(onData)
  useEffect(() => { onDataRef.current = onData })

  useEffect(() => {
    if (!enabled) {
      esRef.current?.close()
      esRef.current = null
      setStatus('off')
      return
    }

    const token = localStorage.getItem('google_oauth_token') ?? ''
    const qs = token ? `?token=${encodeURIComponent(token)}` : ''
    const es = new EventSource(`/api${path}${qs}`)
    esRef.current = es
    setStatus('connecting')

    es.onopen = () => setStatus('live')
    es.onmessage = (e: MessageEvent) => {
      try { onDataRef.current(JSON.parse(e.data) as T) } catch { /* ignore parse errors */ }
    }
    // onerror fires on transient drops too; browser auto-reconnects, so treat as degraded
    es.onerror = () => setStatus('error')

    return () => {
      es.close()
      esRef.current = null
      setStatus('off')
    }
  }, [enabled, path])

  return status
}
