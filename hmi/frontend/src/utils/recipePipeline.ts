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
    })
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

  ;(recipe.preprocess || []).forEach((raw: DataTypePreprocessStep, idx) => {
    const opId = raw.op_id
    const op = getOp(operators, opId)
    const key = `prep-${idx}-${opId}`
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
    steps.push({
      key: 'prep-bbox-detect_bbox',
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

  if (recipe.stages?.label?.enabled) {
    const op = getOp(operators, 'label')
    const model = recipe.stages.label.model
    steps.push({
      key: 'stage-label',
      op_id: 'label',
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
  if (recipe.stages?.embed?.enabled) {
    const op = getOp(operators, 'embed')
    steps.push({
      key: 'stage-embed',
      op_id: 'embed',
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
  return [...sourceCards, ...steps]
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
    const clean: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
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
    stages.label = { enabled: true }
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
    const produces = effectiveProduces(card, op)
    const title = op?.title || card.op_id
    for (const name of produces) {
      if (!needed.some((need) => typeCompatible(name, need, typeProvides))) continue
      const binding: PipelineBinding = {
        kind: 'upstream',
        step_key: card.key,
        port_id: name,
      }
      options.push({
        value: encodeBinding(binding),
        label: `${title} · ${card.output_labels?.[name] || typeLabel(name)}`,
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
