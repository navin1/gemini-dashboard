import { useEffect, useRef, useState } from 'react'
import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'
import 'highlight.js/styles/atom-one-dark.css'
import { Copy, CheckCheck, Download, TriangleAlert, Info, Sparkles, RefreshCw } from 'lucide-react'
import type { TaskSqlResult } from '../../types'
import { STATE_COLORS, STATE_ICONS } from './TaskNode'
import { optimizeSql } from '../../api/query'
import DiffViewer from './DiffViewer'

hljs.registerLanguage('sql', sql)

function highlight(code: string): string {
  try { return hljs.highlight(code, { language: 'sql' }).value }
  catch { return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
}

function addLineNumbers(highlighted: string): string {
  return highlighted.split('\n')
    .map((line, i) => `<span class="line-num">${String(i + 1).padStart(3, ' ')}</span>${line}`)
    .join('\n')
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const ms   = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(ms / 60_000)
  const hours = Math.floor(mins / 60)
  const days  = Math.floor(hours / 24)
  if (days  > 0) return `${days}d ago`
  if (hours > 0) return `${hours}h ago`
  if (mins  > 0) return `${mins}m ago`
  return 'just now'
}

const btnBase: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 5,
  background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: 6, padding: '5px 11px', cursor: 'pointer', fontSize: 12, color: '#94A3B8',
}

function CopyBtn({ text, label = 'Copy SQL' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      style={btnBase}
    >
      {copied ? <CheckCheck size={13} color="#4ade80" /> : <Copy size={13} />}
      <span style={{ color: copied ? '#4ade80' : '#94A3B8' }}>{copied ? 'Copied!' : label}</span>
    </button>
  )
}

function DownloadBtn({ text, filename }: { text: string; filename: string }) {
  function download() {
    const blob = new Blob([text], { type: 'text/plain' })
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: filename })
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <button onClick={download} style={btnBase}>
      <Download size={13} />
      <span>Download .sql</span>
    </button>
  )
}

interface Props {
  taskId: string
  operatorFull: string
  state: string | null
  lastRunStart: string | null
  sqlResult: TaskSqlResult | null
  loading: boolean
  error: string | null
}

