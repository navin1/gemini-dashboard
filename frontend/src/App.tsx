import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { LayoutDashboard, Users, GitBranch, Sparkles, Star, BookOpen, Plus, X as XIcon, Pencil, Wind } from 'lucide-react'
import { Header } from './components/Header/Header'
import { UATDashboardTab } from './tabs/UATDashboardTab'
import { PRDDashboardTab } from './tabs/PRDDashboardTab'
import { DEVDashboardTab } from './tabs/DEVDashboardTab'
import { MyDashboardTab } from './tabs/MyDashboardTab'
import { FavoritesTab } from './tabs/FavoritesTab'
import { GlossaryTab } from './tabs/GlossaryTab'
import { ChatPanel } from './components/Chat/ChatPanel'
import { AuthProvider } from './context/AuthContext'
import { WidgetTransferProvider } from './context/WidgetTransferContext'
import { fetchFTEScorecard, fetchVendorScorecard, fetchHierarchyScorecard } from './api/scorecard'
import DagDetailTab from './components/Airflow/DagDetailTab'
import SqlTab from './components/Airflow/SqlTab'
import type { ChatWidgetDef } from './api/chat'
import type { Widget, AirflowTab } from './types'
import clsx from 'clsx'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1 } } })

// Kick off all three scorecard fetches immediately so tabs load instantly
qc.prefetchQuery({ queryKey: ['scorecard', 'uat'], queryFn: fetchFTEScorecard })
qc.prefetchQuery({ queryKey: ['scorecard', 'prd'], queryFn: fetchVendorScorecard })
qc.prefetchQuery({ queryKey: ['scorecard', 'dev'], queryFn: fetchHierarchyScorecard })

// ── Fixed tabs (always present, not closeable) ────────────────────────────────
const FIXED_TABS = [
  { id: 'my',        label: 'My Dashboard',   icon: Sparkles,        badge: 'Dynamic'   },
  { id: 'prd', label: 'PRD Dashboard', icon: Users,           badge: 'Scorecard' },
  { id: 'uat', label: 'UAT Dashboard', icon: LayoutDashboard, badge: 'Scorecard' },
  { id: 'dev', label: 'DEV Dashboard', icon: GitBranch,       badge: 'Scorecard' },
  { id: 'favorites', label: 'Favorites',      icon: Star,            badge: 'Saved'     },
  { id: 'glossary',  label: 'Glossary',       icon: BookOpen,        badge: 'Reference' },
] as const

const TAB_ORDER_VERSION = 3

function envToPrefix(env: string): string {
  const map: Record<string, string> = { UAT: 'UAT', PROD: 'PRD', Dev: 'DEV' }
  return map[env] ?? env
}

type FixedTabId = typeof FIXED_TABS[number]['id']

interface CustomTab {
  id: string
  label: string
}

