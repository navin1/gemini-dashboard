import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, Star, ChevronDown, ChevronUp, Maximize2, Code2, Sparkles, Loader2, Pencil, CornerUpRight, CopyPlus, Wifi, WifiOff, RefreshCw, AlertCircle } from 'lucide-react'
import { ChartRenderer } from '../Charts/ChartRenderer'
import { DataTable } from '../DataTable/DataTable'
import { refineWidget } from '../../api/query'
import { useWidgetTransfer } from '../../context/WidgetTransferContext'
import { useTabTheme } from '../../context/TabThemeContext'
import AirflowSection from '../Airflow/AirflowSection'
import { LiveBadge } from '../common/LiveBadge'
import type { Widget as WidgetType } from '../../types'
import type { LiveStatus } from '../../hooks/useLiveStream'

const TYPE_STYLE: Record<string, { border: string; badge: string }> = {
  bar:            { border: 'border-l-blue-400',    badge: 'bg-blue-50 text-blue-700' },
  stacked_bar:    { border: 'border-l-indigo-400',  badge: 'bg-indigo-50 text-indigo-700' },
  line:           { border: 'border-l-emerald-400', badge: 'bg-emerald-50 text-emerald-700' },
  donut:          { border: 'border-l-amber-400',   badge: 'bg-amber-50 text-amber-700' },
  pie:            { border: 'border-l-orange-400',  badge: 'bg-orange-50 text-orange-700' },
  table:          { border: 'border-l-violet-400',  badge: 'bg-violet-50 text-violet-700' },
  kpi:            { border: 'border-l-sky-400',     badge: 'bg-sky-50 text-sky-700' },
  combo:          { border: 'border-l-teal-400',    badge: 'bg-teal-50 text-teal-700' },
  horizontal_bar: { border: 'border-l-cyan-400',    badge: 'bg-cyan-50 text-cyan-700' },
  airflow_dags:   { border: 'border-l-sky-500',     badge: 'bg-sky-50 text-sky-700' },
}
const FALLBACK = { border: 'border-l-slate-300', badge: 'bg-slate-100 text-slate-600' }

const TAB_BADGE: Record<string, string> = {
  DEV: 'bg-blue-100 text-blue-700',
  UAT: 'bg-yellow-100 text-yellow-700',
  PRD: 'bg-green-100 text-green-700',
  My:  'bg-gray-100 text-gray-600',
}

// Stop RGL from treating button clicks as drag starts
function noDrag(e: React.MouseEvent) { e.stopPropagation() }

interface Props {
  widget: WidgetType
  onRemove: (id: string) => void
  isFavorited: boolean
  isFavoritePending?: boolean
  onFavoriteToggle: () => void
  onUpdate?: (widget: WidgetType) => void
}

