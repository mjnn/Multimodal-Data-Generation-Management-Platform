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
import { asBindingList, displayNodeTitle, effectiveProduces, getOp, isGenericNodeTitle, isLegacyHydrateKey, newSourceCard, typeLabel, uniqueCatalogKey } from './recipePipeline'

const COPY_SUFFIX = '-copy'

/** AI打标器 or 标签树输入 both write labels_tree. */
export function isLabelsSink(n: { type?: string; op_id?: string } | null | undefined): boolean {
  if (!n) return false
  return n.type === 'label' || n.op_id === 'label_tree_input'
}

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
        title: 'AI打标器',
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

function bindingRefs(node: RecipeGraphNode): string[] {
  const refs: string[] = []
  for (const raw of Object.values(node.bindings || {})) {
    for (const bind of asBindingList(raw)) {
      if (bind.kind === 'slot' && bind.slot_id) refs.push(bind.slot_id)
      if (bind.kind === 'upstream' && bind.step_key) refs.push(bind.step_key)
    }
  }
  return refs
}

function bindingFromSourceNode(src: RecipeGraphNode, sourcePort: string): PipelineBinding {
  if (src.type === 'source') return { kind: 'slot', slot_id: src.key }
  const port = sourcePort && sourcePort !== 'out' ? sourcePort : undefined
  return port
    ? { kind: 'upstream', step_key: src.key, port_id: port }
    : { kind: 'upstream', step_key: src.key }
}

/** Incoming canvas edges win over stale inspector bindings on the same port. */
export function mergeNodeBindingsFromEdges(
  node: RecipeGraphNode,
  graph: RecipeGraph,
): Record<string, PipelinePortBindings> {
  const byKey = new Map((graph.nodes || []).map((n) => [n.key, n]))
  const merged: Record<string, PipelinePortBindings> = { ...(node.bindings || {}) }
  const grouped = new Map<string, PipelineBinding[]>()
  for (const e of graph.edges || []) {
    if (e.target !== node.key) continue
    const src = byKey.get(e.source)
    if (!src) continue
    const port = e.target_port || 'in'
    const list = grouped.get(port) || []
    list.push(bindingFromSourceNode(src, e.source_port || 'out'))
    grouped.set(port, list)
  }
  for (const [port, binds] of grouped) {
    merged[port] = binds.length === 1 ? binds[0]! : binds
  }
  return merged
}

export function dropBindingsToRemoved(graph: RecipeGraph, removed: Set<string>): RecipeGraphNode[] {
  return (graph.nodes || [])
    .filter((n) => !removed.has(n.key))
    .map((n) => {
      if (!n.bindings) return n
      let changed = false
      const next: Record<string, PipelinePortBindings> = {}
      for (const [pid, raw] of Object.entries(n.bindings)) {
        const kept = asBindingList(raw).filter((b) => {
          const ref = b.kind === 'slot' ? b.slot_id : b.step_key
          return !removed.has(String(ref || ''))
        })
        if (kept.length !== asBindingList(raw).length) changed = true
        if (kept.length === 1) next[pid] = kept[0]!
        else if (kept.length > 1) next[pid] = kept
      }
      return changed ? { ...n, bindings: next } : n
    })
}

function nodeToStep(node: RecipeGraphNode, graph: RecipeGraph): PipelineStep | null {
  const key = String(node.key || '').trim()
  if (!key) return null
  if (node.type === 'if' || node.type === 'review' || node.type === 'export') return null
  const params = { ...(node.params || {}) }
  if (node.type === 'source') {
    const kinds = Array.isArray(params.kinds) ? params.kinds.map((x) => String(x)) : ['.mp4']
    return newSourceCard({
      key,
      title: String(node.title || key),
      kinds: kinds.length ? kinds : ['.mp4'],
      cardinality_min: Number(params.cardinality_min ?? 1) || 1,
      cardinality_max: Number(params.cardinality_max ?? 1) || 1,
      required: params.required !== false,
    })
  }
  const opId = String(node.op_id || (node.type === 'label' ? 'label' : '')).trim()
  if (!opId) return null
  return {
    key,
    op_id: opId,
    title: String(node.title || key),
    role: node.type === 'label' || opId === 'label' ? 'stage' : 'preprocess',
    params,
    required: Boolean(params.required),
    bindings: mergeNodeBindingsFromEdges(node, graph),
    produces: Array.isArray(params.produces)
      ? (params.produces as string[]).filter(Boolean)
      : Array.isArray(params.emit_modalities)
        ? (params.emit_modalities as string[]).filter(Boolean)
        : undefined,
    bbox_enabled: opId === 'detect_bbox' ? params.bbox_enabled !== false : undefined,
  }
}

