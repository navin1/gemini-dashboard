import { useState, useEffect, useCallback, useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchExcelMapping, refreshExcelMapping, getPreviewUrl } from '../../api/excelMapping'
import type { ExcelMappingFile } from '../../api/excelMapping'

interface Props {
  onRegisterRefresh: (fn: () => void) => void
}

type SortKey = 'display_name' | 'total_rows' | 'mapped' | 'in_progress'
type SortDir = 'asc' | 'desc'

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey | null; sortDir: SortDir }) {
  if (sortKey !== col) return <span className="text-gray-300 ml-1 text-[10px]">↕</span>
  return <span className="text-gray-600 ml-1 text-[10px]">{sortDir === 'asc' ? '↑' : '↓'}</span>
}

export default function ExcelMappingSection({ onRegisterRefresh }: Props) {
  const [files,        setFiles]        = useState<ExcelMappingFile[]>([])
  const [fetching,     setFetching]     = useState(false)
  const [error,        setError]        = useState<string | null>(null)
  const [unconfigured, setUnconfigured] = useState(false)
  const [sortKey,      setSortKey]      = useState<SortKey | null>(null)
  const [sortDir,      setSortDir]      = useState<SortDir>('asc')

  const load = useCallback(async (forceRefresh = false) => {
    setFetching(true)
    setError(null)
    try {
      const res = forceRefresh ? await refreshExcelMapping() : await fetchExcelMapping()
      if (!res.configured) {
        setUnconfigured(true)
        setFiles([])
      } else {
        setUnconfigured(false)
        setFiles(res.files)
      }
    } catch (e: unknown) {
      setError((e as Error).message ?? 'Failed to fetch Excel mapping data')
    } finally {
      setFetching(false)
    }
  }, [])

  useEffect(() => { load(false) }, [load])
  useEffect(() => { onRegisterRefresh(() => load(true)) }, [load, onRegisterRefresh])

  function handleSort(col: SortKey) {
    if (sortKey === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(col); setSortDir('asc') }
  }

  const sorted = useMemo(() => {
    if (!sortKey) return files
    return [...files].sort((a, b) => {
      const av = a[sortKey] ?? -1
      const bv = b[sortKey] ?? -1
      if (typeof av === 'number' && typeof bv === 'number')
        return sortDir === 'asc' ? av - bv : bv - av
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    })
  }, [files, sortKey, sortDir])

  // Computed summary (exclude errored files from numeric totals)
  const validFiles  = files.filter(f => !f.error)
  const totalRows   = validFiles.reduce((s, f) => s + (f.total_rows ?? 0), 0)
  const totalMapped = validFiles.reduce((s, f) => s + (f.mapped ?? 0), 0)
  const pct         = totalRows ? Math.round(totalMapped / totalRows * 100) : 0

  const thBase = 'px-3 py-2 text-left text-xs font-semibold text-gray-600 whitespace-nowrap select-none cursor-pointer hover:bg-gray-100 transition-colors'
  const numTh  = `${thBase} text-right`

  if (fetching && files.length === 0) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-gray-400">
        <Loader2 size={14} className="animate-spin" />
        <span className="text-xs">Loading Excel mappings…</span>
      </div>
    )
  }

  if (unconfigured) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-gray-400 text-center px-4">
        Excel mapping is not configured. Set EXCEL_MAPPING_FILE_PATH in .env
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

  if (!fetching && files.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-gray-400">
        No .xlsx files found in the configured paths.
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* AI Insight summary */}
      <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-100 flex-shrink-0">
        <p className="text-[11px] text-slate-500">
          {validFiles.length} file{validFiles.length !== 1 ? 's' : ''} ·{' '}
          {totalRows.toLocaleString()} total rows ·{' '}
          <span className="text-emerald-600 font-medium">{totalMapped.toLocaleString()} mapped ({pct}%)</span> ·{' '}
          <span className="text-amber-600 font-medium">{(totalRows - totalMapped).toLocaleString()} in progress</span>
          {files.some(f => f.error) && (
            <> · <span className="text-red-500 font-medium">{files.filter(f => f.error).length} error{files.filter(f => f.error).length > 1 ? 's' : ''}</span></>
          )}
        </p>
      </div>

      {fetching && (
        <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-gray-400 flex-shrink-0">
          <Loader2 size={11} className="animate-spin" /> Refreshing…
        </div>
      )}

      <div className="overflow-auto flex-1 rounded border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
            <tr>
              <th className={thBase} onClick={() => handleSort('display_name')}>
                File Name <SortIcon col="display_name" sortKey={sortKey} sortDir={sortDir} />
              </th>
              <th className={numTh}  onClick={() => handleSort('total_rows')}>
                Total Rows <SortIcon col="total_rows" sortKey={sortKey} sortDir={sortDir} />
              </th>
              <th className={numTh}  onClick={() => handleSort('mapped')}>
                Mapped <SortIcon col="mapped" sortKey={sortKey} sortDir={sortDir} />
              </th>
              <th className={numTh}  onClick={() => handleSort('in_progress')}>
                In Progress <SortIcon col="in_progress" sortKey={sortKey} sortDir={sortDir} />
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((file, i) => {
              const rowBg  = i % 2 === 0 ? 'bg-white' : 'bg-blue-50'
              const isError = !!file.error
              return (
                <tr key={file.display_name} className={rowBg}>
                  <td className="px-3 py-2">
                    {isError ? (
                      <span className="text-red-600 font-semibold">{file.display_name}</span>
                    ) : (
                      <button
                        className="text-blue-600 underline hover:text-blue-800 text-xs text-left"
                        onClick={() => window.open(getPreviewUrl(file.display_name), '_blank')}
                      >
                        {file.display_name}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-700">
                    {isError ? '—' : file.total_rows?.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {isError ? '—' : (
                      <span className={file.mapped ? 'text-emerald-600 font-semibold' : 'text-gray-400'}>
                        {file.mapped?.toLocaleString()}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {isError ? (
                      <span className="text-red-500 text-[10px] leading-tight">{file.error}</span>
                    ) : (
                      <span className={file.in_progress ? 'text-amber-600 font-semibold' : 'text-gray-400'}>
                        {file.in_progress?.toLocaleString()}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
