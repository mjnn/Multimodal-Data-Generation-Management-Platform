/**
 * DataType editor: ordered SDK component cards ↔ recipe preprocess/stages/bbox.
 * Mirrors hmi/backend/hmi/platform/recipe_pipeline.py
 */
import type {
  DataTypePreprocessStep,
  DataTypeProduct,
  DataTypeRecipe,
  DataTypeSlot,
  PipelineBinding,
  PipelinePortBindings,
  PipelineStep,
  PlatformOperator,
  OperatorPort,
} from '../api/types'

import {
  PARSE_BAG_MODALITIES,
  SOURCE_KINDS,
  normalizeParseBagModality,
  normalizeSourceKind,
} from './fileKinds'

export { PARSE_BAG_MODALITIES }
export type { ParseBagModality } from './fileKinds'

const OMNI_PROMPT_KEYS = [
  'system_role',
  'output_instruction',
  'json_format_hint',
  'labeling_rules',
  'labels_section_title',
  'user_task_intro',
  'user_modality_hint',
  'user_taxonomy_task',
  'user_asr_hint',
  'user_bbox_hint',
] as const

const EXTRA_KEYS_BY_MODEL: Record<string, readonly string[]> = {
  default: ['omni_model_id', 'omni_label_prompt', 'bbox_in_label_prompt', 'temperature', 'max_tokens'],
  nvh_sem_ast: ['ast_top_k', 'reference_constraints'],
  nvh_sem_heuristic: ['reference_constraints'],
  nvh_sem_vl: ['vl_prompt', 'vl_model', 'reference_constraints'],
}

function compactOmniPrompt(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const allowed = new Set<string>(OMNI_PROMPT_KEYS)
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!allowed.has(k) || v == null) continue
    const text = String(v).trim()
    if (text) out[k] = text
  }
  return out
}

export function labelStageExtras(params: Record<string, unknown> | undefined): Record<string, unknown> {
  const p = params || {}
  const model = String(p.model || '').trim() || 'default'
  const allowed = new Set(EXTRA_KEYS_BY_MODEL[model] || EXTRA_KEYS_BY_MODEL.default)
  const out: Record<string, unknown> = {}
  for (const key of allowed) {
    if (!(key in p) || p[key] == null) continue
    const v = p[key]
    if (key === 'omni_label_prompt') {
      const nested = compactOmniPrompt(v)
      if (Object.keys(nested).length) out.omni_label_prompt = nested
      continue
    }
    if (key === 'bbox_in_label_prompt') {
      if (typeof v === 'boolean') out.bbox_in_label_prompt = v
      continue
    }
    if (key === 'temperature') {
      const n = typeof v === 'number' ? v : Number(v)
      if (Number.isFinite(n)) out.temperature = n
      continue
    }
    if (key === 'max_tokens' || key === 'ast_top_k') {
      const n = typeof v === 'number' ? v : Number(v)
      if (Number.isFinite(n)) out[key] = Math.trunc(n)
      continue
    }
    if (typeof v === 'string') {
      const text = v.trim()
      if (text) out[key] = text
      continue
    }
  }
  return out
}

export const CATEGORY_ORDER = ['parse', 'encode', 'audio', 'detect_ai'] as const

export const CATEGORY_TITLES: Record<string, string> = {
  parse: '解析',
  encode: '编码与变换',
  audio: '音频分析',
  detect_ai: '检测与 AI',
}

export function typeCompatible(
  provided: string,
  needed: string,
  typeProvides: Record<string, string[]> = {},
): boolean {
  if (!provided || !needed) return false
  const p = normalizeSourceKind(provided) || provided
  const n = normalizeSourceKind(needed) || needed
  if (p === n) return true
  return (typeProvides[p] || typeProvides[provided] || []).includes(n)
}

export function getOp(operators: PlatformOperator[], opId: string): PlatformOperator | undefined {
  return operators.find((op) => op.op_id === opId)
}

export function inputPorts(op: PlatformOperator | undefined): OperatorPort[] {
  if (!op) return [{ id: 'in', types: [] }]
  if (op.input_ports?.length) return op.input_ports
  return [{ id: 'in', types: [...(op.input_kinds || [])] }]
}

export function outputPorts(op: PlatformOperator | undefined): OperatorPort[] {
  if (!op) return [{ id: 'out', types: [] }]
  if (op.output_ports?.length) return op.output_ports
  return [{ id: 'out', types: op.product ? [op.product] : [] }]
}

