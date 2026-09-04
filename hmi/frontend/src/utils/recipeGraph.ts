/**
 * Client-side recipe.graph helpers (mirror backend hydrate_graph chain rules).
 * Validation still happens on the server; this only hydrates positions + types for save/editor.
 */
import type {
  GraphCondition,
  PipelineBinding,
  PipelinePortBindings,
  PipelineStep,
  PlatformOperator,
  RecipeGraph,
  RecipeGraphEdge,
  RecipeGraphNode,
} from '../api/types'
import { effectiveProduces, getOp, newSourceCard, typeLabel } from './recipePipeline'

const COPY_SUFFIX = '-copy'

function remapBinding(b: PipelineBinding, keymap: Map<string, string>): PipelineBinding {
  if (b.kind === 'slot' && keymap.has(b.slot_id)) return { ...b, slot_id: keymap.get(b.slot_id)! }
  if (b.kind === 'upstream' && keymap.has(b.step_key)) return { ...b, step_key: keymap.get(b.step_key)! }
  return b
}

function remapPortBindings(
  raw: PipelinePortBindings | undefined,
  keymap: Map<string, string>,
): PipelinePortBindings | undefined {
  if (!raw) return raw
  return Array.isArray(raw) ? raw.map((b) => remapBinding(b, keymap)) : remapBinding(raw, keymap)
}

/** Default canvas for a new recipe: one source, one label, one edge. */
export function defaultNewGraph(): RecipeGraph {
  return {
    nodes: [
      {
        key: 'src-1',
        type: 'source',
        op_id: 'source',
        title: '数据源',
        params: { kinds: ['.mp4'], required: true, cardinality_min: 1, cardinality_max: 1 },
        position: { x: 80, y: 0 },
      },
      {
        key: 'stage-label',
        type: 'label',
        op_id: 'label',
        title: '打标器',
        params: { model: 'default' },
        position: { x: 80, y: 96 },
      },
    ],
    edges: [
      {
        id: 'src-1->stage-label',
        source: 'src-1',
        source_port: 'out',
        target: 'stage-label',
        target_port: 'in',
      },
    ],
  }
}

/** Derive linear compile steps from canvas (source/op/label only; skip if/review/export). */
export function graphToSteps(graph: RecipeGraph): PipelineStep[] {
  const steps: PipelineStep[] = []
  for (const node of graph.nodes || []) {
    const key = String(node.key || '').trim()
    if (!key) continue
    if (node.type === 'if' || node.type === 'review' || node.type === 'export') continue
    const params = { ...(node.params || {}) }
    if (node.type === 'source') {
      const kinds = Array.isArray(params.kinds) ? params.kinds.map((x) => String(x)) : ['.mp4']
      steps.push(
        newSourceCard({
          key,
          title: String(node.title || key),
          kinds: kinds.length ? kinds : ['.mp4'],
          cardinality_min: Number(params.cardinality_min ?? 1) || 1,
          cardinality_max: Number(params.cardinality_max ?? 1) || 1,
          required: params.required !== false,
        }),
      )
      continue
    }
    const opId = String(node.op_id || (node.type === 'label' ? 'label' : '')).trim()
    if (!opId) continue
    steps.push({
      key,
      op_id: opId,
      title: String(node.title || key),
      role: node.type === 'label' || opId === 'label' ? 'stage' : 'preprocess',
      params,
      required: Boolean(params.required),
      bindings: { ...(node.bindings || {}) },
      bbox_enabled: opId === 'detect_bbox' ? params.bbox_enabled !== false : undefined,
    })
  }
  return steps
}

