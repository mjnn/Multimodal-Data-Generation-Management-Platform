import type { DataTypeRecipe } from '../api/types'
import { kindFromFilename, normalizeSourceKind } from './fileKinds'

/** Upload staging / lake file → DataType source kind (suffix). */
export function uploadModalityToSourceKind(modality: string): string {
  return normalizeSourceKind(modality) || kindFromFilename(`x${modality.startsWith('.') ? modality : `.${modality}`}`) || modality
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
    const g = group.map((k) => normalizeSourceKind(k) || k)
    if (g.length && g.every((k) => present.has(k))) {
      return { ok: true, missing: [] }
    }
  }
  const missing = [...new Set(groups.flat().map((k) => normalizeSourceKind(k) || k))]
    .filter((k) => !present.has(k))
    .sort()
  return { ok: false, missing }
}
