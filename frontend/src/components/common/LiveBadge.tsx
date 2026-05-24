import { Loader2, WifiOff } from 'lucide-react'
import type { LiveStatus } from '../../hooks/useLiveStream'

export function LiveBadge({ status }: { status: LiveStatus }) {
  if (status === 'off') return null

  if (status === 'connecting') return (
    <span className="flex items-center gap-1 text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-1 rounded-full">
      <Loader2 size={11} className="animate-spin" />
      Connecting…
    </span>
  )

  if (status === 'error') return (
    <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 border border-red-200 px-2 py-1 rounded-full">
      <WifiOff size={11} />
      Reconnecting…
    </span>
  )

  return (
    <span className="flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-1 rounded-full">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
      Live
    </span>
  )
}