/** Build a linear graph from pipeline steps (source/op/label chain, y+=96). */
export function hydrateGraphFromSteps(steps: PipelineStep[]): RecipeGraph {
  const nodes: RecipeGraphNode[] = []
  const edges: RecipeGraphEdge[] = []
  let prev: string | null = null
  let y = 0

  for (const step of steps) {
    const key = String(step.key || '').trim()
    if (!key) continue
    const opId = String(step.op_id || '')
    let ntype: RecipeGraphNode['type']
    if (step.card_kind === 'source' || opId === 'source') {
      ntype = 'source'
    } else if (opId === 'label') {
      ntype = 'label'
    } else {
      ntype = 'op'
    }

    const params: Record<string, unknown> = { ...(step.params || {}) }
    if (ntype === 'source') {
      if (step.kinds != null) params.kinds = [...(step.kinds || [])]
      if (params.required === undefined) params.required = step.required !== false
      if (step.cardinality_min != null) params.cardinality_min = Number(step.cardinality_min) || 1
      if (step.cardinality_max != null) params.cardinality_max = Number(step.cardinality_max) || 1
    }

    nodes.push({
      key,
      type: ntype,
      op_id: opId || ntype,
      title: String(step.title || key),
      params,
      bindings: { ...(step.bindings || {}) },
      position: { x: 80, y },
    })

    if (prev) {
      edges.push({
        id: `${prev}->${key}`,
        source: prev,
        source_port: 'out',
        target: key,
        target_port: 'in',
      })
    }
    prev = key
    y += 96
  }

  if (!nodes.some((n) => n.type === 'label')) {
    nodes.push({
      key: 'stage-label',
      type: 'label',
      op_id: 'label',
      title: '打标器',
      params: {},
      position: { x: 80, y },
    })
    if (prev) {
      edges.push({
        id: `${prev}->stage-label`,
        source: prev,
        source_port: 'out',
        target: 'stage-label',
        target_port: 'in',
      })
    }
  }

  return { nodes, edges }
}

export function applyNodeParamOverrides(
  graph: RecipeGraph,
  overrides: Record<string, { params?: Record<string, unknown>; condition?: GraphCondition | null }> | undefined,
): RecipeGraph {
  const raw = overrides || {}
  return {
    ...graph,
    nodes: (graph.nodes || []).map((n) => {
      const ov = raw[n.key]
      if (!ov) return n
      const next = { ...n }
      if (ov.params && typeof ov.params === 'object') {
        next.params = { ...(n.params || {}), ...ov.params }
      }
      if (n.type === 'if' && 'condition' in ov) {
        next.condition = ov.condition || undefined
      }
      return next
    }),
  }
}

export function orderedGraphNodes(graph: RecipeGraph): RecipeGraphNode[] {
  const nodes = graph.nodes || []
  const orig = nodes.map((n) => n.key)
  const byKey = new Map(nodes.map((n) => [n.key, n]))
  const indeg = new Map(orig.map((k) => [k, 0]))
  const adj = new Map(orig.map((k) => [k, [] as string[]]))
  for (const e of graph.edges || []) {
    if (!adj.has(e.source) || !indeg.has(e.target)) continue
    adj.get(e.source)!.push(e.target)
    indeg.set(e.target, (indeg.get(e.target) || 0) + 1)
  }
  const ready = orig.filter((k) => (indeg.get(k) || 0) === 0)
  const out: string[] = []
  while (ready.length) {
    const key = ready.shift()!
    out.push(key)
    for (const t of adj.get(key) || []) {
      const next = (indeg.get(t) || 0) - 1
      indeg.set(t, next)
      if (next === 0) ready.push(t)
    }
    ready.sort((a, b) => orig.indexOf(a) - orig.indexOf(b))
  }
  const keys = out.length === orig.length ? out : orig
  return keys.map((k) => byKey.get(k)!).filter(Boolean)
}

/** True if graph has branching / non-chain node types that cannot round-trip to linear steps. */
export function graphIsLossy(graph: RecipeGraph): boolean {
  return (graph.nodes || []).some((n) => n.type === 'if' || n.type === 'review' || n.type === 'export')
}

/** Prefer existing graph when present; otherwise hydrate a chain from editor steps. */
export function recipeGraphFromEditor(
  existingGraph: RecipeGraph | null | undefined,
  steps: PipelineStep[],
): RecipeGraph {
  if (existingGraph?.nodes?.length) return attachStepBindings(existingGraph, steps)
  return hydrateGraphFromSteps(steps)
}

