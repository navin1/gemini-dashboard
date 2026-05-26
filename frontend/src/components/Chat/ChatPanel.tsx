import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, Sparkles, Plus, RotateCcw, ChevronDown, ChevronUp, Mic, MicOff } from 'lucide-react'
import { streamChatMessage, runSqlQuery, type ChatMessage, type ChatWidgetDef } from '../../api/chat'
import { ChartRenderer } from '../Charts/ChartRenderer'
import type { ChartType } from '../../types'

interface InternalMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  widget?: ChatWidgetDef
  loading?: boolean
  statusText?: string
  suggested_questions?: string[]
}

interface Props {
  onAddWidget?: (widget: ChatWidgetDef) => void
}

let _mid = 0
const mid = () => `m_${++_mid}`

const STARTERS = [
  'Total YTD spend by vendor?',
  'Capital vs expense trend over the year',
  'Top resource managers by headcount',
  'Donut chart of bill type split',
  'What does FTP mean?',
]

const EXPANDED_HEIGHT = 440

const SQL_RE = /^\s*(SELECT|WITH|EXPLAIN)\s/i
function isSql(text: string) { return SQL_RE.test(text) }

// Web Speech API types
const SpeechRecognition =
  (window as unknown as { SpeechRecognition?: new () => SpeechRecognition; webkitSpeechRecognition?: new () => SpeechRecognition }).SpeechRecognition ||
  (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognition }).webkitSpeechRecognition

interface SpeechRecognition extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  start(): void
  stop(): void
  onresult: ((e: SpeechRecognitionEvent) => void) | null
  onerror: ((e: Event) => void) | null
  onend: (() => void) | null
}
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList
}
interface SpeechRecognitionResultList {
  readonly length: number
  item(index: number): SpeechRecognitionResult
  [index: number]: SpeechRecognitionResult
}
interface SpeechRecognitionResult {
  readonly length: number
  item(index: number): SpeechRecognitionAlternative
  [index: number]: SpeechRecognitionAlternative
}
interface SpeechRecognitionAlternative {
  transcript: string
}

