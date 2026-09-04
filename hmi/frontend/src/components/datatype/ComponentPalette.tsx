import { useState, type ReactNode } from 'react'
import { CATEGORY_ORDER, CATEGORY_TITLES } from '../../utils/recipePipeline'
import type { PlatformOperator } from '../../api/types'

const CAT_COLOR: Record<string, string> = {
  parse: '#5e6ad2',
  encode: '#27a644',
  audio: '#d97706',
  detect_ai: '#828fff',
}

export type PaletteExtra = { id: string; title: string; testId: string }

type ExtraGroup = { id: string; groupTitle: string; items: PaletteExtra[] }

type Props = {
  operators: PlatformOperator[]
  categoryTitles?: Record<string, string>
  onAdd: (opId: string) => void
  hideOpIds?: string[]
  extras?: ExtraGroup[]
}

function PaletteGroup({
  id,
  title,
  collapsed,
  onToggle,
  children,
}: {
  id: string
  title: string
  collapsed: boolean
  onToggle: (id: string) => void
  children: ReactNode
}) {
  return (
    <div className="pipe-orch__group" data-testid={`palette-group-${id}`}>
      <button
        type="button"
        className="pipe-orch__group-title"
        aria-expanded={!collapsed}
        data-testid={`palette-group-toggle-${id}`}
        onClick={() => onToggle(id)}
      >
        <span className={`pipe-orch__group-caret${collapsed ? ' is-collapsed' : ''}`} aria-hidden>
          ▾
        </span>
        {title}
      </button>
      {collapsed ? null : children}
    </div>
  )
}

export function ComponentPalette({ operators, categoryTitles, onAdd, hideOpIds, extras }: Props) {
  const hidden = new Set(hideOpIds || [])
  const titles = categoryTitles && Object.keys(categoryTitles).length ? categoryTitles : CATEGORY_TITLES
  const groups = CATEGORY_ORDER.map((cat) => ({
    cat,
    title: titles[cat] || cat,
    ops: operators.filter((op) => (op.category || 'detect_ai') === cat && !hidden.has(op.op_id)),
  })).filter((g) => g.ops.length)
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <aside className="pipe-orch__palette" data-testid="pipeline-palette">
      <p className="pipe-orch__palette-kicker">管线组件</p>
      {groups.map((g) => (
        <PaletteGroup key={g.cat} id={g.cat} title={g.title} collapsed={!expanded.has(g.cat)} onToggle={toggle}>
          {g.ops.map((op) => (
            <button
              key={op.op_id}
              type="button"
              className="pipe-orch__op"
              data-testid={`palette-op-${op.op_id}`}
              onClick={() => onAdd(op.op_id)}
            >
              <span className="pipe-orch__op-dot" style={{ background: CAT_COLOR[g.cat] || '#5e6ad2' }} />
              {op.title}
            </button>
          ))}
        </PaletteGroup>
      ))}
      {(extras || []).map((g) => (
        <PaletteGroup
          key={g.id}
          id={g.id}
          title={g.groupTitle}
          collapsed={!expanded.has(g.id)}
          onToggle={toggle}
        >
          {g.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="pipe-orch__op"
              data-testid={item.testId}
              onClick={() => onAdd(item.id)}
            >
              <span className="pipe-orch__op-dot" style={{ background: '#828fff' }} />
              {item.title}
            </button>
          ))}
        </PaletteGroup>
      ))}
    </aside>
  )
}