export function channelCountFromParams(params?: Record<string, unknown> | null): number {
  const raw = params?.channel_count ?? 1
  const n = typeof raw === 'number' ? raw : Number(raw)
  if (!Number.isFinite(n)) return 1
  return Math.max(1, Math.min(16, Math.trunc(n)))
}

export function expandOutputPorts(
  op: PlatformOperator | undefined,
  params?: Record<string, unknown> | null,
): OperatorPort[] {
  const template = outputPorts(op)
  if (!op || op.expand_outputs_from !== 'channel_count') return template
  const t0 = template[0] || { id: 'out', types: [] }
  const titles =
    params?.port_titles && typeof params.port_titles === 'object' && !Array.isArray(params.port_titles)
      ? (params.port_titles as Record<string, unknown>)
      : {}
  const n = channelCountFromParams(params)
  const baseTitle = String(t0.title || '').trim()
  const out: OperatorPort[] = []
  for (let i = 1; i <= n; i += 1) {
    const id = `ch${i}`
    const custom = String(titles[id] ?? '').trim()
    out.push({
      ...t0,
      id,
      types: [...(t0.types || [])],
      title: custom || (baseTitle ? `${baseTitle} ${i}` : id),
      channel_index: i - 1,
    })
  }
  return out
}

export function asBindingList(raw: PipelinePortBindings | undefined | null): PipelineBinding[] {
  if (!raw) return []
  return Array.isArray(raw) ? raw.filter(Boolean) : [raw]
}

export function defaultProduces(op: PlatformOperator | undefined): string[] {
  if (!op) return []
  if (op.op_id === 'parse_bag') return [...PARSE_BAG_MODALITIES]
  const names = (op.output_ports || [])
    .map((p) => p.types?.[0])
    .filter((x): x is string => Boolean(x))
  if (names.length) return names
  return op.product ? [op.product] : []
}

export function parseBagEmitModalities(params?: Record<string, unknown>): string[] | null {
  if (!params || !('emit_modalities' in params)) return null
  const raw = params.emit_modalities
  const out: string[] = []
  if (Array.isArray(raw)) {
    for (const item of raw) {
      const m = normalizeParseBagModality(String(item || ''))
      if (m && !out.includes(m)) out.push(m)
    }
  }
  return out
}

export function effectiveProduces(step: PipelineStep, op?: PlatformOperator): string[] {
  if (step.op_id === 'parse_bag') {
    const selected = parseBagEmitModalities(step.params)
    if (selected !== null) return selected
    const stored = (step.produces || []).filter(Boolean)
    const mapped: string[] = []
    for (const item of stored) {
      const m = normalizeParseBagModality(item)
      if (m && !mapped.includes(m)) mapped.push(m)
    }
    if (!stored.length || (stored.length === 1 && stored[0] === 'frames_audio_topics')) {
      return [...PARSE_BAG_MODALITIES]
    }
    if (mapped.length) return mapped
    return [...PARSE_BAG_MODALITIES]
  }
  const stored = (step.produces || []).filter(Boolean)
  if (stored.length) return stored
  return defaultProduces(op)
}

export function isSourceCard(card: PipelineStep | null | undefined): boolean {
  if (!card) return false
  return card.card_kind === 'source' || card.op_id === 'source'
}

export function isLabelCard(card: PipelineStep | null | undefined): boolean {
  return Boolean(card && card.op_id === 'label')
}

export function isLabelsTreeCard(card: PipelineStep | null | undefined): boolean {
  return Boolean(card && (card.op_id === 'label' || card.op_id === 'label_tree_input'))
}

/** If AI打标器 exists, keep it last. Fill-only graphs stay as-is. */
export function pinLabelLast(steps: PipelineStep[]): PipelineStep[] {
  const labels = steps.filter(isLabelCard)
  if (!labels.length) return steps
  const rest = steps.filter((s) => !isLabelCard(s))
  return [...rest, labels[labels.length - 1]]
}

export function duplicateSourceTitleError(steps: PipelineStep[]): string | null {
  const seen = new Set<string>()
  for (const card of steps) {
    if (!isSourceCard(card)) continue
    const title = String(card.title || card.key || '').trim()
    if (!title) return '请填写数据源名称'
    const key = title.toLowerCase()
    if (seen.has(key)) return '数据源名称不能重复'
    seen.add(key)
  }
  return null
}

