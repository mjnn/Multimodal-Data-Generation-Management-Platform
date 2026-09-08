import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import { CATEGORY_ORDER, CATEGORY_TITLES } from '../../utils/recipePipeline'
import type { PlatformOperator } from '../../api/types'

export const PALETTE_OP_MIME = 'application/hmi-dag-op'

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
  onAdd: (opId: string, position?: { x: number; y: number }) => void
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

function matchesQuery(query: string, ...parts: Array<string | undefined>): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return parts.some((p) => String(p || '').toLowerCase().includes(q))
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
  const [query, setQuery] = useState('')
  const skipClickRef = useRef(false)
  const searching = query.trim().length > 0

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const startDrag = (opId: string) => (e: DragEvent) => {
    skipClickRef.current = true
    e.dataTransfer.setData(PALETTE_OP_MIME, opId)
    e.dataTransfer.setData('text/plain', opId)
    e.dataTransfer.effectAllowed = 'copy'
  }

  const clickAdd = (opId: string) => {
    if (skipClickRef.current) {
      skipClickRef.current = false
      return
    }
    onAdd(opId)
  }

  const renderOp = (opId: string, title: string, testId: string, color: string, desc?: string) => (
    <button
      key={opId}
      type="button"
      className="pipe-orch__op"
      data-testid={testId}
      title={desc || title}
      draggable
      onDragStart={startDrag(opId)}
      onDragEnd={() => {
        window.setTimeout(() => {
          skipClickRef.current = false
        }, 0)
      }}
      onClick={() => clickAdd(opId)}
    >
      <span className="pipe-orch__op-dot" style={{ background: color }} />
      <span className="pipe-orch__op-text">
        <span className="pipe-orch__op-title">{title}</span>
        {desc ? <span className="pipe-orch__op-desc">{desc}</span> : null}
      </span>
    </button>
  )

  return (
    <aside className="pipe-orch__palette" data-testid="pipeline-palette">
      <p className="pipe-orch__palette-kicker">管线组件</p>
      <input
        className="pipe-orch__palette-search"
        data-testid="palette-search"
        placeholder="搜索组件"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {groups.map((g) => {
        const ops = searching
          ? g.ops.filter((op) => matchesQuery(query, op.title, op.op_id, op.description))
          : g.ops
        if (!ops.length) return null
        const collapsed = searching ? false : !expanded.has(g.cat)
        return (
          <PaletteGroup key={g.cat} id={g.cat} title={g.title} collapsed={collapsed} onToggle={toggle}>
            {ops.map((op) =>
              renderOp(op.op_id, op.title, `palette-op-${op.op_id}`, CAT_COLOR[g.cat] || '#5e6ad2', op.description),
            )}
          </PaletteGroup>
        )
      })}
      {(extras || []).map((g) => {
        const items = searching
          ? g.items.filter((item) => matchesQuery(query, item.title, item.id))
          : g.items
        if (!items.length) return null
        const collapsed = searching ? false : !expanded.has(g.id)
        return (
          <PaletteGroup
            key={g.id}
            id={g.id}
            title={g.groupTitle}
            collapsed={collapsed}
            onToggle={toggle}
          >
            {items.map((item) => renderOp(item.id, item.title, item.testId, '#828fff'))}
          </PaletteGroup>
        )
      })}
    </aside>
  )
}
