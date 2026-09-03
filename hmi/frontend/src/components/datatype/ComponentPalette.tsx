import { CATEGORY_ORDER, CATEGORY_TITLES } from '../../utils/recipePipeline'
import type { PlatformOperator } from '../../api/types'

const CAT_COLOR: Record<string, string> = {
  parse: '#5e6ad2',
  encode: '#27a644',
  audio: '#d97706',
  detect_ai: '#828fff',
}

type Props = {
  operators: PlatformOperator[]
  categoryTitles?: Record<string, string>
  onAdd: (opId: string) => void
}

export function ComponentPalette({ operators, categoryTitles, onAdd }: Props) {
  const titles = categoryTitles && Object.keys(categoryTitles).length ? categoryTitles : CATEGORY_TITLES
  const groups = CATEGORY_ORDER.map((cat) => ({
    cat,
    title: titles[cat] || cat,
    ops: operators.filter((op) => (op.category || 'detect_ai') === cat),
  })).filter((g) => g.ops.length)

  return (
    <aside className="pipe-orch__palette" data-testid="pipeline-palette">
      <p className="pipe-orch__palette-kicker">SDK 组件</p>
      {groups.map((g) => (
        <div key={g.cat} className="pipe-orch__group">
          <p className="pipe-orch__group-title">{g.title}</p>
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
        </div>
      ))}
    </aside>
  )
}