export function newSourceCard(args: {
  key: string
  title: string
  kinds: string[]
  cardinality_min?: number
  cardinality_max?: number
  required?: boolean
}): PipelineStep {
  const kinds = [...args.kinds]
  return {
    key: args.key,
    card_kind: 'source',
    op_id: 'source',
    title: args.title,
    kinds,
    cardinality_min: args.cardinality_min ?? 1,
    cardinality_max: args.cardinality_max ?? 1,
    required: args.required !== false,
    produces: [...kinds],
    bindings: {},
  }
}

export function slotsFromSteps(steps: PipelineStep[]): DataTypeSlot[] {
  const out: DataTypeSlot[] = []
  for (const card of steps) {
    if (!isSourceCard(card)) continue
    const key = String(card.key || '').trim()
    if (!key) continue
    const title = String(card.title || key).trim() || key
    out.push({
      id: key,
      title,
      kinds: [...(card.kinds || [])],
      cardinality_min: Number(card.cardinality_min ?? 1),
      cardinality_max: Number(card.cardinality_max ?? 1),
      required: card.required !== false,
      role: 'input',
    })
  }
  return out
}

/** Bindings may only point at cards that appear earlier in the list. */
export function assertUpwardBindings(steps: PipelineStep[]): void {
  const keyToIndex = new Map<string, number>()
  steps.forEach((card, i) => {
    const key = String(card.key || '').trim()
    if (key) keyToIndex.set(key, i)
  })
  steps.forEach((card, i) => {
    const bindings = card.bindings || {}
    for (const raw of Object.values(bindings)) {
      for (const bind of asBindingList(raw)) {
        const refs: string[] = []
        if (bind.kind === 'slot' && bind.slot_id) refs.push(bind.slot_id)
        if (bind.kind === 'upstream' && bind.step_key) refs.push(bind.step_key)
        for (const ref of refs) {
          const idx = keyToIndex.get(ref)
          if (idx === undefined) continue
          if (idx >= i) {
            throw new Error(`binding ${JSON.stringify(ref)} must reference a card above the current step`)
          }
        }
      }
    }
  })
}

function singletonKindGroups(...exts: string[]): string[][] {
  return exts.filter(Boolean).map((e) => [e])
}

function requireAnyKindsFromSlots(slots: DataTypeSlot[]): string[][] {
  const required = slots.filter((s) => s.required && s.kinds?.length)
  const pool = required.length ? required : slots.filter((s) => s.kinds?.length)
  const groups: string[][] = []
  for (const slot of pool) {
    groups.push(...singletonKindGroups(...(slot.kinds || [])))
  }
  return groups
}

export function stripOutputLabels(
  labels: Record<string, string> | undefined,
  produces: string[],
): Record<string, string> | undefined {
  if (!labels) return undefined
  const allowed = new Set(produces)
  const clean: Record<string, string> = {}
  for (const [key, value] of Object.entries(labels)) {
    const name = String(value || '').trim()
    if (allowed.has(key) && name) clean[key] = name
  }
  return Object.keys(clean).length ? clean : undefined
}

export function nextSourceTitle(steps: PipelineStep[], base = '数据源'): string {
  const used = new Set(
    steps
      .filter(isSourceCard)
      .map((s) => String(s.title || '').trim().toLowerCase())
      .filter(Boolean),
  )
  if (!used.has(base.toLowerCase())) return base
  let n = 2
  while (used.has(`${base} ${n}`.toLowerCase())) n += 1
  return `${base} ${n}`
}

function whenKindFromSlot(slot: DataTypeSlot | undefined): string | null {
  const kinds = (slot?.kinds || [])
    .map((k) => normalizeSourceKind(k) || k.trim().toLowerCase())
    .filter((k) => SOURCE_KINDS.has(k))
  return kinds.length === 1 ? kinds[0] : null
}

