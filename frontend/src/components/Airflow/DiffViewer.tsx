import { useMemo, useState } from 'react'
import { diffLines } from 'diff'
import hljs from 'highlight.js/lib/core'
import sql from 'highlight.js/lib/languages/sql'
import { Copy, Download, CheckCheck } from 'lucide-react'

hljs.registerLanguage('sql', sql)

type LineType = 'normal' | 'removed' | 'added' | 'empty'

interface SideLine { text: string; type: LineType }
interface DiffRow   { left: SideLine; right: SideLine; num: number }

function splitLines(val: string): string[] {
  const lines = val.split('\n')
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
  return lines
}

function buildRows(original: string, optimized: string): DiffRow[] {
  const changes = diffLines(original, optimized)
  const rows: DiffRow[] = []
  let num = 0
  let i = 0
  while (i < changes.length) {
    const change = changes[i]
    const lines  = splitLines(change.value)
    if (!change.added && !change.removed) {
      lines.forEach(line => {
        rows.push({ left: { text: line, type: 'normal' }, right: { text: line, type: 'normal' }, num: ++num })
      })
      i++
    } else if (change.removed) {
      const next        = changes[i + 1]
      const removedLines = lines
      const addedLines   = next?.added ? splitLines(next.value) : []
      const maxLen       = Math.max(removedLines.length, addedLines.length)
      for (let j = 0; j < maxLen; j++) {
        rows.push({
          left:  { text: j < removedLines.length ? removedLines[j] : '', type: j < removedLines.length ? 'removed' : 'empty' },
          right: { text: j < addedLines.length   ? addedLines[j]   : '', type: j < addedLines.length   ? 'added'   : 'empty' },
          num:   ++num,
        })
      }
      i += next?.added ? 2 : 1
    } else {
      lines.forEach(line => {
        rows.push({ left: { text: '', type: 'empty' }, right: { text: line, type: 'added' }, num: ++num })
      })
      i++
    }
  }
  return rows
}

function hl(line: string): string {
  if (!line.trim()) return '&nbsp;'
  try { return hljs.highlight(line, { language: 'sql' }).value }
  catch { return line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
}

function getBG(type: LineType): string {
  if (type === 'removed') return 'rgba(239,68,68,0.15)'
  if (type === 'added')   return 'rgba(16,185,129,0.15)'
  if (type === 'empty')   return 'rgba(255,255,255,0.03)'
  return 'transparent'
}

const BORDER_LEFT: Record<LineType, string> = {
  normal:  '3px solid transparent',
  removed: '3px solid #EF4444',
  added:   '3px solid #10B981',
  empty:   '3px solid transparent',
}

function PanelActionBar({ sqlText, label }: { sqlText: string; label: string }) {
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard.writeText(sqlText)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function download() {
    const blob = new Blob([sqlText], { type: 'text/plain' })
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: `${label.toLowerCase().replace(/\s+/g, '_')}.sql`,
    })
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const btnStyle: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
    color: '#94A3B8', background: 'rgba(255,255,255,0.07)',
    border: '1px solid rgba(255,255,255,0.12)', borderRadius: 5,
    padding: '3px 8px', cursor: 'pointer',
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', padding: '8px 12px', background: '#1E293B', borderBottom: '1px solid #334155', gap: 8, flexShrink: 0 }}>
      <span style={{ fontWeight: 700, fontSize: 12, color: '#475569', letterSpacing: '0.06em' }}>
        {label.toUpperCase()}
      </span>
      <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
        <button onClick={copy} style={btnStyle}>
          {copied ? <CheckCheck size={12} color="#4ade80" /> : <Copy size={12} />}
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button onClick={download} style={btnStyle}><Download size={12} /> .sql</button>
      </div>
    </div>
  )
}

interface DiffViewerProps {
  original:  string
  optimized: string
}

export default function DiffViewer({ original, optimized }: DiffViewerProps) {
  const rows = useMemo(() => buildRows(original, optimized), [original, optimized])
  const addedCount   = rows.filter(r => r.right.type === 'added').length
  const removedCount = rows.filter(r => r.left.type  === 'removed').length

  const lineNumStyle: React.CSSProperties = {
    display: 'inline-block', minWidth: '3em', fontSize: 12,
    fontFamily: '"Courier New", monospace', padding: '0 8px',
    userSelect: 'none', flexShrink: 0, textAlign: 'right',
    lineHeight: '1.7em', borderRight: '1px solid #1E293B', color: '#475569',
  }

  const codeLineStyle: React.CSSProperties = {
    fontFamily: '"Courier New", "JetBrains Mono", Consolas, monospace',
    fontSize: 13, lineHeight: '1.7em', whiteSpace: 'pre',
    flex: 1, padding: '0 12px 0 8px', color: '#CBD5E1',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 16, padding: '8px 20px', background: '#1E293B', borderBottom: '1px solid #334155', alignItems: 'center', flexShrink: 0 }}>
        <span style={{ color: '#10B981', fontWeight: 600, fontSize: 12 }}>+{addedCount} added</span>
        <span style={{ color: '#EF4444', fontWeight: 600, fontSize: 12 }}>−{removedCount} removed</span>
        <span style={{ color: '#64748B', fontSize: 11 }}>{rows.length} total lines · line-by-line diff</span>
      </div>

      {/* Side-by-side panels */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* LEFT — original */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#0F172A' }}>
          <PanelActionBar sqlText={original}  label="Original SQL" />
          <div style={{ flex: 1, overflow: 'auto', paddingBottom: 40 }}>
            {rows.map((row, i) => (
              <div key={i} style={{ display: 'flex', background: getBG(row.left.type), borderLeft: BORDER_LEFT[row.left.type], minHeight: '1.7em', alignItems: 'baseline' }}>
                <span style={lineNumStyle}>{row.left.type !== 'empty' ? row.num : ''}</span>
                <span style={codeLineStyle} dangerouslySetInnerHTML={{ __html: hl(row.left.text) }} />
              </div>
            ))}
          </div>
        </div>

        <div style={{ width: 2, background: '#1E293B', flexShrink: 0 }} />

        {/* RIGHT — optimized */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#0F172A' }}>
          <PanelActionBar sqlText={optimized} label="Optimized SQL" />
          <div style={{ flex: 1, overflow: 'auto', paddingBottom: 40 }}>
            {rows.map((row, i) => (
              <div key={i} style={{ display: 'flex', background: getBG(row.right.type), borderLeft: BORDER_LEFT[row.right.type], minHeight: '1.7em', alignItems: 'baseline' }}>
                <span style={lineNumStyle}>{row.right.type !== 'empty' ? row.num : ''}</span>
                <span style={codeLineStyle} dangerouslySetInnerHTML={{ __html: hl(row.right.text) }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
