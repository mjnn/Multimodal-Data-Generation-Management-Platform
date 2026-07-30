import type { TaxonomyArchiveReason, TaxonomyStatus } from '../api/types'

export function formatTaxonomyVersionLabel(v: {
  version_code: string
  status: TaxonomyStatus | string
  archive_reason?: TaxonomyArchiveReason | null
}): string {
  const code = v.version_code?.trim() || '—'
  const released =
    v.status === 'published' || (v.status === 'archived' && v.archive_reason === 'superseded')
  if (released) return `${code}（已发布）`
  if (v.status === 'draft') return `${code}（草稿）`
  if (v.status === 'archived') return `${code}（已归档）`
  return code
}