function hydrateBindings(
  inputs: string[],
  slots: DataTypeSlot[],
  produceIndex: Map<string, { stepKey: string; portId: string }>,
  op: PlatformOperator | undefined,
): Record<string, PipelinePortBindings> {
  const ports = inputPorts(op)
  const slotIds = new Set(slots.map((s) => s.id).filter(Boolean))
  const bindings: Record<string, PipelinePortBindings> = {}
  const one = (inp: string): PipelineBinding => {
    const up = produceIndex.get(inp)
    if (slotIds.has(inp)) return { kind: 'slot', slot_id: inp }
    if (up) return { kind: 'upstream', step_key: up.stepKey, port_id: up.portId }
    return { kind: 'slot', slot_id: inp }
  }
  const multi = Boolean(ports[0]?.multiple) && ports.length === 1
  if (multi) {
    const pid = ports[0]?.id || 'in'
    const acc = inputs.map((raw) => String(raw || '').trim()).filter(Boolean).map(one)
    if (acc.length) bindings[pid] = acc
    return bindings
  }
  inputs.forEach((raw, i) => {
    const inp = String(raw || '').trim()
    if (!inp) return
    const port = ports[i] ?? ports[ports.length - 1]
    const pid = port?.id || 'in'
    bindings[pid] = one(inp)
  })
  return bindings
}

function autoBindings(
  op: PlatformOperator | undefined,
  slots: DataTypeSlot[],
  upstream: PipelineStep[],
  operators: PlatformOperator[],
  typeProvides: Record<string, string[]>,
): { bindings: Record<string, PipelinePortBindings>; whenKind: string | null } {
  const bindings: Record<string, PipelinePortBindings> = {}
  let whenKind: string | null = null
  for (const port of inputPorts(op)) {
    const pid = port.id || 'in'
    const options = bindingOptions({
      neededTypes: port.types || [],
      slots,
      upstream,
      operators,
      typeProvides,
    }).filter((o) => o.binding.kind === 'slot')
    if (!options.length) continue
    if (port.multiple) bindings[pid] = options.map((o) => o.binding)
    else bindings[pid] = options[0].binding
    const first = options[0].binding
    if (first.kind === 'slot' && !whenKind) {
      whenKind = whenKindFromSlot(slots.find((s) => s.id === first.slot_id))
    }
  }
  return { bindings, whenKind }
}

function stageBindings(
  op: PlatformOperator | undefined,
  inputs: string[] | undefined,
  slots: DataTypeSlot[],
  produceIndex: Map<string, { stepKey: string; portId: string }>,
  prior: PipelineStep[],
  operators: PlatformOperator[],
  typeProvides: Record<string, string[]>,
): Record<string, PipelinePortBindings> {
  if (inputs === undefined) {
    return autoBindings(op, slots, prior, operators, typeProvides).bindings
  }
  return hydrateBindings(inputs, slots, produceIndex, op)
}

