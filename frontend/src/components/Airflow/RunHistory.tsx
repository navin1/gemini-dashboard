import type { AirflowRun } from '../../types'
import { STATE_COLORS, STATE_ICONS } from './TaskNode'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

interface Props {
  runs: AirflowRun[]
  selectedRunId: string | null
  onSelectRun: (runId: string) => void
}

export default function RunHistory({ runs, selectedRunId, onSelectRun }: Props) {
  if (!runs.length) return (
    <div className="text-sm text-gray-400 py-4 text-center">No runs found</div>
  )

  return (
    <div className="overflow-auto rounded-lg border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
          <tr>
            <th className="px-3 py-2 text-left">Run ID</th>
            <th className="px-3 py-2 text-left">Status</th>
            <th className="px-3 py-2 text-left">Execution Date</th>
            <th className="px-3 py-2 text-left">Start</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const color = STATE_COLORS[run.state] ?? STATE_COLORS._default
            const icon  = STATE_ICONS[run.state] ?? '◆'
            const isSelected = run.run_id === selectedRunId
            return (
              <tr
                key={run.run_id}
                onClick={() => onSelectRun(run.run_id)}
                className={`border-t border-gray-100 cursor-pointer transition-colors ${isSelected ? 'bg-brand-50' : 'hover:bg-gray-50'}`}
              >
                <td className="px-3 py-2 font-mono text-xs text-gray-600 max-w-[260px] truncate">{run.run_id}</td>
                <td className="px-3 py-2">
                  <span style={{ color, fontWeight: 600, fontSize: 12 }}>{icon} {run.state}</span>
                </td>
                <td className="px-3 py-2 text-gray-500">{formatDate(run.execution_date)}</td>
                <td className="px-3 py-2 text-gray-500">{formatDate(run.start_date)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
