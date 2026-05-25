import { useEffect, useRef, useState } from 'react'
import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'
import 'highlight.js/styles/atom-one-dark.css'
import { Copy, CheckCheck, TriangleAlert, Info, Sparkles } from 'lucide-react'
import type { TaskSqlResult } from '../../types'
import { STATE_COLORS, STATE_ICONS } from './TaskNode'

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

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
      style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer' }}
    >
      {copied ? <CheckCheck size={14} color="#4ade80" /> : <Copy size={14} color="#94A3B8" />}
      <span style={{ fontSize: 11, color: copied ? '#4ade80' : '#94A3B8' }}>{copied ? 'Copied!' : 'Copy'}</span>
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
  onAnalyzeWithGemini?: (sql: string) => void
}

export default function SqlViewer({ taskId, operatorFull, state, lastRunStart, sqlResult, loading, error, onAnalyzeWithGemini }: Props) {
  const codeRef = useRef<HTMLElement>(null)
  const withLineNums = sqlResult?.sql ? addLineNumbers(highlight(sqlResult.sql)) : null

  useEffect(() => {
    if (codeRef.current && withLineNums) codeRef.current.innerHTML = withLineNums
  }, [withLineNums])

  const stateColor = STATE_COLORS[state ?? ''] ?? STATE_COLORS._default
  const stateIcon  = state ? STATE_ICONS[state] ?? '◆' : null

  const btnBase: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer' }

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
            <span style={{ fontSize: 11, color: '#64748B' }}>
              Last run: {timeAgo(lastRunStart)}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {sqlResult?.sql && onAnalyzeWithGemini && (
            <button
              onClick={() => onAnalyzeWithGemini(sqlResult.sql!)}
              style={{ ...btnBase, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.4)', color: '#A5B4FC' }}
            >
              <Sparkles size={13} color="#A5B4FC" />
              <span style={{ fontSize: 11 }}>Analyze with Gemini</span>
            </button>
          )}
          {sqlResult?.sql && <CopyButton text={sqlResult.sql} />}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
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
        {!loading && !error && sqlResult?.source === 'none' && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, padding: 24 }}>
            <Info size={22} color="#64748B" />
            <span style={{ color: '#64748B', fontSize: 13 }}>
              No SQL found for <strong style={{ color: '#94A3B8' }}>{taskId}</strong>.
              This task may not use a SQL operator, or has not run successfully yet.
            </span>
          </div>
        )}
        {!loading && !error && sqlResult?.sql && (
          <pre style={{ margin: 0, padding: '16px 0 40px', fontSize: 13, lineHeight: 1.7, tabSize: 2, background: 'transparent' }}>
            <code ref={codeRef} className="hljs language-sql" style={{ fontFamily: '"JetBrains Mono", "Fira Code", Consolas, monospace', background: 'transparent', display: 'block', padding: '0 16px', whiteSpace: 'pre' }} />
          </pre>
        )}
      </div>
    </div>
  )
}