export default function SqlViewer({ taskId, operatorFull, state, lastRunStart, sqlResult, loading, error }: Props) {
  const codeRef = useRef<HTMLElement>(null)
  const withLineNums = sqlResult?.sql ? addLineNumbers(highlight(sqlResult.sql)) : null

  const [showDiff,      setShowDiff]      = useState(false)
  const [optimizedSql,  setOptimizedSql]  = useState<string | null>(null)
  const [optimizing,    setOptimizing]    = useState(false)
  const [optimizeError, setOptimizeError] = useState<string | null>(null)

  useEffect(() => {
    if (codeRef.current && withLineNums) codeRef.current.innerHTML = withLineNums
  }, [withLineNums])

  // Reset diff state when SQL changes (e.g. navigating to another task)
  useEffect(() => { setShowDiff(false); setOptimizedSql(null); setOptimizeError(null) }, [sqlResult?.sql])

  async function handleOptimize() {
    if (!sqlResult?.sql) return
    setOptimizing(true)
    setOptimizeError(null)
    setShowDiff(false)
    try {
      const result = await optimizeSql(sqlResult.sql)
      setOptimizedSql(result)
      setShowDiff(true)
    } catch (e) {
      setOptimizeError((e as Error).message ?? 'Optimization failed')
    } finally {
      setOptimizing(false)
    }
  }

  const stateColor = STATE_COLORS[state ?? ''] ?? STATE_COLORS._default
  const stateIcon  = state ? STATE_ICONS[state] ?? '◆' : null
  const hasSql     = !!sqlResult?.sql

  return (
    <div style={{ display: 'flex', flexDirection: 'column', background: '#0F172A', flex: 1, overflow: 'hidden', minHeight: 0 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid #1E293B', gap: 12, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flex: 1 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: '#F1F5F9' }}>{taskId}</span>
          {operatorFull && (
            <span style={{ background: '#334155', color: '#CBD5E1', borderRadius: 4, padding: '2px 7px', fontSize: 11, fontWeight: 600 }}>
              {operatorFull.replace('Operator', '')}
            </span>
          )}
          {state && (
            <span style={{ background: stateColor + '33', color: stateColor, borderRadius: 4, padding: '2px 7px', fontSize: 11, fontWeight: 600 }}>
              {stateIcon} {state.replace(/_/g, ' ')}
            </span>
          )}
          {sqlResult?.source && sqlResult.source !== 'none' && (
            <span style={{ background: '#1e3a5f', color: '#60A5FA', borderRadius: 4, padding: '2px 7px', fontSize: 11, fontWeight: 600 }}>
              <Info size={10} style={{ verticalAlign: 'middle' }} /> {sqlResult.source}
            </span>
          )}
          {lastRunStart && (
            <span style={{ fontSize: 11, color: '#64748B' }}>Last run: {timeAgo(lastRunStart)}</span>
          )}
        </div>
      </div>

      {/* Action bar */}
      {hasSql && !showDiff && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', background: '#0F172A', borderBottom: '1px solid #1E293B', flexShrink: 0 }}>
          <CopyBtn    text={sqlResult!.sql!} />
          <DownloadBtn text={sqlResult!.sql!} filename={`${taskId}.sql`} />
          <div style={{ marginLeft: 'auto' }}>
            <button
              onClick={handleOptimize}
              disabled={optimizing}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontSize: 12, fontWeight: 600,
                color:      optimizing ? '#9CA3AF' : '#fff',
                background: optimizing ? '#334155' : 'linear-gradient(135deg,#6366F1,#8B5CF6)',
                border: 'none', borderRadius: 7, padding: '6px 14px',
                cursor: optimizing ? 'not-allowed' : 'pointer',
                boxShadow: optimizing ? 'none' : '0 2px 8px rgba(99,102,241,0.35)',
              }}
            >
              {optimizing
                ? <><RefreshCw size={13} style={{ animation: 'spin 0.7s linear infinite' }} /> Optimizing…</>
                : <><Sparkles size={13} /> Optimize with Vertex AI</>}
            </button>
          </div>
        </div>
      )}

      {showDiff && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', background: '#1E293B', borderBottom: '1px solid #334155', flexShrink: 0 }}>
          <button onClick={() => setShowDiff(false)} style={btnBase}>← Back to SQL</button>
          <span style={{ fontSize: 12, color: '#64748B', marginLeft: 4 }}>Vertex AI optimization</span>
        </div>
      )}

      {/* Optimize error */}
      {optimizeError && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', background: '#FEF2F2', color: '#B91C1C', fontSize: 12, borderBottom: '1px solid #FECACA', flexShrink: 0 }}>
          <TriangleAlert size={14} /> {optimizeError}
          <button onClick={() => setOptimizeError(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: '#B91C1C' }}>✕</button>
        </div>
      )}

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', position: 'relative', display: 'flex', flexDirection: 'column' }}>
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 10 }}>
            <div style={{ width: 22, height: 22, border: '2.5px solid #1E293B', borderTop: '2.5px solid #6366F1', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
            <span style={{ color: '#64748B', fontSize: 13 }}>Fetching SQL…</span>
          </div>
        )}
        {!loading && error && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 24 }}>
            <TriangleAlert size={22} color="#F87171" />
            <span style={{ color: '#F87171', fontSize: 13, textAlign: 'center', maxWidth: 480 }}>{error}</span>
          </div>
        )}
        {!loading && !error && sqlResult?.source === 'none' && !showDiff && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 24 }}>
            <Info size={22} color="#64748B" />
            <span style={{ color: '#64748B', fontSize: 13 }}>
              No SQL found for <strong style={{ color: '#94A3B8' }}>{taskId}</strong>.
              This task may not use a SQL operator, or has not run successfully yet.
            </span>
          </div>
        )}
        {!loading && !error && hasSql && !showDiff && (
          <pre style={{ margin: 0, padding: '16px 0 40px', fontSize: 13, lineHeight: 1.7, tabSize: 2, background: 'transparent', flex: 1 }}>
            <code ref={codeRef} className="hljs language-sql" style={{ fontFamily: '"JetBrains Mono", "Fira Code", Consolas, monospace', background: 'transparent', display: 'block', padding: '0 16px', whiteSpace: 'pre' }} />
          </pre>
        )}
        {hasSql && showDiff && optimizedSql && (
          <DiffViewer original={sqlResult!.sql!} optimized={optimizedSql} />
        )}
      </div>
    </div>
  )
}
