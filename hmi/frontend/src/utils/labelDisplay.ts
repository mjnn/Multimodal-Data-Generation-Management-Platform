import type { AiLabelHint, TaxonomyNodeDetail } from '../api/types'

function schemaLabels(schema: unknown): Record<string, string> {
  if (!schema || typeof schema !== 'object') return {}
  const labels = (schema as { labels?: Record<string, string> }).labels
  return labels && typeof labels === 'object' ? labels : {}
}

function normalizeBoolText(raw: string): string | null {
  const t = raw.trim().toLowerCase()
  if (t === 'true' || t === '1' || t === 'yes' || t === '是') return '是'
  if (t === 'false' || t === '0' || t === 'no' || t === '否') return '否'
  return null
}

export function formatLabelValue(value: unknown, node?: TaxonomyNodeDetail | null): string {
  if (value === null || value === undefined || value === '') return '—'
  const schema = node?.value_schema
  if (typeof value === 'boolean') {
    if (schema && typeof schema === 'object') {
      const s = schema as { true_label?: string; false_label?: string }
      return value ? s.true_label ?? '是' : s.false_label ?? '否'
    }
    return value ? '是' : '否'
  }
  if (Array.isArray(value)) {
    return value
      .map((v) => formatLabelValue(v, node))
      .filter((s) => s && s !== '—')
      .join('、')
  }
  if (typeof value === 'string') {
    const boolText = normalizeBoolText(value)
    if (boolText && schema && typeof schema === 'object' && (schema as { type?: string }).type === 'bool') {
      return boolText
    }
    const labels = schemaLabels(schema)
    if (value in labels) return labels[value]
    for (const zh of Object.values(labels)) {
      if (zh === value) return value
    }
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

export function clipLabelsFlat(labelsJson: Record<string, unknown> | undefined | null): Record<string, unknown> {
  if (!labelsJson || typeof labelsJson !== 'object') return {}
  const values = labelsJson.values
  if (values && typeof values === 'object' && !Array.isArray(values)) {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(values as Record<string, unknown>)) {
      if (v && typeof v === 'object' && 'value' in (v as object)) {
        out[k] = (v as { value: unknown }).value
      } else {
        out[k] = v
      }
    }
    return out
  }
  return labelsJson as Record<string, unknown>
}

const SCENE_LABEL_NAME_HINTS = ['场景描述', '场景概述', '场景摘要']

function pickSceneFromFlat(flat: Record<string, unknown>): string | null {
  for (const key of Object.keys(flat)) {
    if (/scene/i.test(key) && (key.includes('summary') || key.includes('desc'))) {
      const text = formatLabelValue(flat[key])
      if (text && text !== '—') return text
    }
  }
  return null
}

/** 场景描述：优先标签树中「场景描述」类标签，其次 scene_summary 等字段。 */
export function resolveSceneDescriptionText(
  labelsJson: Record<string, unknown> | undefined | null,
  options?: {
    taxonomyNodes?: TaxonomyNodeDetail[]
    sceneSummary?: string | null
  },
): string | null {
  const sceneSummary = options?.sceneSummary?.trim()
  if (sceneSummary) return sceneSummary

  if (!labelsJson || typeof labelsJson !== 'object') return null

  const rootSummary =
    typeof (labelsJson as { scene_summary?: unknown }).scene_summary === 'string'
      ? (labelsJson as { scene_summary: string }).scene_summary.trim()
      : ''
  if (rootSummary) return rootSummary

  const flat = clipLabelsFlat(labelsJson)
  const fromFlat = pickSceneFromFlat(flat)
  if (fromFlat) return fromFlat

  const nodes = options?.taxonomyNodes ?? []
  for (const node of nodes) {
    if (!SCENE_LABEL_NAME_HINTS.some((hint) => node.name.includes(hint))) continue
    const text = formatLabelValue(flat[node.label_id], node)
    if (text && text !== '—') return text
  }

  return null
}

export function enumDisplayOptions(node: TaxonomyNodeDetail | undefined): { value: string; label: string }[] {
  if (!node?.value_schema || typeof node.value_schema !== 'object') return []
  const schema = node.value_schema as { type?: string; values?: unknown[]; labels?: Record<string, string> }
  const labels = schema.labels ?? {}
  const values = Array.isArray(schema.values) ? schema.values.map(String) : []
  if (!values.length) return []
  return values.map((v) => {
    const zh = labels[v] ?? v
    return { value: zh, label: zh }
  })
}

export function schemaEnumValues(node: TaxonomyNodeDetail | undefined): string[] {
  if (!node) return []
  return enumDisplayOptions(node).map((o) => o.value)
}

/** Extract AI confidence / evidence from OMS-style nested labels_json. */
export function extractAiHintsFromLabels(
  labelsJson: Record<string, unknown> | undefined | null,
): Record<string, AiLabelHint> {
  if (!labelsJson || typeof labelsJson !== 'object') return {}
  const hints: Record<string, AiLabelHint> = {}
  const values = labelsJson.values
  const source =
    values && typeof values === 'object' && !Array.isArray(values)
      ? (values as Record<string, unknown>)
      : labelsJson
  for (const [lid, entry] of Object.entries(source)) {
    if (lid === 'values' || !entry || typeof entry !== 'object' || Array.isArray(entry)) continue
    const obj = entry as Record<string, unknown>
    const hint: AiLabelHint = {}
    if (obj.confidence != null) {
      const c = Number(obj.confidence)
      if (!Number.isNaN(c)) hint.confidence = c
    }
    if (obj.evidence != null && String(obj.evidence).trim()) {
      hint.evidence = String(obj.evidence).trim()
    }
    if (hint.confidence != null || hint.evidence) {
      hints[lid] = hint
    }
  }
  return hints
}
