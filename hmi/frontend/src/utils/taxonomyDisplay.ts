import type { TaxonomyArchiveReason, TaxonomyStatus } from '../api/types'

export const TAXONOMY_STATUS_LABEL: Record<TaxonomyStatus, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
  proposal: '提案中',
}

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
  if (v.status === 'proposal') return `${code}（提案中）`
  if (v.status === 'archived') return `${code}（已归档）`
  return code
}

/** Normalize legacy English impact warnings from older API responses. */
export function formatTaxonomyImpactWarning(message: string): string {
  const trimmed = message.trim()
  const legacy: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
    [
      /^(\d+) reviewed clip\(s\) still bound to this taxonomy version$/i,
      (m) => `仍有 ${m[1]} 条已校核 clip 绑定在此标签树版本`,
    ],
    [/^draft version is referenced by clip reviews$/i, () => '草稿版本已被 clip 校核引用'],
  ]
  for (const [pattern, render] of legacy) {
    const match = trimmed.match(pattern)
    if (match) return render(match)
  }
  return trimmed
}
