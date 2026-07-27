import type { ReactNode } from 'react'

type StatCardProps = {
  label: string
  value: ReactNode
  hint?: string
  accent?: 'default' | 'success' | 'warning' | 'danger' | 'stat'
  icon?: ReactNode
}

const accentClass: Record<NonNullable<StatCardProps['accent']>, string> = {
  default: '',
  success: 'stat-card--success',
  warning: 'stat-card--warning',
  danger: 'stat-card--danger',
  stat: 'stat-card--stat',
}

export function StatCard({ label, value, hint, accent = 'default', icon }: StatCardProps) {
  return (
    <div className={`stat-card grid-item ${accentClass[accent]}`}>
      <div className="stat-card__top">
        <span className="stat-card__label">{label}</span>
        {icon ? <span className="stat-card__icon">{icon}</span> : null}
      </div>
      <div className="stat-card__value">{value}</div>
      {hint ? <div className="stat-card__hint">{hint}</div> : null}
    </div>
  )
}
