import { X } from 'lucide-react'

const MONEY_LABEL = /spend|cost|budget|amount|dollar|fee|salary|capital|expense/i
const PCT_LABEL   = /pct|percent/i

function fmt(val: number | null | undefined, label = '', pct = false, raw = false): string {
  if (val == null || isNaN(val)) return '—'
  if (pct || PCT_LABEL.test(label)) return `${(val as number).toFixed(2)}%`
  if (raw) return val.toLocaleString()
  const money = MONEY_LABEL.test(label)
  if (money) {
    if (Math.abs(val) >= 1_000_000) return `$${(val / 1_000_000).toFixed(2)}M`
    if (Math.abs(val) >= 1_000)     return `$${(val / 1_000).toFixed(2)}K`
    return `$${val.toFixed(2)}`
  }
  return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2)
}

interface Props {
  label: string
  value: number | null | undefined
  pct?: boolean
  raw?: boolean
  sub?: string
  onRemove?: () => void
}

export function KPICard({ label, value, pct = false, raw = false, sub, onRemove }: Props) {
  return (
    <div className="relative bg-white border border-gray-200 rounded-lg px-5 py-4 min-w-[160px] text-center group/kpi">
      {onRemove && (
        <button
          onClick={onRemove}
          title="Remove KPI"
          className="absolute top-1 right-1 p-0.5 text-gray-300 hover:text-red-400 rounded opacity-0 group-hover/kpi:opacity-100 transition-opacity"
        >
          <X size={11} />
        </button>
      )}
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{fmt(value, label, pct, raw)}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}