export function hydrateRecipeToSteps(
  recipe: DataTypeRecipe,
  operators: PlatformOperator[],
  typeProvides: Record<string, string[]> = {},
): PipelineStep[] {
  const slots = recipe.slots || []
  const sourceCards: PipelineStep[] = []
  for (const slot of slots) {
    const sid = String(slot.id || '').trim()
    if (!sid) continue
    sourceCards.push(
      newSourceCard({
        key: sid,
        title: String(slot.title || sid),
        kinds: [...(slot.kinds || [])],
        cardinality_min: Number(slot.cardinality_min ?? 1),
        cardinality_max: Number(slot.cardinality_max ?? 1),
        required: slot.required !== false,
      }),
    )
  }

  const steps: PipelineStep[] = []
  const produceIndex = new Map<string, { stepKey: string; portId: string }>()
  const usedKeys = new Set(sourceCards.map((c) => String(c.key || '')).filter(Boolean))

  ;(recipe.preprocess || []).forEach((raw: DataTypePreprocessStep) => {
    const opId = raw.op_id
    const op = getOp(operators, opId)
    const key = uniqueCatalogKey(opId, usedKeys)
    const produces = (raw.produces || []).filter(Boolean)
    let params = { ...(raw.params || {}) }
    let resolved = produces
    if (opId === 'parse_bag') {
      resolved = effectiveProduces({ op_id: opId, key: '', produces, params }, op)
      params = { ...params, emit_modalities: resolved }
    } else if (!resolved.length) {
      resolved = defaultProduces(op)
    }
    const card: PipelineStep = {
      key,
      op_id: opId,
      title: String(op?.title || opId),
      role: 'preprocess',
      required: Boolean(raw.required),
      when_kind: raw.when_kind ?? null,
      produces: resolved,
      params,
      bindings: hydrateBindings(raw.inputs || [], slots, produceIndex, op),
      bbox_enabled: false,
    }
    if (raw.output_labels && typeof raw.output_labels === 'object') {
      card.output_labels = { ...raw.output_labels }
    }
    if (opId === 'detect_bbox') {
      card.bbox_enabled = Boolean(recipe.bbox?.enabled)
      if (recipe.bbox?.detector) card.params = { ...card.params, detector: recipe.bbox.detector }
      if (recipe.bbox && 'yolo_classes' in recipe.bbox) {
        card.params = { ...card.params, yolo_classes: recipe.bbox.yolo_classes || '' }
      }
    }
    steps.push(card)
    ;(card.produces || []).forEach((name) => {
      produceIndex.set(name, { stepKey: key, portId: name })
    })
  })

  const hasBboxOp = steps.some((s) => s.op_id === 'detect_bbox')
  if (recipe.bbox?.enabled && !hasBboxOp) {
    const op = getOp(operators, 'detect_bbox')
    const bboxKey = uniqueCatalogKey('detect_bbox', usedKeys)
    steps.push({
      key: bboxKey,
      op_id: 'detect_bbox',
      role: 'preprocess',
      required: true,
      when_kind: null,
      produces: defaultProduces(op),
      params: {
        detector: recipe.bbox.detector || 'opencv',
        yolo_classes: recipe.bbox.yolo_classes || '',
      },
      bindings: {},
      bbox_enabled: true,
    })
  }

  if (recipe.stages?.embed?.enabled) {
    const op = getOp(operators, 'embed')
    steps.push({
      key: uniqueCatalogKey('embed', usedKeys),
      op_id: 'embed',
      title: String(op?.title || 'embed'),
      role: 'stage',
      required: false,
      when_kind: null,
      produces: defaultProduces(op),
      params: {},
      bindings: stageBindings(
        op,
        recipe.stages.embed.inputs,
        slots,
        produceIndex,
        [...sourceCards, ...steps],
        operators,
        typeProvides,
      ),
      bbox_enabled: false,
    })
  }
  if (recipe.stages?.label?.enabled) {
    const op = getOp(operators, 'label')
    const model = recipe.stages.label.model
    steps.push({
      key: 'stage-label',
      op_id: 'label',
      title: String(op?.title || 'label'),
      role: 'stage',
      required: false,
      when_kind: null,
      produces: defaultProduces(op),
      params: model ? { model } : {},
      bindings: stageBindings(
        op,
        recipe.stages.label.inputs,
        slots,
        produceIndex,
        [...sourceCards, ...steps],
        operators,
        typeProvides,
      ),
      bbox_enabled: false,
    })
  }
  return pinLabelLast([...sourceCards, ...steps])
}

function compileOneBind(bind: PipelineBinding, byKey: Map<string, PipelineStep>, operators: PlatformOperator[]): string | null {
  if (bind.kind === 'slot' && bind.slot_id) return bind.slot_id
  if (bind.kind !== 'upstream') return null
  const up = byKey.get(bind.step_key)
  if (!up) return null
  let produces = effectiveProduces(up, getOp(operators, up.op_id))
  if (isSourceCard(up) && !produces.length) produces = [...(up.kinds || [])]
  const portId = bind.port_id || ''
  if (portId && produces.includes(portId)) return portId
  if (produces.length && (!portId || portId === 'out')) return produces[0]
  if (isSourceCard(up)) return up.key || null
  return null
}

function compileInputs(
  card: PipelineStep,
  byKey: Map<string, PipelineStep>,
  op: PlatformOperator | undefined,
  operators: PlatformOperator[],
): string[] {
  const bindings = card.bindings || {}
  const out: string[] = []
  for (const port of inputPorts(op)) {
    for (const bind of asBindingList(bindings[port.id || 'in'])) {
      const resolved = compileOneBind(bind, byKey, operators)
      if (resolved && !out.includes(resolved)) out.push(resolved)
    }
  }
  return out
}

function deriveWhenKind(card: PipelineStep, slots: DataTypeSlot[]): string | null | undefined {
  if (card.when_kind !== undefined && card.when_kind !== null) return card.when_kind
  const bindings = card.bindings || {}
  for (const raw of Object.values(bindings)) {
    for (const bind of asBindingList(raw)) {
      if (bind.kind !== 'slot') continue
      const slot = slots.find((s) => s.id === bind.slot_id)
      const wk = whenKindFromSlot(slot)
      if (wk) return wk
    }
  }
  return null
}

