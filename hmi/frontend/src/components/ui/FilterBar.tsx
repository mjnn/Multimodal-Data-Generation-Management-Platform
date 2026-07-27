import { Segmented } from 'antd'
import type { ReactNode } from 'react'

export type FilterOption = {
  value: string
  label: ReactNode
  count?: number
}

type FilterBarProps = {
  label?: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
  total?: number
  totalLabel?: string
  'aria-label'?: string
}

/**
 * Secondary in-page filters — visually distinct from primary sidebar navigation (ux: nav-hierarchy).
 * Use Segmented pills, not Ant Tabs, to avoid mixing hierarchy levels (ux: avoid-mixed-patterns).
 */
export function FilterBar({
  label = '筛选',
  value,
  options,
  onChange,
  total,
  totalLabel = '条记录',
  'aria-label': ariaLabel,
}: FilterBarProps) {
  return (
    <div className="filter-bar" role="toolbar" aria-label={ariaLabel ?? `${label}工具栏`}>
      <span className="filter-bar__label">{label}</span>
      <Segmented
        className="filter-bar__segmented"
        value={value}
        onChange={(v) => onChange(String(v))}
        options={options.map((opt) => ({
          value: opt.value,
          label:
            opt.count != null ? (
              <span className="filter-bar__option">
                {opt.label}
                <span className="filter-bar__count-badge">{opt.count}</span>
              </span>
            ) : (
              opt.label
            ),
        }))}
      />
      {total != null ? (
        <span className="filter-bar__total" aria-live="polite">
          共 {total.toLocaleString()} {totalLabel}
        </span>
      ) : null}
    </div>
  )
}