export function Widget({ widget, onRemove, isFavorited, isFavoritePending, onFavoriteToggle, onUpdate }: Props) {
  const isCollapsed = widget.prevH !== undefined
  const [showData, setShowData] = useState(false)
  const [showSql, setShowSql] = useState(false)
  const [nlInput, setNlInput] = useState('')
  const [refining, setRefining] = useState(false)
  const [refineError, setRefineError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const style = TYPE_STYLE[widget.chart_type] ?? FALLBACK
  const hasSql = !!widget.sql?.trim()
  const isAirflow = widget.chart_type === 'airflow_dags'
  const { headerBg: ctxHeaderBg, headerBorder: ctxHeaderBorder, airflowEnv: ctxAirflowEnv, tabPrefix } = useTabTheme()
  // Prefer widget-locked values (set at copy/move time) over live context
  const headerBg     = widget.lockedHeaderBg    ?? ctxHeaderBg
  const headerBorder = widget.lockedHeaderBorder ?? ctxHeaderBorder
  const badgePrefix  = widget.lockedTabPrefix   ?? tabPrefix

  // Build widget with theme locked for transfer to another tab
  function withLockedTheme(w: WidgetType): WidgetType {
    return {
      ...w,
      lockedHeaderBg:    w.lockedHeaderBg    ?? ctxHeaderBg,
      lockedHeaderBorder: w.lockedHeaderBorder ?? ctxHeaderBorder,
      lockedTabPrefix:   w.lockedTabPrefix   ?? tabPrefix,
      ...(isAirflow && { lockedAirflowEnv: w.lockedAirflowEnv ?? ctxAirflowEnv }),
    }
  }
  // Clear locks when returning home (context supplies correct colors again)
  function withClearedTheme(w: WidgetType): WidgetType {
    return { ...w, lockedHeaderBg: undefined, lockedHeaderBorder: undefined, lockedAirflowEnv: undefined, lockedTabPrefix: undefined }
  }

  // Airflow widget controls — live state reported up from AirflowSection
  const [airflowLiveStatus, setAirflowLiveStatus] = useState<LiveStatus>('off')
  const airflowRefreshRef = useRef<(() => void) | null>(null)
  const handleAirflowLiveStatus = useCallback((s: LiveStatus) => setAirflowLiveStatus(s), [])
  const handleRegisterRefresh = useCallback((fn: () => void) => { airflowRefreshRef.current = fn }, [])

  // Inline title rename
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleInput, setTitleInput] = useState('')
  function startTitleEdit() { setTitleInput(widget.title); setEditingTitle(true) }
  function commitTitleRename() {
    setEditingTitle(false)
    const trimmed = titleInput.trim()
    if (trimmed && trimmed !== widget.title) onUpdate?.({ ...widget, title: trimmed })
  }

  // Send to tab / return home
  const { targets, sendToTab, copyToTab, currentTabId } = useWidgetTransfer()
  const isAwayFromHome = !!(widget.homeTabId && widget.homeTabId !== currentTabId)
  function handleRemove() {
    if (isAwayFromHome) sendToTab(withClearedTheme(widget), widget.homeTabId!)
    onRemove(widget.id)
  }
  const [showSendMenu, setShowSendMenu] = useState(false)
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null)
  const sendBtnRef = useRef<HTMLButtonElement>(null)
  const sendMenuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!showSendMenu) return
    function close(e: MouseEvent) {
      if (
        !sendMenuRef.current?.contains(e.target as Node) &&
        !sendBtnRef.current?.contains(e.target as Node)
      ) setShowSendMenu(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [showSendMenu])

  function openSendMenu() {
    const rect = sendBtnRef.current?.getBoundingClientRect()
    if (rect) setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
    setShowSendMenu((s) => !s)
  }

  const [showCopyMenu, setShowCopyMenu] = useState(false)
  const [copyMenuPos, setCopyMenuPos] = useState<{ top: number; right: number } | null>(null)
  const copyBtnRef = useRef<HTMLButtonElement>(null)
  const copyMenuRef = useRef<HTMLDivElement>(null)
  const [copiedTo, setCopiedTo] = useState<string | null>(null)
  useEffect(() => {
    if (!showCopyMenu) return
    function close(e: MouseEvent) {
      if (
        !copyMenuRef.current?.contains(e.target as Node) &&
        !copyBtnRef.current?.contains(e.target as Node)
      ) setShowCopyMenu(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [showCopyMenu])

  function openCopyMenu() {
    const rect = copyBtnRef.current?.getBoundingClientRect()
    if (rect) setCopyMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
    setShowCopyMenu((s) => !s)
  }

  function handleCopyToTab(tabId: string, tabLabel: string) {
    copyToTab(withLockedTheme(widget), tabId)
    setShowCopyMenu(false)
    setCopiedTo(tabLabel)
    setTimeout(() => setCopiedTo(null), 1800)
  }

  function handleCollapse() {
    if (!isCollapsed) {
      // Shrink to header-only: save current h, set h=2 minH=1
      const currentH = widget.layout?.h ?? 8
      onUpdate?.({
        ...widget,
        prevH: currentH,
        layout: widget.layout ? { ...widget.layout, h: 2, minH: 1 } : widget.layout,
      })
    } else {
      // Restore previous height
      onUpdate?.({
        ...widget,
        prevH: undefined,
        layout: widget.layout ? { ...widget.layout, h: widget.prevH ?? 8, minH: 3 } : widget.layout,
      })
    }
  }

  async function handleRefine() {
    if (!nlInput.trim() || !hasSql || refining) return
    setRefining(true)
    setRefineError(null)
    try {
      const result = await refineWidget(widget.sql, nlInput.trim())
      onUpdate?.({ ...widget, ...result, id: widget.id, layout: widget.layout, prevH: widget.prevH })
      setNlInput('')
      setShowSql(false)
    } catch (e) {
      setRefineError(e instanceof Error ? e.message : 'Refinement failed')
    } finally {
      setRefining(false)
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(widget.sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="h-full flex flex-col bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className={`drag-handle flex items-center justify-between px-4 py-2.5 ${headerBg} border-b ${headerBorder} border-l-4 ${style.border} cursor-grab active:cursor-grabbing select-none flex-shrink-0`}>
        <div className="flex items-center gap-2 min-w-0">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide flex-shrink-0 ${TAB_BADGE[badgePrefix] ?? TAB_BADGE.My}`}>
            {badgePrefix}
          </span>
          {editingTitle ? (
            <input
              autoFocus
              value={titleInput}
              onChange={(e) => setTitleInput(e.target.value)}
              onBlur={commitTitleRename}
              onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Enter') commitTitleRename(); if (e.key === 'Escape') setEditingTitle(false) }}
              onMouseDown={(e) => e.stopPropagation()}
              className="text-sm font-semibold text-slate-700 bg-white border border-brand-300 rounded px-1.5 py-0.5 outline-none focus:ring-1 focus:ring-brand-400 min-w-0 w-40"
            />
          ) : (
            <div className="flex items-center gap-1 group/title min-w-0">
              <h3 className="text-sm font-semibold text-slate-700 truncate" onDoubleClick={startTitleEdit}>{widget.title}</h3>
              <button onMouseDown={noDrag} onClick={startTitleEdit} title="Rename widget"
                className="flex-shrink-0 p-0.5 text-slate-300 hover:text-brand-600 rounded opacity-0 group-hover/title:opacity-100 transition-opacity">
                <Pencil size={10} />
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center gap-0.5 flex-shrink-0">
          {targets.length > 0 && (
            <>
              {/* Move to tab */}
              <button
                ref={sendBtnRef}
                title="Move to tab"
                onMouseDown={noDrag}
                onClick={openSendMenu}
                className="p-1.5 text-slate-400 hover:text-brand-600 transition-colors rounded"
              >
                <CornerUpRight size={13} />
              </button>
              {showSendMenu && menuPos && createPortal(
                <div
                  ref={sendMenuRef}
                  style={{ position: 'fixed', top: menuPos.top, right: menuPos.right, zIndex: 9999 }}
                  className="bg-white border border-gray-200 rounded-lg shadow-xl py-1 min-w-36"
                >
                  <p className="text-[10px] text-gray-400 px-3 py-1 font-semibold uppercase tracking-wide">Move to tab</p>
                  {targets.map((t) => (
                    <button
                      key={t.id}
                      onMouseDown={noDrag}
                      onClick={() => { sendToTab(withLockedTheme(widget), t.id); onRemove(widget.id); setShowSendMenu(false) }}
                      className="w-full text-left text-xs text-gray-700 hover:bg-brand-50 hover:text-brand-700 px-3 py-1.5 transition-colors"
                    >
                      {t.label}
                    </button>
                  ))}
                </div>,
                document.body
              )}

              {/* Copy to tab */}
              <button
                ref={copyBtnRef}
                title={copiedTo ? `Copied to ${copiedTo}` : 'Copy to tab'}
                onMouseDown={noDrag}
                onClick={openCopyMenu}
                className={`p-1.5 transition-colors rounded ${copiedTo ? 'text-emerald-500' : 'text-slate-400 hover:text-emerald-600'}`}
              >
                <CopyPlus size={13} />
              </button>
              {showCopyMenu && copyMenuPos && createPortal(
                <div
                  ref={copyMenuRef}
                  style={{ position: 'fixed', top: copyMenuPos.top, right: copyMenuPos.right, zIndex: 9999 }}
                  className="bg-white border border-gray-200 rounded-lg shadow-xl py-1 min-w-36"
                >
                  <p className="text-[10px] text-gray-400 px-3 py-1 font-semibold uppercase tracking-wide">Copy to tab</p>
                  {targets.map((t) => (
                    <button
                      key={t.id}
                      onMouseDown={noDrag}
                      onClick={() => handleCopyToTab(t.id, t.label)}
                      className="w-full text-left text-xs text-gray-700 hover:bg-emerald-50 hover:text-emerald-700 px-3 py-1.5 transition-colors"
                    >
                      {t.label}
                    </button>
                  ))}
                </div>,
                document.body
              )}
            </>
          )}

          {!isAirflow && (
            <button
              title={isFavorited ? 'Remove from favorites' : 'Add to favorites'}
              onMouseDown={noDrag}
              onClick={onFavoriteToggle}
              disabled={isFavoritePending}
              className={`p-1.5 transition-colors rounded disabled:opacity-60 ${isFavorited ? 'text-red-500 hover:text-red-600' : 'text-slate-400 hover:text-red-400'}`}
            >
              {isFavoritePending
                ? <Loader2 size={13} className="animate-spin text-slate-400" />
                : <Star size={13} fill={isFavorited ? 'currentColor' : 'none'} />}
            </button>
          )}

          {!isAirflow && (
            <button
              title={showData ? 'Show chart' : 'Show raw data'}
              onMouseDown={noDrag}
              onClick={() => { setShowData((s) => !s); setShowSql(false) }}
              className={`p-1.5 transition-colors rounded ${showData ? 'text-blue-600 bg-blue-50' : 'text-slate-400 hover:text-blue-500'}`}
            >
              <Maximize2 size={13} />
            </button>
          )}

          {!isAirflow && (
            <button
              title={showSql ? 'Hide SQL' : 'View / refine SQL'}
              onMouseDown={noDrag}
              onClick={() => { setShowSql((s) => !s); setShowData(false); setRefineError(null) }}
              className={`p-1.5 transition-colors rounded ${showSql ? 'text-violet-600 bg-violet-50' : 'text-slate-400 hover:text-violet-500'}`}
            >
              <Code2 size={13} />
            </button>
          )}

          {hasSql && widget.chart_type !== 'kpi' && (
            <button
              title={widget.live ? 'Stop live updates' : 'Enable live updates for this widget'}
              onMouseDown={noDrag}
              onClick={() => onUpdate?.({ ...widget, live: !widget.live })}
              className={`p-1.5 transition-colors rounded ${widget.live ? 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100' : 'text-slate-400 hover:text-emerald-500'}`}
            >
              {widget.live ? <WifiOff size={13} /> : <Wifi size={13} />}
            </button>
          )}

          {isAirflow && (
            <>
              {airflowLiveStatus !== 'off' && <LiveBadge status={airflowLiveStatus} />}
              <button
                title={widget.live ? 'Stop live updates' : 'Start live updates'}
                onMouseDown={noDrag}
                onClick={() => onUpdate?.({ ...widget, live: !widget.live })}
                className={`p-1.5 transition-colors rounded ${widget.live ? 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100' : 'text-slate-400 hover:text-emerald-500'}`}
              >
                {widget.live ? <WifiOff size={13} /> : <Wifi size={13} />}
              </button>
              <button
                title="Refresh DAG status"
                onMouseDown={noDrag}
                onClick={() => airflowRefreshRef.current?.()}
                className="p-1.5 text-slate-400 hover:text-slate-600 transition-colors rounded"
              >
                <RefreshCw size={13} />
              </button>
            </>
          )}

          {hasSql && widget.chart_type !== 'kpi' && (
            <button
              title={widget.live ? 'Stop live updates' : 'Enable live updates for this widget'}
              onMouseDown={noDrag}
              onClick={() => onUpdate?.({ ...widget, live: !widget.live })}
              className={`p-1.5 transition-colors rounded ${widget.live ? 'text-emerald-600 bg-emerald-50 hover:bg-emerald-100' : 'text-slate-400 hover:text-emerald-500'}`}
            >
              {widget.live ? <WifiOff size={13} /> : <Wifi size={13} />}
            </button>
          )}

          <button
            title={isCollapsed ? 'Expand widget' : 'Collapse widget'}
            onMouseDown={noDrag}
            onClick={handleCollapse}
            className="p-1.5 text-slate-400 hover:text-slate-600 transition-colors rounded"
          >
            {isCollapsed ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          </button>

          <button
            title={isAwayFromHome ? 'Return to original tab' : 'Remove widget'}
            onMouseDown={noDrag}
            onClick={handleRemove}
            className={`p-1.5 transition-colors rounded ${isAwayFromHome ? 'text-brand-400 hover:text-brand-700' : 'text-slate-400 hover:text-red-500'}`}
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* Body — hidden when collapsed (widget physically shrinks via layout h change) */}
      {!isCollapsed && (
        <>
          {widget.error ? (
            <div className="flex-1 flex flex-col min-h-0 overflow-auto">
              <div className="m-3 flex items-start gap-2.5 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg">
                <AlertCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-red-700 uppercase tracking-wide">Data Unavailable</p>
                  <p className="text-[11px] text-red-500 mt-1">Failed to load widget data. Check your data access or query configuration.</p>
                </div>
              </div>
            </div>
          ) : (
            <>
              {widget.ai_description && !isAirflow && (
                <div className="px-4 py-2 bg-slate-50 border-b border-slate-100 flex-shrink-0">
                  <p className="text-[11px] text-slate-500 leading-relaxed">{widget.ai_description}</p>
                </div>
              )}

          {isAirflow && (
            <div className="flex-1 overflow-auto min-h-0 p-3">
              <AirflowSection
                live={widget.live ?? false}
                onLiveStatusChange={handleAirflowLiveStatus}
                onRegisterRefresh={handleRegisterRefresh}
                airflowEnvOverride={widget.lockedAirflowEnv}
              />
            </div>
          )}

          {!isAirflow && !showSql && (
            <div className="flex-1 overflow-auto p-3 min-h-0">
              {showData ? (
                <DataTable data={widget.data} />
              ) : (
                <ChartRenderer
                  chart_type={widget.chart_type}
                  data={widget.data}
                  x_axis={widget.x_axis}
                  y_axis={widget.y_axis}
                  color_field={widget.color_field}
                  stacked={widget.stacked}
                  dual_axis={widget.dual_axis}
                  secondary_y={widget.secondary_y}
                  height={220}
                />
              )}
            </div>
          )}

          {/* SQL panel */}
          {!isAirflow && showSql && (
            <div className="flex-1 min-h-0 flex flex-col overflow-hidden border-t border-violet-100">
              <div className="flex items-center justify-between px-3 py-1.5 bg-violet-50 border-b border-violet-100 flex-shrink-0">
                <span className="text-[10px] font-semibold text-violet-700 uppercase tracking-wide">SQL Query</span>
                {hasSql && (
                  <button onClick={handleCopy} className="text-[10px] text-violet-500 hover:text-violet-700 transition-colors">
                    {copied ? '✓ Copied' : 'Copy'}
                  </button>
                )}
              </div>

              {hasSql ? (
                <>
                  <pre className="flex-1 text-[11px] font-mono text-slate-700 px-3 py-2.5 overflow-auto whitespace-pre bg-slate-50">
                    {widget.sql}
                  </pre>
                  <div className="flex-shrink-0 border-t border-violet-100 bg-white px-3 py-2.5 flex flex-col gap-2">
                    <div className="flex items-start gap-2">
                      <Sparkles size={13} className="text-violet-400 mt-2 flex-shrink-0" />
                      <textarea
                        rows={2}
                        value={nlInput}
                        onChange={(e) => setNlInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleRefine() } }}
                        placeholder='Describe what to change… e.g. "filter to Capital only" or "add % of total column"'
                        className="flex-1 text-xs text-gray-800 placeholder-gray-400 border border-gray-200 rounded-lg px-2.5 py-1.5 resize-none outline-none focus:ring-1 focus:ring-violet-300 focus:border-violet-300"
                      />
                      <button
                        onClick={handleRefine}
                        disabled={!nlInput.trim() || refining}
                        className="flex-shrink-0 flex items-center gap-1.5 text-xs bg-violet-600 hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-lg transition-colors"
                      >
                        {refining ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                        {refining ? 'Refining…' : 'Refine'}
                      </button>
                    </div>
                    {refineError && <p className="text-[11px] text-red-600 pl-5">{refineError}</p>}
                  </div>
                </>
              ) : (
                <div className="flex-1 flex items-center justify-center px-4">
                  <p className="text-xs text-slate-400 text-center">
                    SQL not available for built-in scorecard widgets.<br />
                    AI-generated charts will show their query here.
                  </p>
                </div>
              )}
            </div>
          )}
            </>
          )}
        </>
      )}
    </div>
  )
}