export function compileSteps(
  steps: PipelineStep[],
  slots: DataTypeSlot[],
  operators: PlatformOperator[],
): Pick<DataTypeRecipe, 'preprocess' | 'products' | 'stages' | 'bbox' | 'slots' | 'require_any_kinds'> {
  assertUpwardBindings(steps)
  const sourceSlots = slotsFromSteps(steps)
  const effectiveSlots = sourceSlots.length ? sourceSlots : [...(slots || [])]
  const byKey = new Map(steps.map((s) => [s.key, s]))
  const preprocess: DataTypePreprocessStep[] = []
  const products: DataTypeProduct[] = []
  const seen = new Set<string>()
  let labelCard: PipelineStep | undefined
  let embedCard: PipelineStep | undefined
  let bboxCard: PipelineStep | undefined

  for (const rawCard of steps) {
    if (isSourceCard(rawCard)) continue
    const op = getOp(operators, rawCard.op_id)
    const role = rawCard.role || op?.role || 'preprocess'
    if (rawCard.op_id === 'label') {
      labelCard = rawCard
      continue
    }
    if (rawCard.op_id === 'embed') {
      embedCard = rawCard
      continue
    }
    if (role === 'stage') continue

    const produces = effectiveProduces(rawCard, op)
    const card: PipelineStep =
      rawCard.op_id === 'parse_bag'
        ? { ...rawCard, produces, params: { ...(rawCard.params || {}), emit_modalities: produces } }
        : rawCard
    if (rawCard.op_id === 'parse_bag') byKey.set(card.key, card)
    const names = produces
    const inputs = compileInputs(card, byKey, op, operators)
    const entry: DataTypePreprocessStep = {
      op_id: card.op_id,
      when_kind: deriveWhenKind(card, effectiveSlots) ?? null,
      required: Boolean(card.required),
    }
    if (inputs.length) entry.inputs = inputs
    if (names.length) entry.produces = names
    const params = { ...(card.params || {}) }
    if (card.op_id === 'detect_bbox') {
      bboxCard = card
      delete params.enabled
    }
    const allowed = new Set(Object.keys(op?.params_schema || {}))
    const clean: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
      if (!allowed.has(k)) continue
      clean[k] = v
    }
    if (Object.keys(clean).length) entry.params = clean
    const labels = stripOutputLabels(card.output_labels, names)
    if (labels) entry.output_labels = labels
    preprocess.push(entry)
    for (const name of names) {
      if (seen.has(name)) continue
      seen.add(name)
      products.push({ id: name, from_op: card.op_id, reusable: true })
    }
  }

  const stages: NonNullable<DataTypeRecipe['stages']> = {
    label: { enabled: Boolean(labelCard) },
    embed: { enabled: Boolean(embedCard) },
  }
  const model = labelCard?.params?.model
  if (labelCard) {
    stages.label = { enabled: true, ...labelStageExtras(labelCard.params) }
    if (typeof model === 'string' && model.trim()) {
      stages.label.model = model.trim()
    }
    stages.label.inputs = compileInputs(labelCard, byKey, getOp(operators, 'label'), operators)
  }
  if (embedCard) {
    stages.embed = {
      enabled: true,
      inputs: compileInputs(embedCard, byKey, getOp(operators, 'embed'), operators),
    }
  }

  const bbox = bboxCard
    ? {
        enabled: bboxCard.bbox_enabled !== false,
        detector: String(bboxCard.params?.detector || 'opencv'),
        yolo_classes: String(bboxCard.params?.yolo_classes || ''),
      }
    : { enabled: false, detector: 'opencv', yolo_classes: '' }

  return {
    preprocess,
    products,
    stages,
    bbox,
    slots: effectiveSlots,
    require_any_kinds: requireAnyKindsFromSlots(effectiveSlots),
  }
}

export type BindingOption = {
  value: string
  label: string
  binding: PipelineBinding
}

export function encodeBinding(b: PipelineBinding): string {
  if (b.kind === 'slot') return `slot:${b.slot_id}`
  return `up:${b.step_key}:${b.port_id || 'out'}`
}

function hydrateStepAlias(stepKey: string): string {
  const prep = stepKey.match(/^prep-\d+-(.+)$/)
  if (prep?.[1]) return prep[1]
  if (stepKey.startsWith('stage-')) return stepKey.slice('stage-'.length)
  return stepKey
}