/** Copy compiled-step bindings onto matching graph nodes when the node has none. */
export function attachStepBindings(graph: RecipeGraph, steps: PipelineStep[]): RecipeGraph {
  const byKey = new Map(steps.map((s) => [s.key, s]))
  return {
    ...graph,
    nodes: (graph.nodes || []).map((n) => {
      const step = byKey.get(n.key)
      if (!step?.bindings || (n.bindings && Object.keys(n.bindings).length)) return n
      return { ...n, bindings: { ...step.bindings } }
    }),
  }
}

/** Clone a canvas graph with unique node keys (keeps if/review/export topology). */
export function remapGraphKeys(graph: RecipeGraph, suffix = COPY_SUFFIX): RecipeGraph {
  const keymap = new Map((graph.nodes || []).map((n) => [n.key, `${n.key}${suffix}`]))
  const remapKey = (k: string) => keymap.get(k) ?? k
  return {
    nodes: (graph.nodes || []).map((n) => {
      const bindings = n.bindings
        ? Object.fromEntries(
            Object.entries(n.bindings).map(([pid, raw]) => [pid, remapPortBindings(raw, keymap)!]),
          )
        : n.bindings
      const condition = n.condition
        ? {
            all: (n.condition.all || []).map((pred) => {
              if (pred.field === 'source.slot_id' && typeof pred.value === 'string' && keymap.has(pred.value)) {
                return { ...pred, value: keymap.get(pred.value) }
              }
              return { ...pred }
            }),
          }
        : n.condition
      return { ...n, key: remapKey(n.key), bindings, condition }
    }),
    edges: (graph.edges || []).map((e) => ({
      ...e,
      id: `${remapKey(e.source)}-${e.source_port}->${remapKey(e.target)}-${e.target_port}`,
      source: remapKey(e.source),
      target: remapKey(e.target),
    })),
  }
}

/** Nodes that can reach `startKey` along incoming edges (does not include startKey). */
export function ancestorNodeKeys(graph: RecipeGraph, startKey: string): Set<string> {
  const incoming = new Map<string, string[]>()
  for (const e of graph.edges || []) {
    const t = String(e.target || '')
    const s = String(e.source || '')
    if (!t || !s) continue
    const list = incoming.get(t) || []
    list.push(s)
    incoming.set(t, list)
  }
  const seen = new Set<string>()
  const stack = [...(incoming.get(startKey) || [])]
  while (stack.length) {
    const k = stack.pop()!
    if (seen.has(k)) continue
    seen.add(k)
    for (const pred of incoming.get(k) || []) stack.push(pred)
  }
  return seen
}

export type ExportProductOption = { value: string; label: string }

/** Product ids from nodes upstream of an export. If the export has no incoming edge yet, list all op/label products on the canvas. */
export function upstreamProductOptions(
  graph: RecipeGraph,
  exportKey: string,
  operators: PlatformOperator[],
): ExportProductOption[] {
  const ancestors = ancestorNodeKeys(graph, exportKey)
  const pool = (graph.nodes || []).filter((n) => {
    if (n.key === exportKey) return false
    if (n.type === 'export' || n.type === 'review' || n.type === 'if' || n.type === 'source') return false
    if (ancestors.size) return ancestors.has(n.key)
    return n.type === 'op' || n.type === 'label'
  })
  const seen = new Set<string>()
  const options: ExportProductOption[] = []
  for (const node of pool) {
    const opId = String(node.op_id || (node.type === 'label' ? 'label' : ''))
    const ids =
      node.type === 'label'
        ? ['labels_tree']
        : effectiveProduces({ key: node.key, op_id: opId, params: node.params }, getOp(operators, opId))
    const title = String(node.title || opId || node.key)
    for (const id of ids) {
      if (!id || seen.has(id)) continue
      seen.add(id)
      options.push({ value: id, label: `${title} · ${typeLabel(id)}` })
    }
  }
  return options
}
