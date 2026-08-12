/** Nested enum_tree value_schema helpers (SDK taxonomy_tree scaffold). */

export type EnumTreeNode = {
  id: string
  name?: string
  children?: EnumTreeNode[]
}

/** Form row for Hub editor: id + optional nested children. */
export type EnumTreeFormNode = {
  id: string
  /** When true, show children editors (may still be empty until filled). */
  nested?: boolean
  children?: EnumTreeFormNode[]
}

export function isEnumTreeSchema(schema: unknown): schema is {
  type?: string
  values: unknown[]
  labels?: Record<string, string>
} {
  if (!schema || typeof schema !== 'object') return false
  const s = schema as { type?: string; values?: unknown[] }
  if (s.type === 'enum_tree') return true
  if (!Array.isArray(s.values) || !s.values.length) return false
  return s.values.some((v) => v && typeof v === 'object' && !Array.isArray(v) && 'id' in (v as object))
}

export function coerceEnumTreeNodes(values: unknown[] | undefined): EnumTreeNode[] {
  if (!Array.isArray(values)) return []
  const out: EnumTreeNode[] = []
  for (const v of values) {
    if (typeof v === 'string') {
      const id = v.trim()
      if (id) out.push({ id })
      continue
    }
    if (!v || typeof v !== 'object' || Array.isArray(v)) continue
    const obj = v as Record<string, unknown>
    const id = String(obj.id ?? '').trim()
    if (!id) continue
    const node: EnumTreeNode = { id }
    if (obj.name != null) node.name = String(obj.name)
    if (Array.isArray(obj.children)) {
      node.children = coerceEnumTreeNodes(obj.children)
    }
    out.push(node)
  }
  return out
}

/** Schema nodes → form rows (nested=true when children present). */
export function enumTreeToFormNodes(nodes: EnumTreeNode[]): EnumTreeFormNode[] {
  return nodes.map((n) => {
    const kids = n.children?.length ? enumTreeToFormNodes(n.children) : undefined
    return {
      id: n.id,
      nested: Boolean(kids?.length),
      children: kids?.length ? kids : [{ id: '', nested: false }],
    }
  })
}

/** Form rows → schema nodes (drop empty ids; only keep children when nested). */
export function formNodesToEnumTree(nodes: EnumTreeFormNode[] | undefined): EnumTreeNode[] {
  if (!Array.isArray(nodes)) return []
  const out: EnumTreeNode[] = []
  for (const row of nodes) {
    const id = String(row?.id ?? '').trim()
    if (!id) continue
    const node: EnumTreeNode = { id }
    if (row.nested) {
      const children = formNodesToEnumTree(row.children)
      if (children.length) node.children = children
    }
    out.push(node)
  }
  return out
}

export function emptyEnumTreeFormNodes(): EnumTreeFormNode[] {
  return [{ id: '', nested: false, children: [{ id: '', nested: false }] }]
}

/** Flatten to leaf ids (and parent-only ids when no children). */
export function flattenEnumTreeIds(nodes: EnumTreeNode[]): string[] {
  const out: string[] = []
  const walk = (ns: EnumTreeNode[]) => {
    for (const n of ns) {
      if (n.children?.length) {
        walk(n.children)
      } else {
        out.push(n.id)
      }
    }
  }
  walk(nodes)
  return out
}

/** All node ids including internal parents. */
export function collectEnumTreeIds(nodes: EnumTreeNode[]): string[] {
  const out: string[] = []
  const walk = (ns: EnumTreeNode[]) => {
    for (const n of ns) {
      out.push(n.id)
      if (n.children?.length) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

export function validateEnumTreeNodes(nodes: EnumTreeNode[]): string[] {
  const errors: string[] = []
  if (!nodes.length) return ['请至少添加一个树节点']
  const seen = new Set<string>()
  const walk = (ns: EnumTreeNode[], path: string) => {
    for (const n of ns) {
      const id = n.id.trim()
      if (!id) {
        errors.push(`空 id（${path || '/'}）`)
        continue
      }
      if (seen.has(id)) errors.push(`重复 id：${id}`)
      seen.add(id)
      if (n.children?.length) walk(n.children, `${path}/${id}`)
    }
  }
  walk(nodes, '')
  return errors
}

export function formatEnumTreeLines(
  nodes: EnumTreeNode[],
  labels: Record<string, string> = {},
  indent = 0,
): string[] {
  const lines: string[] = []
  const pad = '  '.repeat(indent)
  for (const n of nodes) {
    const label = labels[n.id] ?? n.name ?? n.id
    lines.push(`${pad}${label} (${n.id})`)
    if (n.children?.length) {
      lines.push(...formatEnumTreeLines(n.children, labels, indent + 1))
    }
  }
  return lines
}
