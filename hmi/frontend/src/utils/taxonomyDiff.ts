import type { TaxonomyDiffChanged, TaxonomyDiffResponse, TaxonomyNodeDetail } from '../api/types'

function normSchema(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function activeNodes(nodes: TaxonomyNodeDetail[]): TaxonomyNodeDetail[] {
  return nodes.filter((n) => n.is_active !== false)
}

/** Diff current nodes against a reference version (reference → current). */
export function diffTaxonomyNodes(
  currentNodes: TaxonomyNodeDetail[],
  againstNodes: TaxonomyNodeDetail[],
  meta: {
    baseVersionId: string
    baseVersionCode: string | null
    againstVersionId: string
    againstVersionCode: string | null
  },
): TaxonomyDiffResponse {
  const base = new Map(activeNodes(currentNodes).map((n) => [n.label_id, n]))
  const against = new Map(activeNodes(againstNodes).map((n) => [n.label_id, n]))
  const baseIds = new Set(base.keys())
  const againstIds = new Set(against.keys())

  const added = [...baseIds].filter((id) => !againstIds.has(id)).sort()
  const removed = [...againstIds].filter((id) => !baseIds.has(id)).sort()
  const changed: TaxonomyDiffChanged[] = []

  for (const labelId of [...baseIds].filter((id) => againstIds.has(id)).sort()) {
    const b = base.get(labelId)!
    const a = against.get(labelId)!
    const fields: string[] = []
    if (String(b.name ?? '') !== String(a.name ?? '')) fields.push('name')
    if (String(b.dtype ?? '') !== String(a.dtype ?? '')) fields.push('dtype')
    if (normSchema(b.value_schema) !== normSchema(a.value_schema)) fields.push('value_schema')
    if (Boolean(b.is_active) !== Boolean(a.is_active)) fields.push('is_active')
    if (fields.length) {
      changed.push({
        label_id: labelId,
        fields,
        before: { name: a.name, dtype: a.dtype, is_active: a.is_active },
        after: { name: b.name, dtype: b.dtype, is_active: b.is_active },
      })
    }
  }

  return {
    base_version_id: meta.baseVersionId,
    base_version_code: meta.baseVersionCode,
    against_version_id: meta.againstVersionId,
    against_version_code: meta.againstVersionCode,
    added_label_ids: added,
    removed_label_ids: removed,
    changed,
    summary: { added: added.length, removed: removed.length, changed: changed.length },
  }
}
