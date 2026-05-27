import { useMemo, useState } from 'react'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import { Copy, CheckCheck, Loader2, Sparkles } from 'lucide-react'

hljs.registerLanguage('python', python)

function highlightPython(code: string): string {
  try { return hljs.highlight(code, { language: 'python' }).value }
  catch { return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
}

function withLineNumbers(highlighted: string): string {
  return highlighted.split('\n')
    .map((line, i) =>
      `<span style="color:#4b5563;user-select:none;display:inline-block;min-width:2.5em;text-align:right;margin-right:1em;font-size:11px;">${i + 1}</span>${line}`
    )
    .join('\n')
}

interface Props {
  code: string
  loading: boolean
  error: string | null
  dagId?: string
  onSendToAgent?: (code: string) => void
}

export default function DagCodeViewer({ code, loading, error, dagId, onSendToAgent }: Props) {
  const [copied, setCopied] = useState(false)
  const html = useMemo(() => code ? withLineNumbers(highlightPython(code)) : '', [code])

  async function handleCopy() {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', background: '#282c34', flex: 1, minHeight: 0, overflow: 'hidden', borderRadius: 8, border: '1px solid #374151' }}>
      {/* toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#21252b', borderBottom: '1px solid #374151', flexShrink: 0 }}>
        <span style={{ fontSize: 11, color: '#e2e8f0', fontFamily: 'monospace', fontWeight: 700 }}>{dagId ? `${dagId}.py` : 'dag.py'}</span>
        {code && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {onSendToAgent && (
              <button
                onClick={() => onSendToAgent(code)}
                style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.4)', borderRadius: 6, padding: '3px 9px', cursor: 'pointer' }}
                title="Send DAG code to chat agent"
              >
                <Sparkles size={12} color="#a5b4fc" />
                <span style={{ fontSize: 11, color: '#a5b4fc' }}>Send to Agent</span>
              </button>
            )}
            <button
              onClick={handleCopy}
              style={{ display: 'flex', alignItems: 'center', gap: 5, background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6, padding: '3px 9px', cursor: 'pointer' }}
              title="Copy code to clipboard"
            >
              {copied
                ? <><CheckCheck size={12} color="#4ade80" /><span style={{ fontSize: 11, color: '#4ade80' }}>Copied</span></>
                : <><Copy size={12} color="#94a3b8" /><span style={{ fontSize: 11, color: '#94a3b8' }}>Copy</span></>
              }
            </button>
          </div>
        )}
      </div>

      {/* code body */}
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {loading && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, color: '#6b7280' }}>
            <Loader2 size={16} style={{ animation: 'spin 0.7s linear infinite' }} />
            <span style={{ fontSize: 13 }}>Loading code…</span>
          </div>
        )}
        {!loading && error && (
          <div style={{ padding: 16, color: '#f87171', fontSize: 13 }}>{error}</div>
        )}
        {!loading && !error && !code && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#6b7280', fontSize: 13 }}>
            No code available
          </div>
        )}
        {!loading && !error && code && (
          <pre className="hljs" style={{ margin: 0, padding: '12px 8px', fontSize: 12, lineHeight: 1.6, fontFamily: 'monospace', overflow: 'visible', background: 'transparent' }}>
            <code dangerouslySetInnerHTML={{ __html: html }} />
          </pre>
        )}
      </div>
    </div>
  )
}
