import { ReactNode } from 'react'

interface StatCardProps {
  label: string
  value: ReactNode
  icon?: ReactNode
  hint?: ReactNode
  valueClassName?: string
  iconWrapClassName?: string
}

export default function StatCard({
  label,
  value,
  icon,
  hint,
  valueClassName,
  iconWrapClassName,
}: StatCardProps) {
  return (
    <div className="stat-card card-hover">
      {icon ? (
        <div className={`stat-icon ${iconWrapClassName ?? 'stat-icon-primary'}`}>{icon}</div>
      ) : null}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-dark-400">{label}</p>
        <p className={`text-2xl font-bold mt-1 tabular-nums ${valueClassName ?? 'text-gray-50'}`}>
          {value}
        </p>
        {hint ? <p className="text-xs text-dark-400 mt-1">{hint}</p> : null}
      </div>
    </div>
  )
}
