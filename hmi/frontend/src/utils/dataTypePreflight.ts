import type { DataTypeRecipe } from '../api/types'

/** Upload staging modality → DataType source kind. */
export function uploadModalityToSourceKind(modality: string): string {
  if (modality === 'bag') return 'rosbag'
  return modality
}

export function preflightUploadKinds(
  recipe: DataTypeRecipe | null | undefined,
  kinds: string[],
): { ok: boolean; missing: string[] } {
  if (!recipe) return { ok: false, missing: [] }
  const present = new Set(kinds.map(uploadModalityToSourceKind))
  const groups = recipe.require_any_kinds ?? []
  if (!groups.length) return { ok: true, missing: [] }
  for (const group of groups) {
    if (group.length && group.every((k) => present.has(k))) {
      return { ok: true, missing: [] }
    }
  }
  const missing = [...new Set(groups.flat())].filter((k) => !present.has(k)).sort()
  return { ok: false, missing }
}
