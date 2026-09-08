/** DataType recipe → bound taxonomy helpers (clip explorer / review). */

const NVH_TAXONOMY_IDS = new Set(['audio_nvh'])
const NVH_VERSION_PREFIXES = ['audio_nvh'] as const

export function recipeUsesNvhTaxonomy(
  recipe: { taxonomy_id?: string; taxonomy_version_code?: string } | null | undefined,
): boolean {
  const tid = String(recipe?.taxonomy_id || '').trim()
  if (NVH_TAXONOMY_IDS.has(tid)) return true
  const code = String(recipe?.taxonomy_version_code || '').trim()
  return NVH_VERSION_PREFIXES.some(
    (p) => code === p || code.startsWith(`${p}-`) || code.startsWith(`${p}_`),
  )
}
