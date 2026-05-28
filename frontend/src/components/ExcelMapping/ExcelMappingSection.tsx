import { useState, useEffect, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { fetchExcelMapping, refreshExcelMapping, getPreviewUrl } from '../../api/excelMapping'
import type { ExcelMappingFile } from '../../api/excelMapping'

interface Props {
  onRegisterRefresh: (fn: () => void) => void
}

export default function ExcelMappingSection({ onRegisterRefresh }: Props) {
  const [files, setFiles] = useState<ExcelMappingFile[]>([])
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unconfigured, setUnconfigured] = useState(false)

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

  const thClass = 'px-3 py-2 text-left text-xs font-semibold text-gray-600 whitespace-nowrap select-none'
  const numThClass = `${thClass} text-right`

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
      {fetching && (
        <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-gray-400 flex-shrink-0">
          <Loader2 size={11} className="animate-spin" /> Refreshing…
        </div>
      )}

      <div className="overflow-auto flex-1 rounded border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0 z-10">
            <tr>
              <th className={thClass}>File Name</th>
              <th className={numThClass}>Total Rows</th>
              <th className={numThClass}>Mapped</th>
              <th className={numThClass}>In Progress</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file, i) => {
              const rowBg = i % 2 === 0 ? 'bg-white' : 'bg-blue-50'
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
                    {isError ? '—' : file.total_rows}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {isError ? '—' : (
                      <span className={file.mapped ? 'text-emerald-600 font-semibold' : 'text-gray-400'}>
                        {file.mapped}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {isError ? (
                      <span className="text-red-500 text-[10px] leading-tight">{file.error}</span>
                    ) : (
                      <span className={file.in_progress ? 'text-amber-600 font-semibold' : 'text-gray-400'}>
                        {file.in_progress}
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
