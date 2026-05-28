import { useState, useEffect, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchSchemaAudit } from '../../api/schemaAudit'
import type { SchemaAuditSummary } from '../../api/schemaAudit'

interface Props {
  env: string
  onRegisterRefresh: (fn: () => void) => void
}

function fmtDiff(n: number): string {
  if (n === 0) return '0'
  return n > 0 ? `+${n}` : `${n}`
}

function MismatchCell({ count }: { count: number }) {
  if (count === 0) return <span className="text-gray-400">0</span>
  return <span className="font-semibold text-red-600">{count}</span>
}

export default function SchemaAuditSection({ env, onRegisterRefresh }: Props) {
  const [tables,    setTables]    = useState<SchemaAuditSummary[]>([])
  const [fetching,  setFetching]  = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [unconfigured, setUnconfigured] = useState(false)

  const load = useCallback(async () => {
    if (!env) return
    setFetching(true)
    setError(null)
    try {
      const res = await fetchSchemaAudit(env)
      if (!res.configured) {
        setUnconfigured(true)
        setTables([])
      } else {
        setUnconfigured(false)
        setTables(res.tables)
      }
    } catch (e: unknown) {
      setError((e as Error).message ?? 'Failed to fetch schema audit data')
    } finally {
      setFetching(false)
    }
  }, [env])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    onRegisterRefresh(load)
  }, [load, onRegisterRefresh])

  const thClass = 'px-3 py-2 text-left text-xs font-semibold text-gray-600 whitespace-nowrap select-none'
  const numThClass = `${thClass} text-right`

  if (fetching && tables.length === 0) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-gray-400">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-xs">Loading schema audit…</span>
      </div>
    )
  }

  if (unconfigured) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-gray-400 text-center px-4">
        Schema audit is not configured. Set SCHEMA_AUDIT_SRC_TBL and SCHEMA_AUDIT_{env.toUpperCase()}_SRC / _TGT in .env
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-red-500 text-center px-4">
        {error}
      </div>
    )
  }

  if (!fetching && tables.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-gray-400">
        No tables found in the audit source table.
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {fetching && (
        <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-gray-400 flex-shrink-0">
          <Loader2 size={11} className="animate-spin" /> Refreshing…
        </div>
      )}

      <div className="overflow-auto flex-1 rounded border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
            <tr>
              <th className={thClass}>Table Name</th>
              <th className={numThClass}>Column Count</th>
              <th className={numThClass}>Column Name</th>
              <th className={numThClass}>Data Type</th>
              <th className={numThClass}>Position</th>
            </tr>
          </thead>
          <tbody>
            {tables.map((row, i) => {
              const isRed = row.src_missing || row.tgt_missing
              const baseText = isRed ? 'text-red-600 font-semibold' : 'text-gray-700'
              const rowBg = i % 2 === 0 ? 'bg-white' : 'bg-blue-50'

              const diffLabel = row.src_missing
                ? 'SRC missing'
                : row.tgt_missing
                  ? 'TGT missing'
                  : fmtDiff(row.col_count_diff)

              const diffColor = row.src_missing || row.tgt_missing
                ? 'text-red-600 font-semibold'
                : row.col_count_diff !== 0
                  ? 'font-semibold text-amber-600'
                  : 'text-gray-400'

              return (
                <tr key={row.table_name} className={rowBg}>
                  <td className={`px-3 py-2 ${baseText}`}>{row.table_name}</td>
                  <td className={`px-3 py-2 text-right ${diffColor}`}>{diffLabel}</td>
                  <td className="px-3 py-2 text-right"><MismatchCell count={row.col_name_mismatches} /></td>
                  <td className="px-3 py-2 text-right"><MismatchCell count={row.type_mismatches} /></td>
                  <td className="px-3 py-2 text-right"><MismatchCell count={row.pos_mismatches} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[10px] text-gray-400 flex-shrink-0 pt-1.5">
        Sorted: mismatched tables first · Column Count = SRC − TGT · mismatch counts exclude Source/Target-only columns from type/position totals
      </p>
    </div>
  )
}
