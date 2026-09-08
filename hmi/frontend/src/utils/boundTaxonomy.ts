import type { TaxonomyVersion } from '../api/types'

const TAXONOMY_STATUS_RANK: Record<string, number> = { published: 3, draft: 2, archived: 1, proposal: 0 }

export function pickByTaxonomyId(
  versions: TaxonomyVersion[],
  taxonomyId: string,
): TaxonomyVersion | undefined {
  const id = String(taxonomyId || '').trim()
  if (!id) return undefined
  const exact = versions.find((v) => v.version_code === id)
  if (exact) return exact
  const prefixed = versions.filter(
    (v) => v.version_code.startsWith(`${id}-`) || v.version_code.startsWith(`${id}_`),
  )
  if (!prefixed.length) return undefined
  return [...prefixed].sort((a, b) => {
    const ra = TAXONOMY_STATUS_RANK[a.status] || 0
    const rb = TAXONOMY_STATUS_RANK[b.status] || 0
    if (rb !== ra) return rb - ra
    return String(b.created_at || '').localeCompare(String(a.created_at || ''))
  })[0]
}

/** Clip 详情用：按配方 version_code / taxonomy_id 绑树，禁止落到全局 published OMS。 */
export function pickBoundTaxonomyVersion(
  versions: TaxonomyVersion[],
  opts: { versionCode?: string | null; taxonomyId?: string | null },
): TaxonomyVersion | undefined {
  const code = String(opts.versionCode || '').trim()
  if (code) {
    const found = versions.find((v) => v.version_code === code)
    if (found) return found
  }
  return pickByTaxonomyId(versions, String(opts.taxonomyId || ''))
}