import { useState, KeyboardEvent } from 'react'
import { Sparkles, Loader2, Star } from 'lucide-react'

interface Props {
  onSubmit: (query: string) => void
  loading: boolean
  onOpenFavorites?: () => void
}

const SUGGESTIONS = [
  'Show top 10 managers by YTD spend',
  'Compare capital vs expense spend by business area',
  'Show monthly FTE trend for all vendors',
  'Which vendors have the highest offshore percentage?',
  'Show spend with benefits by resource category',
]

export function QueryBar({ onSubmit, loading, onOpenFavorites }: Props) {
  const [query, setQuery] = useState('')
  const [showSuggestions, setShowSuggestions] = useState(false)

  function submit() {
    if (query.trim() && !loading) {
      onSubmit(query.trim())
      setShowSuggestions(false)
    }
  }

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
      <div className="flex items-start gap-3">
        <div className="mt-1 h-8 w-8 rounded-full bg-brand-50 border border-brand-200 flex items-center justify-center flex-shrink-0">
          <Sparkles size={15} className="text-brand-600" />
        </div>
        <div className="flex-1">
          <textarea
            rows={2}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            placeholder="Ask anything about your workforce data… e.g. &quot;Show top vendors by expense spend this year&quot;"
            className="w-full text-sm text-gray-900 placeholder-gray-400 resize-none border-none outline-none leading-relaxed"
          />
          {showSuggestions && !query && (
            <div className="mt-2 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onMouseDown={() => { setQuery(s); setShowSuggestions(false) }}
                  className="text-xs bg-gray-100 hover:bg-brand-50 hover:text-brand-700 text-gray-600 px-3 py-1 rounded-full transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {onOpenFavorites && (
            <button
              onClick={onOpenFavorites}
              title="Saved queries"
              className="p-2 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg transition-colors"
            >
              <Star size={16} />
            </button>
          )}
          <button
            onClick={submit}
            disabled={!query.trim() || loading}
            className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            {loading ? 'Generating…' : 'Ask AI'}
          </button>
        </div>
      </div>
    </div>
  )
}
