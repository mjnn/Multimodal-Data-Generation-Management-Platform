/**
 * Client-side DAG I/O warnings (mirrors hmi.platform.io_contract.diagnose_graph).
 */
import type { PlatformOperator, RecipeGraph, RecipeGraphNode } from '../api/types'
import { mergeNodeBindingsFromEdges } from './recipeGraph'
import {
  asBindingList,
  effectiveProduces,
  expandOutputPorts,
  getOp,
  inputPorts,
  typeCompatible,
} from './recipePipeline'
import { normalizeSourceKind } from './fileKinds'

const CONTROL = new Set(['source', 'if', 'review', 'export'])

function nodeProduces(node: RecipeGraphNode, operators: PlatformOperator[]): string[] {
  if (node.type === 'source') {
    const kinds = ((node.params?.kinds as string[]) || []).map((k) => normalizeSourceKind(k) || k).filter(Boolean)
    return kinds
  }
  const op = getOp(operators, String(node.op_id || node.type || ''))
  return effectiveProduces(
    {
      key: node.key,
      op_id: String(node.op_id || ''),
      params: node.params,
      produces: Array.isArray(node.params?.produces) ? (node.params?.produces as string[]) : undefined,
    },
    op,
  )
}

function providedTypesFromNode(
  up: RecipeGraphNode,
  portId: string,
  operators: PlatformOperator[],
): string[] | null {
  if (up.type === 'if' || up.type === 'review' || up.type === 'export') return ['*']
  if (up.type === 'source') {
    const kinds = nodeProduces(up, operators)
    return kinds.length ? kinds : ['*']
  }
  const produces = nodeProduces(up, operators)
  const upOp = getOp(operators, String(up.op_id || up.type || ''))
  const expanded = expandOutputPorts(upOp, up.params)
  const pid = String(portId || '').trim()
  if (!pid || pid === 'out') return produces
  const hit = expanded.find((p) => p.id === pid)
  if (hit) {
    const types = (hit.types || []).filter(Boolean)
    if (upOp?.expand_outputs_from === 'channel_count') return types.length ? types : [pid]
    if (produces.includes(pid) || types.some((t) => produces.includes(t))) return types.length ? types : [pid]
    return null
  }
  return produces.includes(pid) ? [pid] : null
}

/** Whether a proposed xyflow connection is type-legal (no self-loop, matching ports). */
export function canConnectGraph(
  graph: RecipeGraph,
  operators: PlatformOperator[],
  typeProvides: Record<string, string[]>,
  conn: { source?: string | null; target?: string | null; sourceHandle?: string | null; targetHandle?: string | null },
): boolean {
  const source = String(conn.source || '').trim()
  const target = String(conn.target || '').trim()
  if (!source || !target || source === target) return false
  const src = (graph.nodes || []).find((n) => n.key === source)
  const dst = (graph.nodes || []).find((n) => n.key === target)
  if (!src || !dst) return false
  if (dst.type === 'source') return false
  if (src.type === 'export') return false
  const sourcePort = conn.sourceHandle
    ? graphPortFromHandle(conn.sourceHandle)
    : src.type === 'if'
      ? 'then'
      : 'out'
  const targetPort = conn.targetHandle ? graphPortFromHandle(conn.targetHandle) : 'in'
  if (src.type === 'if' && sourcePort !== 'then' && sourcePort !== 'else') return false
  if (dst.type === 'if' || dst.type === 'review' || dst.type === 'export') {
    return targetPort === 'in'
  }
  const op = getOp(operators, String(dst.op_id || dst.type || ''))
  const ports = inputPorts(op)
  const port = ports.find((p) => (p.id || 'in') === targetPort) || (targetPort === 'in' ? ports[0] : undefined)
  if (!port) return false
  const needed = (port.types || []).filter(Boolean)
  const provided = providedTypesFromNode(src, sourcePort, operators)
  if (!provided) return false
  if (!needed.length || provided.includes('*')) return true
  return provided.some(
    (p) => needed.some((n) => typeCompatible(p, n, typeProvides) || p === n),
  )
}