export function ChatPanel({ onAddWidget }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [messages, setMessages] = useState<InternalMessage[]>([
    { id: mid(), role: 'assistant', text: "Hi! I'm your AI analyst. Ask me anything about your workforce and spend data — I can answer questions, explain metrics, or generate charts." },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [geminiUnavailable, setGeminiUnavailable] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => { if (d.gemini === false) setGeminiUnavailable(true) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (expanded) {
      setTimeout(() => inputRef.current?.focus(), 150)
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [expanded])

  useEffect(() => {
    if (expanded) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, expanded])

  const buildHistory = useCallback((): ChatMessage[] =>
    messages.filter((m) => !m.loading).map((m) => ({ role: m.role, content: m.text })),
    [messages]
  )

  async function sendMessage(text: string) {
    if (!text || loading) return
    setInput('')
    setExpanded(true)

    const userMsg: InternalMessage = { id: mid(), role: 'user', text }
    const loadingMsg: InternalMessage = { id: mid(), role: 'assistant', text: '', loading: true, statusText: 'Starting…' }
    setMessages((prev) => [...prev, userMsg, loadingMsg])
    setLoading(true)

    try {
      if (isSql(text)) {
        const resp = await runSqlQuery(text)
        setMessages((prev) =>
          prev.map((m) => m.loading
            ? { ...m, loading: false, text: resp.text, widget: resp.widget, suggested_questions: resp.suggested_questions }
            : m
          )
        )
        return
      }

      for await (const event of streamChatMessage(text, buildHistory())) {
        if (event.type === 'status') {
          setMessages((prev) =>
            prev.map((m) => m.loading ? { ...m, statusText: event.message } : m)
          )
        } else if (event.type === 'result') {
          const resp = event.data
          setMessages((prev) =>
            prev.map((m) => m.loading
              ? { ...m, loading: false, statusText: undefined, text: resp.text, widget: resp.widget, suggested_questions: resp.suggested_questions }
              : m
            )
          )
        } else if (event.type === 'error') {
          let msg = event.message
          if (msg.includes('access denied') || msg.includes('not configured')) setGeminiUnavailable(true)
          setMessages((prev) =>
            prev.map((m) => m.loading ? { ...m, loading: false, statusText: undefined, text: msg } : m)
          )
        }
      }
    } catch (err: unknown) {
      const serverDetail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? ''
      let msg = serverDetail || (err instanceof Error ? err.message : 'Unknown error')
      if (msg.includes('API key') || msg.includes('API_KEY_INVALID') || msg.includes('access denied') || msg.includes('not configured')) {
        msg = 'AI Analyst is unavailable — Vertex AI is not configured. Contact your administrator.'
        setGeminiUnavailable(true)
      } else if (msg.includes('429') || msg.includes('quota') || msg.includes('rate limit') || msg.includes('Quota exceeded')) {
        msg = 'AI quota exceeded. Please wait a few minutes and try again.'
      }
      setMessages((prev) =>
        prev.map((m) => m.loading ? { ...m, loading: false, statusText: undefined, text: msg } : m)
      )
    } finally {
      setLoading(false)
    }
  }

  function send() { sendMessage(input.trim()) }

  function clearChat() {
    setMessages([{ id: mid(), role: 'assistant', text: 'Chat cleared. What would you like to explore?' }])
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  function toggleVoice() {
    if (!SpeechRecognition) return
    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }
    const rec = new SpeechRecognition()
    rec.continuous = false
    rec.interimResults = false
    rec.lang = 'en-US'
    rec.onresult = (e: SpeechRecognitionEvent) => {
      const transcript = e.results[0][0].transcript
      setInput((prev) => (prev ? prev + ' ' + transcript : transcript))
      setExpanded(true)
      inputRef.current?.focus()
    }
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    recognitionRef.current = rec
    rec.start()
    setListening(true)
  }

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 flex flex-col bg-white border-t border-brand-200 shadow-[0_-4px_24px_rgba(220,38,38,0.1)]"
      style={{ height: expanded ? `${EXPANDED_HEIGHT}px` : '54px', transition: 'height 0.22s cubic-bezier(0.4,0,0.2,1)' }}
    >
      {/* ── Content area (header + messages) ── */}
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-brand-50 to-white border-b border-brand-100">
          <div className="flex items-center gap-2.5">
            <div className="h-7 w-7 rounded-full bg-brand-100 border border-brand-200 flex items-center justify-center">
              <Sparkles size={13} className="text-brand-600" />
            </div>
            <div>
              <span className="text-sm font-semibold text-gray-800">AI Analyst</span>
              <span className="text-xs text-gray-400 ml-2 hidden sm:inline">ask anything about your workforce data</span>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              onClick={clearChat}
              title="Clear chat"
              className="p-1.5 text-slate-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg transition-colors"
            >
              <RotateCcw size={13} />
            </button>
            <button
              onClick={() => setExpanded(false)}
              title="Minimize"
              className="flex items-center gap-1 px-2 py-1.5 text-slate-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg transition-colors text-xs"
            >
              <ChevronDown size={14} />
              <span className="hidden sm:inline">Minimize</span>
            </button>
          </div>
        </div>

        {/* Gemini unavailable banner */}
        {geminiUnavailable && (
          <div className="mx-4 mt-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700 flex items-center gap-2">
            <span>⚠️</span>
            <span>AI Analyst unavailable — Gemini API key not configured. Scorecard tabs still work normally.</span>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-2 space-y-1.5">
          {messages.length === 1 && (
            <div className="flex flex-wrap gap-1.5 pb-1">
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => { setInput(s); inputRef.current?.focus() }}
                  className="text-[11px] bg-brand-50 hover:bg-brand-100 hover:text-brand-700 text-brand-600 px-2.5 py-1 rounded-full transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[88%] flex flex-col gap-1.5 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className={`px-3 py-1.5 rounded-2xl text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-brand-600 text-white rounded-br-sm'
                    : 'bg-slate-100 text-slate-800 rounded-bl-sm'
                }`}>
                  {msg.loading ? (
                    <span className="flex items-center gap-2 text-slate-400">
                      <Loader2 size={13} className="animate-spin flex-shrink-0" />
                      <span className="text-xs italic">{msg.statusText ?? 'Starting…'}</span>
                    </span>
                  ) : (
                    <span className="whitespace-pre-wrap">{msg.text}</span>
                  )}
                </div>

                {msg.widget && (msg.widget.data?.length > 0 || msg.widget.error) && (
                  <div className={`w-full bg-white border rounded-xl overflow-hidden shadow-sm ${msg.widget.error ? 'border-red-200' : 'border-gray-200'}`}>
                    <div className={`flex items-center justify-between px-3 py-2 border-b ${msg.widget.error ? 'bg-red-50 border-red-100' : 'bg-brand-50 border-brand-100'}`}>
                      <span className="text-xs font-semibold text-slate-700 truncate">{msg.widget.title}</span>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {!msg.widget.error && (
                          <span className="text-[10px] bg-brand-100 text-brand-700 px-1.5 py-0.5 rounded">
                            {msg.widget.chart_type.replace('_', ' ')}
                          </span>
                        )}
                        {onAddWidget && (
                          <button
                            onClick={() => onAddWidget(msg.widget!)}
                            className={`flex items-center gap-1 text-[10px] text-white px-2 py-0.5 rounded ml-1 ${msg.widget.error ? 'bg-red-500 hover:bg-red-600' : 'bg-brand-600 hover:bg-brand-700'}`}
                          >
                            <Plus size={10} /> Add to tab
                          </button>
                        )}
                      </div>
                    </div>
                    {msg.widget.error ? (
                      <div className="px-3 py-2.5 flex items-start gap-2">
                        <span className="text-[11px] text-red-600 font-mono break-all leading-relaxed whitespace-pre-wrap">{msg.widget.error}</span>
                      </div>
                    ) : (
                      <>
                        {msg.widget.ai_description && (
                          <p className="text-[10px] text-brand-700 bg-brand-50 px-3 py-1.5 border-b border-brand-100">
                            {msg.widget.ai_description}
                          </p>
                        )}
                        <div className="p-2">
                          <ChartRenderer
                            chart_type={msg.widget.chart_type as ChartType}
                            data={msg.widget.data}
                            x_axis={msg.widget.x_axis}
                            y_axis={msg.widget.y_axis}
                            color_field={msg.widget.color_field}
                            stacked={msg.widget.stacked}
                            dual_axis={msg.widget.dual_axis}
                            secondary_y={msg.widget.secondary_y}
                            height={180}
                          />
                        </div>
                      </>
                    )}
                  </div>
                )}

                {msg.suggested_questions && msg.suggested_questions.length > 0 && !msg.loading && (
                  <div className="flex flex-wrap gap-1.5 mt-0.5">
                    {msg.suggested_questions.map((q) => (
                      <button
                        key={q}
                        onClick={() => sendMessage(q)}
                        className="text-[11px] bg-brand-50 hover:bg-brand-100 text-brand-600 hover:text-brand-700 px-2.5 py-1 rounded-full border border-brand-100 transition-colors text-left"
                      >
                        ↳ {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── Input bar — always visible at bottom ── */}
      <div className="flex-shrink-0 flex items-center gap-2.5 px-4 py-3 border-t border-brand-100 bg-white">
        {!expanded && (
          <button
            onClick={() => setExpanded(true)}
            title="Open AI Analyst"
            className="flex items-center gap-1.5 flex-shrink-0 text-brand-600 hover:text-brand-700 transition-colors"
          >
            <div className="h-6 w-6 rounded-full bg-brand-50 border border-brand-200 flex items-center justify-center">
              <Sparkles size={12} className="text-brand-600" />
            </div>
            <ChevronUp size={14} />
          </button>
        )}
        <div className="flex-1 flex flex-col min-w-0">
          {isSql(input) && (
            <span className="text-[10px] font-semibold text-emerald-600 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded self-start mb-0.5">
              SQL — runs directly
            </span>
          )}
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onFocus={() => setExpanded(true)}
            onKeyDown={handleKeyDown}
            placeholder={expanded ? 'Ask anything or paste SQL… (Enter to send)' : 'Ask anything about your workforce data…'}
            className="w-full bg-transparent text-sm text-gray-700 placeholder-gray-400 resize-none outline-none leading-relaxed"
            style={{ maxHeight: '72px', overflowY: 'auto' }}
          />
        </div>
        {SpeechRecognition && (
          <button
            onClick={toggleVoice}
            title={listening ? 'Stop recording' : 'Voice input'}
            className={`flex-shrink-0 h-8 w-8 flex items-center justify-center rounded-lg transition-colors ${
              listening
                ? 'bg-brand-600 text-white animate-pulse'
                : 'text-brand-400 hover:text-brand-600 hover:bg-brand-50'
            }`}
          >
            {listening ? <MicOff size={14} /> : <Mic size={14} />}
          </button>
        )}
        {expanded && (
          <button
            onClick={() => setExpanded(false)}
            title="Minimize"
            className="p-1.5 text-slate-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg flex-shrink-0 transition-colors"
          >
            <ChevronDown size={15} />
          </button>
        )}
        <button
          onClick={send}
          disabled={!input.trim() || loading}
          className="flex-shrink-0 h-8 w-8 flex items-center justify-center bg-brand-600 hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
        </button>
      </div>
    </div>
  )
}