function loadCustomTabs(): CustomTab[] {
  try {
    const raw = localStorage.getItem('custom_tabs')
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveCustomTabs(tabs: CustomTab[]) {
  localStorage.setItem('custom_tabs', JSON.stringify(tabs))
}

const FIXED_IDS = FIXED_TABS.map((t) => t.id)

function loadTabOrder(customIds: string[]): string[] {
  const allIds = [...FIXED_IDS, ...customIds]
  try {
    const version = parseInt(localStorage.getItem('tab_order_version') || '1')
    if (version < TAB_ORDER_VERSION) {
      localStorage.removeItem('tab_order')
      localStorage.setItem('tab_order_version', String(TAB_ORDER_VERSION))
      return allIds
    }
    const raw: string[] = JSON.parse(localStorage.getItem('tab_order') || '[]')
    // Migrate old tab IDs in stored order
    const migrated = raw.map(id => id === 'fte' ? 'uat' : id === 'vendor' ? 'prd' : id === 'hierarchy' ? 'dev' : id)
    const valid = migrated.filter((id) => allIds.includes(id))
    const missing = allIds.filter((id) => !valid.includes(id))
    return [...valid, ...missing]
  } catch {
    return allIds
  }
}

function saveTabOrder(order: string[]) {
  localStorage.setItem('tab_order', JSON.stringify(order))
}

let _tabSeq = 0

// ── Per-custom-tab widget registry ───────────────────────────────────────────
// MyDashboardTab receives an onAddExternalWidget ref so the chat can push widgets into it.
// We store these callbacks by tab id.
const _addWidgetCallbacks: Record<string, ((w: Widget) => void)> = {}

function registerAddWidget(tabId: string, fn: (w: Widget) => void) {
  _addWidgetCallbacks[tabId] = fn
}

// Module-level ref for chat SQL injection (set by ChatPanel, called by SqlTab)
let _injectSqlToChat: ((sql: string) => void) | null = null

// ── Content router ────────────────────────────────────────────────────────────
function TabContent({
  tabId, tabLabel, registerCb,
  airflowTabs, onOpenDagTab, onOpenSqlTab,
}: {
  tabId: string
  tabLabel: string
  registerCb: (fn: (w: Widget) => void) => void
  airflowTabs: AirflowTab[]
  onOpenDagTab: (dagId: string, env: string) => void
  onOpenSqlTab: (dagId: string, taskId: string, env: string, runId?: string, operatorFull?: string) => void
}) {
  const airflowTab = airflowTabs.find(t => t.id === tabId)

  if (airflowTab?.type === 'airflow_dag') {
    return (
      <DagDetailTab
        dagId={airflowTab.dagId}
        env={airflowTab.env}
        onOpenSqlTab={onOpenSqlTab}
      />
    )
  }

  if (airflowTab?.type === 'airflow_sql') {
    return (
      <SqlTab
        dagId={airflowTab.dagId}
        taskId={airflowTab.taskId!}
        env={airflowTab.env}
        runId={airflowTab.runId}
        operatorFull={airflowTab.operatorFull}
        onAnalyzeWithGemini={(sql) => {
          if (_injectSqlToChat) _injectSqlToChat(sql)
        }}
      />
    )
  }

  switch (tabId as FixedTabId) {
    case 'uat':
      return <UATDashboardTab tabLabel={tabLabel} onRegisterAddWidget={registerCb} onOpenDagTab={onOpenDagTab} />
    case 'prd':
      return <PRDDashboardTab tabLabel={tabLabel} onRegisterAddWidget={registerCb} onOpenDagTab={onOpenDagTab} />
    case 'dev':
      return <DEVDashboardTab tabLabel={tabLabel} onRegisterAddWidget={registerCb} onOpenDagTab={onOpenDagTab} />
    case 'favorites': return <FavoritesTab />
    case 'glossary':  return <GlossaryTab />
    default:
      return <MyDashboardTab key={tabId} tabId={tabId} tabLabel={tabLabel} onRegisterAddWidget={registerCb} />
  }
}


export default function App() {
  const [activeTabId, setActiveTabId] = useState<string>('my')
  const [customTabs, setCustomTabs] = useState<CustomTab[]>(loadCustomTabs)

  // Inline rename state
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  // Tab order (fixed + custom, persisted)
  const [tabOrder, setTabOrder] = useState<string[]>(() =>
    loadTabOrder(loadCustomTabs().map((t) => t.id))
  )
  const [dragId, setDragId] = useState<string | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)

  // Ephemeral Airflow tabs (not persisted to localStorage)
  const [airflowTabs, setAirflowTabs] = useState<AirflowTab[]>([])

  // Fixed tab label overrides (editable, persisted)
  const [fixedTabLabels, setFixedTabLabels] = useState<Record<string, string>>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('fixed_tab_labels') || '{}')
      // Migrate old default names → new defaults so renames are transparent
      if (stored['ai'] !== undefined) { stored['my'] = stored['ai']; delete stored['ai'] }
      if (stored['my'] === 'AI Dashboard' || stored['my'] === 'My Dashboard') delete stored['my']
      // Migrate old tab IDs (fte→uat, vendor→prd, hierarchy→dev) — move any custom labels across
      for (const [oldId, newId] of [['fte', 'uat'], ['vendor', 'prd'], ['hierarchy', 'dev']] as const) {
        if (stored[oldId] !== undefined) { stored[newId] = stored[oldId]; delete stored[oldId] }
      }
      if (stored['uat'] === 'FTE Hierarchy' || stored['uat'] === 'UAT Dashboard') delete stored['uat']
      if (stored['prd'] === 'Vendor Summary' || stored['prd'] === 'PRD Dashboard') delete stored['prd']
      if (stored['dev'] === 'Hierarchy Summary' || stored['dev'] === 'DEV Dashboard') delete stored['dev']
      return stored
    } catch { return {} }
  })

  useEffect(() => {
    if (renamingId) setTimeout(() => renameInputRef.current?.focus(), 50)
  }, [renamingId])

  // Keep tabOrder in sync when custom tabs are added or removed
  useEffect(() => {
    setTabOrder((prev) => {
      const allIds = [...FIXED_IDS, ...customTabs.map((t) => t.id)]
      const valid = prev.filter((id) => allIds.includes(id))
      const missing = allIds.filter((id) => !valid.includes(id))
      const next = [...valid, ...missing]
      saveTabOrder(next)
      return next
    })
  }, [customTabs])

  function addTab() {
    const label = `Dashboard ${++_tabSeq}`
    const id = `custom_${Date.now()}`
    const next = [...customTabs, { id, label }]
    setCustomTabs(next)
    saveCustomTabs(next)
    setActiveTabId(id)
  }

  function removeTab(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    const next = customTabs.filter((t) => t.id !== id)
    setCustomTabs(next)
    saveCustomTabs(next)
    delete _addWidgetCallbacks[id]
    if (activeTabId === id) {
      setActiveTabId(next.length > 0 ? next[next.length - 1].id : 'my')
    }
  }

  function handleDragStart(e: React.DragEvent, id: string) {
    setDragId(id)
    e.dataTransfer.effectAllowed = 'move'
  }

  function handleDragOver(e: React.DragEvent, id: string) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (id !== dragId) setDragOverId(id)
  }

  function handleDrop(e: React.DragEvent, targetId: string) {
    e.preventDefault()
    if (!dragId || dragId === targetId) { setDragId(null); setDragOverId(null); return }
    setTabOrder((prev) => {
      const next = [...prev]
      const from = next.indexOf(dragId)
      const to = next.indexOf(targetId)
      if (from === -1 || to === -1) return prev
      next.splice(from, 1)
      next.splice(to, 0, dragId)
      saveTabOrder(next)
      return next
    })
    setDragId(null)
    setDragOverId(null)
  }

  function handleDragEnd() { setDragId(null); setDragOverId(null) }

  function openAirflowDagTab(dagId: string, env: string) {
    const id = `airflow_dag_${dagId}_${env}`
    if (airflowTabs.some(t => t.id === id)) { setActiveTabId(id); return }
    const prefix = envToPrefix(env)
    const tab: AirflowTab = { id, label: `[${prefix}] ${dagId}`, type: 'airflow_dag', dagId, env }
    setAirflowTabs(prev => [...prev, tab])
    setTabOrder(prev => { const next = [...prev, id]; saveTabOrder(next); return next })
    setActiveTabId(id)
  }

  function openAirflowSqlTab(dagId: string, taskId: string, env: string, runId?: string, operatorFull?: string) {
    const id = `airflow_sql_${dagId}_${taskId}_${env}`
    if (airflowTabs.some(t => t.id === id)) { setActiveTabId(id); return }
    const prefix = envToPrefix(env)
    const tab: AirflowTab = { id, label: `[${prefix}] ${taskId} | SQL`, type: 'airflow_sql', dagId, env, runId, taskId, operatorFull }
    setAirflowTabs(prev => [...prev, tab])
    setTabOrder(prev => { const next = [...prev, id]; saveTabOrder(next); return next })
    setActiveTabId(id)
  }

  function closeAirflowTab(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setAirflowTabs(prev => prev.filter(t => t.id !== id))
    setTabOrder(prev => { const next = prev.filter(tid => tid !== id); saveTabOrder(next); return next })
    if (activeTabId === id) setActiveTabId('uat')
  }

  function startRename(tab: { id: string; label: string }, e: React.MouseEvent) {
    e.stopPropagation()
    setRenamingId(tab.id)
    setRenameValue(tab.label)
  }

  function commitRename(id: string) {
    if (!renameValue.trim()) { setRenamingId(null); return }
    if ((FIXED_IDS as readonly string[]).includes(id)) {
      const next = { ...fixedTabLabels, [id]: renameValue.trim() }
      setFixedTabLabels(next)
      localStorage.setItem('fixed_tab_labels', JSON.stringify(next))
    } else {
      const next = customTabs.map((t) => t.id === id ? { ...t, label: renameValue.trim() } : t)
      setCustomTabs(next)
      saveCustomTabs(next)
    }
    setRenamingId(null)
  }

  // Copy a widget to another tab — original stays, copy gets a new ID; live resets on destination
  const copyWidgetToTab = useCallback((widget: Widget, tabId: string) => {
    const copy: Widget = { ...widget, id: `copy_${Date.now()}`, homeTabId: undefined, live: false }
    _addWidgetCallbacks[tabId]?.(copy)
  }, [])

  // Send a widget to any tab (used by "Move to tab" and "return home on remove"); live resets on destination
  const sendWidgetToTab = useCallback((widget: Widget, tabId: string) => {
    const returningHome = widget.homeTabId === tabId
    const widgetToSend = returningHome
      ? { ...widget, homeTabId: undefined, live: false }
      : { ...widget, homeTabId: widget.homeTabId ?? activeTabId, live: false }
    // All tabs are always mounted, so callbacks are always live
    _addWidgetCallbacks[tabId]?.(widgetToSend)
    setActiveTabId(tabId)
  }, [activeTabId])

  // Targets for WidgetTransferProvider: AI tab + all custom tabs
  const transferTargets = useMemo(
    () => [
      { id: 'my', label: fixedTabLabels['my'] || 'My Dashboard' },
      ...customTabs.map((t) => ({ id: t.id, label: t.label })),
    ],
    [customTabs, fixedTabLabels]
  )

  // When chat generates a widget, push it into the active AI tab (if applicable)
  const handleChatAddWidget = useCallback((chatWidget: ChatWidgetDef) => {
    const widget: Widget = {
      id: `chat_${Date.now()}`,
      title: chatWidget.title,
      chart_type: chatWidget.chart_type as Widget['chart_type'],
      x_axis: chatWidget.x_axis,
      y_axis: chatWidget.y_axis,
      color_field: chatWidget.color_field,
      stacked: chatWidget.stacked,
      dual_axis: chatWidget.dual_axis,
      secondary_y: chatWidget.secondary_y,
      ai_description: chatWidget.ai_description,
      sql: chatWidget.sql,
      data: chatWidget.data,
    }
    const cb = _addWidgetCallbacks[activeTabId]
    if (cb) {
      cb(widget)
    } else {
      _addWidgetCallbacks['my']?.(widget)
      setActiveTabId('my')
    }
  }, [activeTabId])

  return (
    <GoogleOAuthProvider clientId={import.meta.env.VITE_GOOGLE_CLIENT_ID ?? ''}>
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <WidgetTransferProvider value={{ targets: transferTargets, sendToTab: sendWidgetToTab, copyToTab: copyWidgetToTab, currentTabId: activeTabId }}>
        <div className="h-screen flex flex-col bg-gray-50 font-sans overflow-hidden">
          <Header
            title="EDA OSR Helper"
            subtitle="Interactive Agent"
          />

          {/* ── Tab bar ─────────────────────────────────────────────────── */}
          <div className="bg-white border-b border-gray-200 px-3 flex items-end gap-0.5 overflow-x-auto">
            {tabOrder.map((id) => {
              const fixed    = FIXED_TABS.find((t) => t.id === id)
              const custom   = customTabs.find((t) => t.id === id)
              const airflow  = airflowTabs.find((t) => t.id === id)
              if (!fixed && !custom && !airflow) return null
              const isActive     = id === activeTabId
              const isDropTarget = dragOverId === id
              const isDragging   = dragId === id

              // Airflow tab rendering
              if (airflow) {
                return (
                  <div
                    key={id}
                    onClick={() => setActiveTabId(id)}
                    className={clsx(
                      'group flex items-center gap-1 px-3 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex-shrink-0 cursor-pointer',
                      isActive ? 'border-brand-600 text-brand-700 bg-brand-50' : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50',
                    )}
                  >
                    <Wind size={13} className={isActive ? 'text-brand-600' : 'text-gray-400'} />
                    <span className="max-w-[160px] truncate" title={airflow.label}>{airflow.label}</span>
                    <button
                      onClick={(e) => closeAirflowTab(id, e)}
                      className="p-0.5 text-gray-400 hover:text-red-500 rounded ml-1 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Close tab"
                    >
                      <XIcon size={11} />
                    </button>
                  </div>
                )
              }

              if (fixed) {
                const Icon = fixed.icon
                const displayLabel = fixedTabLabels[id] || fixed.label
                return (
                  <div
                    key={id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, id)}
                    onDragOver={(e) => handleDragOver(e, id)}
                    onDrop={(e) => handleDrop(e, id)}
                    onDragEnd={handleDragEnd}
                    onClick={() => setActiveTabId(id)}
                    className={clsx(
                      'group flex items-center gap-1.5 px-3.5 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex-shrink-0 cursor-grab active:cursor-grabbing',
                      isActive ? 'border-brand-600 text-brand-700 bg-brand-50' : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50',
                      isDragging && 'opacity-40',
                      isDropTarget && !isDragging && 'border-l-2 border-l-brand-400',
                    )}
                  >
                    <Icon size={14} />
                    {renamingId === id ? (
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={() => commitRename(id)}
                        onKeyDown={(e) => {
                          e.stopPropagation()
                          if (e.key === 'Enter') commitRename(id)
                          if (e.key === 'Escape') setRenamingId(null)
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-28 text-sm bg-white border border-brand-300 rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-brand-400"
                      />
                    ) : (
                      <span onDoubleClick={(e) => startRename({ id, label: displayLabel }, e)} title="Double-click to rename">
                        {displayLabel}
                      </span>
                    )}
                    <span className={clsx('text-[10px] px-1.5 py-0.5 rounded hidden sm:inline', isActive ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-400')}>
                      {fixed.badge}
                    </span>
                    {renamingId !== id && (
                      <button
                        onClick={(e) => { e.stopPropagation(); startRename({ id, label: displayLabel }, e) }}
                        className="p-0.5 text-gray-400 hover:text-brand-600 rounded hidden group-hover:inline-flex"
                        title="Rename tab"
                      >
                        <Pencil size={11} />
                      </button>
                    )}
                  </div>
                )
              }

              // Custom tab
              const t = custom!
              return (
                <div
                  key={id}
                  draggable
                  onDragStart={(e) => handleDragStart(e, id)}
                  onDragOver={(e) => handleDragOver(e, id)}
                  onDrop={(e) => handleDrop(e, id)}
                  onDragEnd={handleDragEnd}
                  onClick={() => setActiveTabId(id)}
                  className={clsx(
                    'group flex items-center gap-1 px-3 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap cursor-grab active:cursor-grabbing flex-shrink-0',
                    isActive ? 'border-brand-600 text-brand-700 bg-brand-50' : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50',
                    isDragging && 'opacity-40',
                    isDropTarget && !isDragging && 'border-l-2 border-l-brand-400',
                  )}
                >
                  <Sparkles size={13} className={isActive ? 'text-brand-600' : 'text-gray-400'} />

                  {renamingId === t.id ? (
                    <input
                      ref={renameInputRef}
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => commitRename(t.id)}
                      onKeyDown={(e) => {
                        e.stopPropagation()
                        if (e.key === 'Enter') commitRename(t.id)
                        if (e.key === 'Escape') setRenamingId(null)
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="w-28 text-sm bg-white border border-brand-300 rounded px-1 py-0.5 outline-none focus:ring-1 focus:ring-brand-400"
                    />
                  ) : (
                    <span onDoubleClick={(e) => startRename(t, e)} title="Double-click to rename">
                      {t.label}
                    </span>
                  )}

                  <span className="hidden group-hover:flex items-center gap-0.5 ml-1">
                    {renamingId !== t.id && (
                      <button
                        onClick={(e) => startRename(t, e)}
                        className="p-0.5 text-gray-400 hover:text-brand-600 rounded"
                        title="Rename tab"
                      >
                        <Pencil size={11} />
                      </button>
                    )}
                    <button
                      onClick={(e) => removeTab(t.id, e)}
                      className="p-0.5 text-gray-400 hover:text-red-500 rounded"
                      title="Close tab"
                    >
                      <XIcon size={11} />
                    </button>
                  </span>
                </div>
              )
            })}

            {/* Add tab button */}
            <button
              onClick={addTab}
              title="Add new dashboard tab"
              className="flex items-center gap-1 px-2.5 py-2.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 border-b-2 border-transparent transition-colors flex-shrink-0 ml-1"
            >
              <Plus size={15} />
              <span className="text-xs hidden sm:inline">New Tab</span>
            </button>
          </div>

          {/* ── Content — all tabs always mounted; inactive hidden via CSS ── */}
          <main className="flex-1 min-h-0 overflow-auto pb-14">
            {tabOrder.map((id) => {
              const fixed   = FIXED_TABS.find((t) => t.id === id)
              const custom  = customTabs.find((t) => t.id === id)
              const airflow = airflowTabs.find((t) => t.id === id)
              if (!fixed && !custom && !airflow) return null
              const tabLabel = fixedTabLabels[id] || fixed?.label || custom?.label || airflow?.label || id
              return (
                <div key={id} className="h-full" style={id === activeTabId ? undefined : { display: 'none' }}>
                  <TabContent
                    tabId={id}
                    tabLabel={tabLabel}
                    registerCb={(fn) => registerAddWidget(id, fn)}
                    airflowTabs={airflowTabs}
                    onOpenDagTab={openAirflowDagTab}
                    onOpenSqlTab={openAirflowSqlTab}
                  />
                </div>
              )
            })}
          </main>

          {/* ── Floating chat panel ──────────────────────────────────────── */}
          <ChatPanel
            onAddWidget={handleChatAddWidget}
            onRegisterInject={(fn) => { _injectSqlToChat = fn }}
          />
        </div>
        </WidgetTransferProvider>
      </AuthProvider>
    </QueryClientProvider>
    </GoogleOAuthProvider>
  )
}