/** Chip / selected-value text: never fall back to raw `up:{nodeId}:{port}` ids. */
export function bindingDisplayLabel(
  value: string,
  options: BindingOption[],
  steps: PipelineStep[],
  operators: PlatformOperator[],
): string {
  const direct = options.find((o) => o.value === value)
  if (direct?.label) return direct.label
  const decoded = decodeBinding(value)
  if (!decoded) return value
  if (decoded.kind === 'slot') {
    const hit = options.find((o) => o.binding.kind === 'slot' && o.binding.slot_id === decoded.slot_id)
    if (hit?.label) return hit.label
    const src = steps.find((s) => isSourceCard(s) && s.key === decoded.slot_id)
    const title = String(src?.title || decoded.slot_id || '').trim()
    return title || value
  }
  const portId = decoded.port_id && decoded.port_id !== 'out' ? decoded.port_id : ''
  const samePort = (o: BindingOption) =>
    o.binding.kind === 'upstream' && (!portId || o.binding.port_id === portId)
  const byKey = options.find((o) => samePort(o) && o.binding.kind === 'upstream' && o.binding.step_key === decoded.step_key)
  if (byKey?.label) return byKey.label
  const alias = hydrateStepAlias(decoded.step_key)
  const byAlias = options.find(
    (o) =>
      samePort(o) &&
      o.binding.kind === 'upstream' &&
      (o.binding.step_key === alias || o.binding.step_key.endsWith(`-${alias}`)),
  )
  if (byAlias?.label) return byAlias.label
  const step =
    steps.find((s) => s.key === decoded.step_key) ||
    steps.find((s) => s.op_id === alias || s.key === alias || s.key.endsWith(`-${alias}`))
  const op = getOp(operators, String(step?.op_id || alias))
  const title = String(op?.title || step?.title || alias || decoded.step_key || '').trim()
  const product = portId ? step?.output_labels?.[portId] || typeLabel(portId) : ''
  if (title && product) return `${title} · ${product}`
  return title || value
}

export function decodeBinding(value: string): PipelineBinding | null {
  if (!value) return null
  if (value.startsWith('slot:')) return { kind: 'slot', slot_id: value.slice(5) }
  if (value.startsWith('up:')) {
    const rest = value.slice(3)
    const idx = rest.lastIndexOf(':')
    if (idx <= 0) return { kind: 'upstream', step_key: rest, port_id: 'out' }
    return { kind: 'upstream', step_key: rest.slice(0, idx), port_id: rest.slice(idx + 1) }
  }
  return null
}

export function bindingOptions(args: {
  neededTypes: string[]
  slots: DataTypeSlot[]
  upstream: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
}): BindingOption[] {
  const { neededTypes, slots, upstream, operators, typeProvides } = args
  const needed = neededTypes.filter(Boolean)
  const options: BindingOption[] = []
  const seenSlotIds = new Set<string>()

  const appendSlot = (sid: string, kinds: string[], title: string) => {
    if (!sid || seenSlotIds.has(sid)) return
    if (!kinds.some((kind) => needed.some((need) => typeCompatible(kind, need, typeProvides)))) return
    seenSlotIds.add(sid)
    const binding: PipelineBinding = { kind: 'slot', slot_id: sid }
    const label = title.trim() ? title.trim() : `槽位 ${sid}`
    options.push({ value: encodeBinding(binding), label, binding })
  }

  for (const slot of slots) {
    if (!slot.id) continue
    appendSlot(slot.id, slot.kinds || [], String(slot.title || ''))
  }
  for (const card of upstream) {
    if (isSourceCard(card)) {
      appendSlot(String(card.key || '').trim(), card.kinds || [], String(card.title || card.key || ''))
      continue
    }
    const op = getOp(operators, card.op_id)
    const title = op?.title || card.op_id
    const ports = expandOutputPorts(op, card.params)
    for (const port of ports) {
      const types = (port.types || []).filter(Boolean)
      const matchTypes = types.length ? types : [port.id]
      if (!needed.some((need) => matchTypes.some((t) => typeCompatible(t, need, typeProvides)))) continue
      const binding: PipelineBinding = {
        kind: 'upstream',
        step_key: card.key,
        port_id: port.id,
      }
      options.push({
        value: encodeBinding(binding),
        label: `${title} · ${port.title || card.output_labels?.[port.id] || typeLabel(port.id)}`,
        binding,
      })
    }
  }
  return options
}

