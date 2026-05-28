import { useState } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'

const MONEY_COL = /spend|dollar|amount|budget|cost|ytd|capital|expense|salary|fee/i
const COUNT_COL = /count|ftp|fte|hc|headcount|qty|quantity|rank|row_num|num_/i
const PCT_COL   = /pct|percent|_pct$/i

function fmtMoney(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${Math.round(n)}`
}

function fmtCell(val: unknown, key: string): string {
  if (val == null) return '—'
  if (typeof val !== 'number') return String(val)
  const k = key.toLowerCase()
  if (PCT_COL.test(k)) return `${val.toFixed(2)}%`
  if (MONEY_COL.test(k) && !COUNT_COL.test(k)) {
    if (Math.abs(val) >= 1_000_000) return `$${(val / 1_000_000).toFixed(2)}M`
    if (Math.abs(val) >= 1_000) return `$${(val / 1_000).toFixed(2)}K`
    return `$${val.toFixed(2)}`
  }
  return Number.isInteger(val)
    ? val.toLocaleString()
    : val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const TH = 'px-3 py-2 text-xs font-semibold text-gray-600 whitespace-nowrap select-none cursor-pointer hover:bg-gray-100 transition-colors'

interface Props {
  data: Record<string, unknown>[]
  maxRows?: number
}

export function DataTable({ data, maxRows = 100 }: Props) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const pageSize = 20

  if (!data.length) return <p className="text-sm text-gray-400 text-center py-8">No data</p>

  const headers    = Object.keys(data[0])
  const numericCols = new Set(headers.filter((h) => typeof data.find((r) => r[h] != null)?.[h] === 'number'))
  const limited    = data.slice(0, maxRows)

  const sorted = sortKey
    ? [...limited].sort((a, b) => {
        const av = a[sortKey] as number | string
        const bv = b[sortKey] as number | string
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    : limited

  const totalPages = Math.ceil(sorted.length / pageSize)
  const visible    = sorted.slice(page * pageSize, page * pageSize + pageSize)

  function toggleSort(key: string) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  // Compute aggregates for the insight bar
  const moneyAgg = headers
    .filter(h => MONEY_COL.test(h) && !COUNT_COL.test(h) && numericCols.has(h))
    .slice(0, 2)
    .map(h => ({ label: h.replace(/_/g, ' '), sum: data.reduce((s, r) => s + (((r[h] as number) || 0)), 0) }))
    .filter(({ sum }) => sum !== 0)

  const countAgg = headers
    .filter(h => COUNT_COL.test(h) && numericCols.has(h))
    .slice(0, 2)
    .map(h => ({ label: h.replace(/_/g, ' '), sum: Math.round(data.reduce((s, r) => s + (((r[h] as number) || 0)), 0)) }))
    .filter(({ sum }) => sum !== 0)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* AI Insight summary */}
      <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-100 flex-shrink-0">
        <p className="text-[11px] text-slate-500">
          {data.length.toLocaleString()} row{data.length !== 1 ? 's' : ''}
          {moneyAgg.map(({ label, sum }) => (
            <> · <span key={label} className="text-emerald-600 font-medium">{label}: {fmtMoney(sum)}</span></>
          ))}
          {countAgg.map(({ label, sum }) => (
            <> · <span key={label} className="text-blue-600 font-medium">{label}: {sum.toLocaleString()}</span></>
          ))}
        </p>
      </div>

      {/* Table */}
      <div className="overflow-auto flex-1 rounded border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
            <tr>
              {headers.map((h) => (
                <th
                  key={h}
                  onClick={() => toggleSort(h)}
                  className={`${TH} ${numericCols.has(h) ? 'text-right' : 'text-left'}`}
                >
                  <span className={`flex items-center gap-1 ${numericCols.has(h) ? 'justify-end' : ''}`}>
                    {h.replace(/_/g, ' ')}
                    {sortKey === h
                      ? sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                      : <ChevronDown size={12} className="opacity-20" />}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-blue-50'}>
                {headers.map((h) => (
                  <td key={h} className={`px-3 py-2 text-gray-700 whitespace-nowrap ${numericCols.has(h) ? 'text-right' : ''}`}>
                    {fmtCell(row[h], h)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-500 flex-shrink-0 pt-1">
          <span>
            {page * pageSize + 1}–{Math.min((page + 1) * pageSize, sorted.length)} of {sorted.length} rows
          </span>
          <div className="flex gap-1">
            <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Prev</button>
            <button disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)} className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
