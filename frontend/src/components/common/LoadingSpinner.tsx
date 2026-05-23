export function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sz = size === 'sm' ? 'h-4 w-4' : size === 'lg' ? 'h-10 w-10' : 'h-6 w-6'
  return (
    <div className={`animate-spin rounded-full border-2 border-gray-200 border-t-brand-600 ${sz}`} />
  )
}

export function LoadingOverlay({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-gray-400">
      <LoadingSpinner size="lg" />
      <span className="text-sm">{label}</span>
    </div>
  )
}