/** Rewrite linear hydrate aliases (prep-N-op / stage-embed) to catalog operator ids. */
export function catalogizeGraph(graph: RecipeGraph, operators: PlatformOperator[] = []): RecipeGraph {
  const nodes = graph.nodes || []
  const used = new Set<string>()
  for (const n of nodes) {
    if (n.key && !isLegacyHydrateKey(n.key)) used.add(n.key)
  }
  const keymap = new Map<string, string>()
  const remapped: RecipeGraphNode[] = nodes.map((n) => {
    const old = String(n.key || '')
    const opId = String(n.op_id || (n.type === 'label' ? 'label' : ''))
    let nextKey = old
    if (isLegacyHydrateKey(old)) {
      let preferred = opId || old
      if (old === 'stage-embed') preferred = opId || 'embed'
      nextKey = uniqueCatalogKey(preferred, used)
    }
    keymap.set(old, nextKey)
    const stored = String(n.title || '')
    const title =
      n.type !== 'source' && opId && isGenericNodeTitle(stored, opId, old)
        ? displayNodeTitle({ ...n, key: nextKey, title: '' }, operators) || stored || nextKey
        : n.type !== 'source' && opId && isGenericNodeTitle(stored, opId, nextKey)
          ? displayNodeTitle({ ...n, key: nextKey, title: '' }, operators) || stored || nextKey
          : stored || n.title
    return { ...n, key: nextKey, title }
  })
  const withBindings = remapped.map((n) => {
    if (!n.bindings && !n.condition) return n
    const bindings = n.bindings
      ? Object.fromEntries(Object.entries(n.bindings).map(([pid, raw]) => [pid, remapPortBindings(raw, keymap)!]))
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
    return { ...n, bindings, condition }
  })
  return {
    ...graph,
    nodes: withBindings,
    edges: (graph.edges || []).map((e) => {
      const source = keymap.get(e.source) ?? e.source
      const target = keymap.get(e.target) ?? e.target
      return {
        ...e,
        id: `${source}-${e.source_port}->${target}-${e.target_port}`,
        source,
        target,
      }
    }),
  }
}

/** Build a linear graph from pipeline steps (source/op/label chain, y+=96). */
export function hydrateGraphFromSteps(steps: PipelineStep[], operators: PlatformOperator[] = []): RecipeGraph {
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
      title: ntype === 'source' ? String(step.title || key) : displayNodeTitle({ key, type: ntype, op_id: opId, title: step.title }, operators),
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

  if (!nodes.some((n) => isLabelsSink(n))) {
    nodes.push({
      key: 'stage-label',
      type: 'label',
      op_id: 'label',
      title: 'AI打标器',
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

  return catalogizeGraph({ nodes, edges }, operators)
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
  const seen = new Set<string>()
  const add = (src: string, tgt: string) => {
    const id = `${src}->${tgt}`
    if (!src || !tgt || src === tgt || seen.has(id)) return
    if (!adj.has(src) || !indeg.has(tgt)) return
    seen.add(id)
    adj.get(src)!.push(tgt)
    indeg.set(tgt, (indeg.get(tgt) || 0) + 1)
  }
  for (const e of graph.edges || []) add(e.source, e.target)
  for (const n of nodes) {
    for (const ref of bindingRefs(n)) add(ref, n.key)
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

/** Derive linear compile steps from canvas (topo order; skip if/review/export). */
export function graphToSteps(graph: RecipeGraph): PipelineStep[] {
  const steps: PipelineStep[] = []
  for (const node of orderedGraphNodes(graph)) {
    const step = nodeToStep(node, graph)
    if (step) steps.push(step)
  }
  return steps
}

/** True if graph has branching / non-chain node types that cannot round-trip to linear steps. */
export function graphIsLossy(graph: RecipeGraph): boolean {
  return (graph.nodes || []).some((n) => n.type === 'if' || n.type === 'review' || n.type === 'export')
}

/** Prefer existing graph when present; otherwise hydrate a chain from editor steps. */
export function recipeGraphFromEditor(
  existingGraph: RecipeGraph | null | undefined,
  steps: PipelineStep[],
  operators: PlatformOperator[] = [],
): RecipeGraph {
  if (existingGraph?.nodes?.length) {
    return attachStepBindings(catalogizeGraph(existingGraph, operators), steps)
  }
  return hydrateGraphFromSteps(steps, operators)
}

function slotOnlyBindings(
  raw: Record<string, PipelinePortBindings> | undefined,
): Record<string, PipelinePortBindings> {
  const next: Record<string, PipelinePortBindings> = {}
  for (const [pid, val] of Object.entries(raw || {})) {
    const slots = asBindingList(val).filter((b) => b.kind === 'slot')
    if (!slots.length) continue
    next[pid] = slots.length === 1 ? slots[0]! : slots
  }
  return next
}

/** Copy source-lake slot bindings onto matching graph nodes when the node has none.
 * Never stamp DAG-upstream `up:` products into inspector 输入. */
export function attachStepBindings(graph: RecipeGraph, steps: PipelineStep[]): RecipeGraph {
  const byKey = new Map(steps.map((s) => [s.key, s]))
  return {
    ...graph,
    nodes: (graph.nodes || []).map((n) => {
      const existingSlots = slotOnlyBindings(n.bindings)
      if (Object.keys(existingSlots).length) return { ...n, bindings: existingSlots }
      const step = byKey.get(n.key)
      const slots = slotOnlyBindings(step?.bindings)
      if (!Object.keys(slots).length) return { ...n, bindings: existingSlots }
      return { ...n, bindings: slots }
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
