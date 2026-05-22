interface BarRowProps {
  label: string
  count: number
  percent: number
}

export default function BarRow({ label, count, percent }: BarRowProps) {
  const safePercent = Math.max(0, Math.min(100, percent))
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24 truncate text-dark-400" title={label}>
        {label}
      </span>
      <span className="w-12 text-right text-gray-50 tabular-nums">{count}</span>
      <div className="flex-1 h-2 bg-dark-700 rounded overflow-hidden">
        <div
          className="h-full bg-primary-500 rounded transition-all"
          style={{ width: `${safePercent}%` }}
        />
      </div>
      <span className="w-12 text-right text-dark-400 tabular-nums">{safePercent.toFixed(0)}%</span>
    </div>
  )
}
