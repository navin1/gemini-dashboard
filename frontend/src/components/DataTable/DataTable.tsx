import { useState } from 'react'
import { ChevronUp, ChevronDown } from 'lucide-react'

const MONEY_COL = /spend|dollar|amount|budget|cost|ytd|capital|expense|salary|fee/i
const COUNT_COL = /count|ftp|fte|hc|headcount|qty|quantity|rank|row_num|num_/i
const PCT_COL   = /pct|percent|_pct$/i

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
  // Plain number: integers without decimals, decimals with up to 2 places
  return Number.isInteger(val)
    ? val.toLocaleString()
    : val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

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

  const headers = Object.keys(data[0])
  const numericCols = new Set(headers.filter((h) => typeof data.find((r) => r[h] != null)?.[h] === 'number'))
  const limited = data.slice(0, maxRows)

  const sorted = sortKey
    ? [...limited].sort((a, b) => {
        const av = a[sortKey] as number | string
        const bv = b[sortKey] as number | string
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === 'asc' ? cmp : -cmp
      })
    : limited

  const totalPages = Math.ceil(sorted.length / pageSize)
  const visible = sorted.slice(page * pageSize, page * pageSize + pageSize)

  function toggleSort(key: string) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-auto rounded border border-gray-200">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              {headers.map((h) => (
                <th
                  key={h}
                  onClick={() => toggleSort(h)}
                  className={`px-3 py-2 font-semibold text-gray-600 whitespace-nowrap cursor-pointer hover:bg-gray-100 select-none ${numericCols.has(h) ? 'text-right' : 'text-left'}`}
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
              <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
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
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-500">
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