export function newStepFromOp(args: {
  opId: string
  key: string
  operators: PlatformOperator[]
  slots: DataTypeSlot[]
  upstream: PipelineStep[]
  typeProvides: Record<string, string[]>
}): PipelineStep {
  const { opId, key, operators, slots, upstream, typeProvides } = args
  const op = getOp(operators, opId)
  const role = op?.role || 'preprocess'
  const { bindings, whenKind } = autoBindings(op, slots, upstream, operators, typeProvides)
  const params: Record<string, unknown> = {}
  if (opId === 'label') params.model = 'default'
  if (opId === 'detect_bbox') {
    params.detector = 'opencv'
    params.yolo_classes = ''
  }
  if (opId === 'parse_bag') params.emit_modalities = [...PARSE_BAG_MODALITIES]
  if (opId === 'json_extract') params.path_keys = ['']
  if (opId === 'label_tree_input') params.assignments = []
  if (op?.expand_outputs_from === 'channel_count') params.channel_count = 1
  return {
    key,
    op_id: opId,
    role,
    required: false,
    when_kind: whenKind,
    produces: opId === 'parse_bag' ? [...PARSE_BAG_MODALITIES] : defaultProduces(op),
    params,
    bindings,
    bbox_enabled: opId === 'detect_bbox',
  }
}

export function defaultNewSteps(operators: PlatformOperator[]): PipelineStep[] {
  return [
    newSourceCard({ key: 'src-1', title: '数据源', kinds: ['.mp4'] }),
    newStepFromOp({
      opId: 'label',
      key: 'stage-label',
      operators,
      slots: [],
      upstream: [],
      typeProvides: {},
    }),
  ]
}

const LEGACY_LABEL_TITLES = new Set(['打标器', 'label', 'labeler'])

export function uniqueCatalogKey(preferred: string, used: Set<string>): string {
  const base = (preferred || 'op').trim() || 'op'
  if (!used.has(base)) {
    used.add(base)
    return base
  }
  let n = 2
  while (used.has(`${base}-${n}`)) n += 1
  const key = `${base}-${n}`
  used.add(key)
  return key
}

export function isLegacyHydrateKey(key: string): boolean {
  const k = String(key || '')
  return /^prep-\d+-/.test(k) || k.startsWith('prep-bbox-') || k === 'stage-embed'
}

export function isGenericNodeTitle(stored: string, opId: string, key?: string): boolean {
  const t = String(stored || '').trim()
  if (!t) return true
  if (t === opId) return true
  if (key && t === key) return true
  if (t.startsWith('prep-')) return true
  if (opId && t === `stage-${opId}`) return true
  if (opId === 'label' && LEGACY_LABEL_TITLES.has(t)) return true
  return false
}

export function displayNodeTitle(
  node: { type?: string; op_id?: string; title?: string; key?: string },
  operators: PlatformOperator[] = [],
): string {
  const opId = String(node.op_id || (node.type === 'label' ? 'label' : '') || '')
  const catalogTitle = getOp(operators, opId)?.title
  const stored = String(node.title || '').trim()
  const key = String(node.key || '')
  if (catalogTitle && isGenericNodeTitle(stored, opId, key)) return catalogTitle
  return stored || catalogTitle || node.key || opId
}

/** Type names shown on cards. */
export const TYPE_LABELS: Record<string, string> = {
  frames: '连续帧',
  frames_audio_topics: '多模数据',
  preview_mp4: '编码视频',
  asr_jsonl: 'ASR 文本',
  mel_matrix: '梅尔频谱',
  stft_matrix: 'STFT 频谱',
  third_octave_json: '1/3 倍频程',
  spl_jsonl: 'SPL',
  pcm_pa_wavs: 'PCM 声压',
  structured_json: '结构化 JSON',
  json_value: 'JSON 值',
  bboxes_jsonl: 'BBox',
  labels_tree: '标签树',
  embeddings: '向量',
  labelable: '可打标数据',
}

export function typeLabel(t: string, labels?: Record<string, string>): string {
  if (labels?.[t]) return labels[t]
  const n = normalizeSourceKind(t)
  if (n) return n
  return TYPE_LABELS[t] || t
}
