import type { TaxonomyNodeDetail } from '../api/types'

/** Expand selected label_ids to include ancestor nodes (matches backend crop). */
export function expandTaxonomyCropLabelIds(
  nodes: TaxonomyNodeDetail[],
  selectedLabelIds: string[],
): string[] {
  const active = nodes.filter((n) => n.is_active !== false)
  const byLabel = new Map(active.map((n) => [n.label_id, n]))
  const byId = new Map(active.map((n) => [n.id, n]))
  const keep = new Set(selectedLabelIds.map((id) => id.trim()).filter((id) => id && byLabel.has(id)))
  if (!keep.size) return []

  let changed = true
  while (changed) {
    changed = false
    for (const lid of [...keep]) {
      const node = byLabel.get(lid)
      if (!node?.parent_id) continue
      const parent = byId.get(node.parent_id)
      if (!parent) continue
      const plid = parent.label_id
      if (!keep.has(plid)) {
        keep.add(plid)
        changed = true
      }
    }
  }
  return [...keep].sort()
}
