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

export function isNestedEnumSchema(schema: unknown, dtype?: string | null): boolean {
  if (!isEnumTreeSchema(schema) && (dtype || '').toLowerCase() !== 'enum_tree') return false
  const values =
    schema && typeof schema === 'object' && 'values' in schema
      ? (schema as { values?: unknown[] }).values
      : undefined
  const nodes = coerceEnumTreeNodes(values)
  return nodes.some((n) => Boolean(n.children?.length))
}

export function parseEnumPath(value: unknown): string[] {
  if (value == null || value === '') return []
  if (typeof value === 'boolean') return []
  if (typeof value === 'number' && Number.isFinite(value)) return [String(value)]
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return []
    if (text.includes('/')) return text.split('/').map((p) => p.trim()).filter(Boolean)
    return [text]
  }
  if (Array.isArray(value)) {
    return value.map((v) => String(v ?? '').trim()).filter(Boolean)
  }
  if (typeof value === 'object') {
    const obj = value as { path?: unknown; value?: unknown }
    if (obj.path != null) return parseEnumPath(obj.path)
    if (obj.value != null) return parseEnumPath(obj.value)
  }
  return []
}

function findChild(nodes: EnumTreeNode[], id: string): EnumTreeNode | undefined {
  return nodes.find((n) => n.id === id)
}

function walkFind(nodes: EnumTreeNode[], id: string, trail: string[]): string[] | null {
  for (const n of nodes) {
    const next = [...trail, n.id]
    if (n.id === id) return next
    if (n.children?.length) {
      const found = walkFind(n.children, id, next)
      if (found) return found
    }
  }
  return null
}

export function resolveEnumPath(nodes: EnumTreeNode[], value: unknown): string[] | null {
  const raw = parseEnumPath(value)
  if (!raw.length) return []
  let cursor = nodes
  const walked: string[] = []
  for (let i = 0; i < raw.length; i++) {
    const match = findChild(cursor, raw[i])
    if (!match) {
      if (i === 0 && raw.length === 1) return walkFind(nodes, raw[0], [])
      return null
    }
    walked.push(raw[i])
    cursor = match.children ?? []
  }
  return walked
}

function nodeAtPath(nodes: EnumTreeNode[], path: string[]): EnumTreeNode | undefined {
  let cursor = nodes
  let current: EnumTreeNode | undefined
  for (const segment of path) {
    current = findChild(cursor, segment)
    if (!current) return undefined
    cursor = current.children ?? []
  }
  return current
}

export function enumChildrenAt(nodes: EnumTreeNode[], pathPrefix: string[]): EnumTreeNode[] {
  if (!pathPrefix.length) return nodes
  const node = nodeAtPath(nodes, pathPrefix)
  return node?.children ?? []
}

export type EnumReviewInspect = {
  complete: boolean
  nested: boolean
  path: string[]
  missingLevel: number | null
  message: string | null
}

export function inspectEnumReviewValue(
  schema: unknown,
  value: unknown,
  dtype?: string | null,
): EnumReviewInspect {
  if (!isNestedEnumSchema(schema, dtype)) {
    return { complete: true, nested: false, path: parseEnumPath(value), missingLevel: null, message: null }
  }
  const values =
    schema && typeof schema === 'object' && 'values' in schema
      ? (schema as { values?: unknown[] }).values
      : undefined
  const nodes = coerceEnumTreeNodes(values)
  const raw = parseEnumPath(value)
  if (!raw.length) {
    return {
      complete: false,
      nested: true,
      path: [],
      missingLevel: 1,
      message: '嵌套枚举未完成：值为空，每一级都需要取值',
    }
  }
  const path = resolveEnumPath(nodes, value)
  if (!path) {
    return {
      complete: false,
      nested: true,
      path: raw,
      missingLevel: null,
      message: `嵌套枚举取值无效：${raw.join('/')} 不在选项中`,
    }
  }
  const terminal = nodeAtPath(nodes, path)
  if (terminal?.children?.length) {
    return {
      complete: false,
      nested: true,
      path,
      missingLevel: path.length + 1,
      message: `嵌套枚举未完成：已选 ${path[path.length - 1]}，还需选择第 ${path.length + 1} 级子值`,
    }
  }
  return { complete: true, nested: true, path, missingLevel: null, message: null }
}

export function toStoredEnumReviewValue(schema: unknown, value: unknown, dtype?: string | null): unknown {
  const info = inspectEnumReviewValue(schema, value, dtype)
  if (!info.complete || !info.nested) return value
  if (info.path.length > 1) return info.path
  return info.path[0] ?? value
}

export function formatEnumReviewValue(value: unknown): string {
  const path = parseEnumPath(value)
  if (path.length) return path.join(' / ')
  return ''
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