export function diagnoseGraph(
  graph: RecipeGraph,
  operators: PlatformOperator[],
  typeProvides: Record<string, string[]> = {},
): Record<string, { level: 'ok' | 'warn'; codes: string[]; message: string }> {
  const byKey = new Map((graph.nodes || []).map((n) => [n.key, n]))
  const out: Record<string, { level: 'ok' | 'warn'; codes: string[]; message: string }> = {}
  for (const node of graph.nodes || []) {
    if (CONTROL.has(node.type)) {
      out[node.key] = { level: 'ok', codes: [], message: '' }
      continue
    }
    const op = getOp(operators, String(node.op_id || node.type || ''))
    const bindings = mergeNodeBindingsFromEdges(node, graph)
    const codes: string[] = []
    const parts: string[] = []
    for (const port of inputPorts(op)) {
      const minCount = Math.max(0, Number(port.min_count ?? 1))
      const needed = (port.types || []).filter(Boolean)
      const binds = asBindingList(bindings[port.id || 'in'])
      let ok = 0
      const bad: string[] = []
      for (const bind of binds) {
        let provided: string[] | null = null
        if (bind.kind === 'slot') {
          const src = byKey.get(bind.slot_id)
          provided = src?.type === 'source' ? nodeProduces(src, operators) : null
          if (provided && !provided.length) provided = ['*']
        } else {
          const up = byKey.get(bind.step_key)
          if (!up) provided = null
          else if (up.type === 'if' || up.type === 'review' || up.type === 'export') provided = ['*']
          else {
            const produces = nodeProduces(up, operators)
            const portId = String(bind.port_id || '').trim()
            const upOp = getOp(operators, String(up.op_id || up.type || ''))
            const expanded = expandOutputPorts(upOp, up.params)
            if (!portId || portId === 'out') provided = produces
            else {
              const hit = expanded.find((p) => p.id === portId)
              if (hit) {
                const types = (hit.types || []).filter(Boolean)
                if (upOp?.expand_outputs_from === 'channel_count') {
                  provided = types.length ? types : [portId]
                } else if (produces.includes(portId) || types.some((t) => produces.includes(t))) {
                  provided = types.length ? types : [portId]
                } else {
                  provided = null
                }
              } else {
                provided = produces.includes(portId) ? [portId] : null
              }
            }
          }
        }
        const compatible =
          provided?.includes('*') ||
          (provided || []).some((p) => !needed.length || needed.some((n) => typeCompatible(p, n, typeProvides) || p === n))
        if (provided && compatible) ok += 1
        else bad.push(bind.kind === 'slot' ? bind.slot_id : `${bind.step_key}.${bind.port_id || 'out'}`)
      }
      if (ok < minCount) {
        codes.push('min_input')
        parts.push(`最少需要 ${minCount} 路「${port.title || port.id}」，当前 ${ok} 路`)
      }
      if (bad.length) {
        codes.push('unbound_kind')
        parts.push(`输入不在上游产物或数据源内：${bad.join('、')}`)
      }
    }
    if (node.op_id === 'label_tree_input') {
      const rows = Array.isArray(node.params?.assignments) ? node.params.assignments : []
      if (!rows.length) {
        codes.push('empty_assignments')
        parts.push('标签树输入还没有条目')
      }
    }
    const allowed = new Set(
      expandOutputPorts(op, node.params).flatMap((p) => [p.id, ...(p.types || [])].filter(Boolean)),
    )
    const selected = nodeProduces(node, operators)
    if (allowed.size && selected.some((p) => !allowed.has(p))) {
      codes.push('bad_produces')
      parts.push('期望输出不在组件可输出列表内')
    }
    const uniq = [...new Set(codes)]
    out[node.key] = {
      level: uniq.length ? 'warn' : 'ok',
      codes: uniq,
      message: parts.join('；'),
    }
  }
  return out
}

export function rfHandleId(port: string): string {
  const p = String(port || 'out').trim() || 'out'
  if (p.startsWith('.')) return `dot-${p.slice(1)}`
  return p
}

export function graphPortFromHandle(handle: string | null | undefined): string {
  const h = String(handle || '').trim()
  if (!h) return 'out'
  if (h.startsWith('dot-')) return `.${h.slice(4)}`
  return h
}

export function outputHandleSpecs(
  node: RecipeGraphNode,
  operators: PlatformOperator[],
): Array<{ id: string; title: string }> {
  if (node.type === 'if') return []
  if (node.type === 'export') return []
  const op = getOp(operators, String(node.op_id || node.type || ''))
  const ports = expandOutputPorts(op, node.params)
  if (op?.expand_outputs_from === 'channel_count') {
    return ports.map((p) => ({ id: rfHandleId(p.id), title: p.title || p.id }))
  }
  if (ports.length <= 1) return [{ id: 'out', title: ports[0]?.title || 'out' }]
  const produces = new Set(nodeProduces(node, operators))
  const named = ports
    .filter((p) => produces.has(p.id) || (p.types || []).some((t) => produces.has(t)))
    .map((p) => ({ id: rfHandleId(p.id), title: p.title || p.id }))
  if (named.length <= 1) return [{ id: 'out', title: named[0]?.title || 'out' }]
  return [{ id: 'out', title: '全部' }, ...named]
}
