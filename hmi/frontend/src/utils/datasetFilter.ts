import type { DatasetFilterJson, LabelDistributionConfig } from '../api/types'

export function buildFilterJson(
  labelDistribution: LabelDistributionConfig | null,
  sampleSize?: number | null,
  extra?: Partial<DatasetFilterJson>,
): DatasetFilterJson {
  const filter: DatasetFilterJson = {
    review_status: 'reviewed',
    include_pending_review: false,
    ...extra,
  }
  if (labelDistribution?.label_id) {
    if (labelDistribution.kind === 'enum') {
      const weights: Record<string, number> = {}
      for (const [k, v] of Object.entries(labelDistribution.weights)) {
        if (v != null && v > 0) weights[k] = v
      }
      filter.label_distribution = {
        label_id: labelDistribution.label_id,
        kind: 'enum',
        weights,
      }
    } else {
      const buckets = labelDistribution.buckets
        .filter(
          (b) =>
            b.weight != null &&
            b.weight > 0 &&
            ((b.match === 'exact' && b.value?.trim()) ||
              (b.match === 'range' && (b.min?.trim() || b.max?.trim()))),
        )
        .map((b) => ({
          id: b.id,
          match: b.match,
          value: b.value?.trim() || undefined,
          min: b.min?.trim() || undefined,
          max: b.max?.trim() || undefined,
          weight: b.weight,
        }))
      if (buckets.length > 0) {
        filter.label_distribution = {
          label_id: labelDistribution.label_id,
          kind: 'string',
          buckets,
        }
      }
    }
  }
  if (sampleSize != null && sampleSize > 0) {
    filter.sample_size = sampleSize
  }
  return filter
}

/** Merge parent snapshot filter with derive wizard overrides (balance + clip label filter + export crop). */
export function buildDeriveFilterJson(
  parent: DatasetFilterJson,
  labelFilters: Record<string, string | boolean>,
  balance: {
    balance_by_label?: string | null
    min_per_class?: number | null
    max_per_class?: number | null
    oversample_policy?: string | null
    oversample_max_multiplier?: number | null
  },
  exportLabelIds?: string[] | null,
): DatasetFilterJson {
  const cleaned = Object.fromEntries(
    Object.entries(labelFilters).filter(([, v]) => v !== '' && v != null),
  ) as Record<string, string | boolean>
  const merged: DatasetFilterJson = {
    ...parent,
    balance_by_label: balance.balance_by_label?.trim() || null,
    min_per_class: balance.min_per_class ?? null,
    max_per_class: balance.max_per_class ?? null,
    oversample_policy: balance.oversample_policy ?? 'none',
    oversample_max_multiplier: balance.oversample_max_multiplier ?? null,
  }
  if (Object.keys(cleaned).length > 0) {
    merged.label_filters = cleaned
  } else {
    merged.label_filters = parent.label_filters ?? null
  }
  if (merged.min_per_class != null && merged.min_per_class > 0) {
    if (!merged.oversample_policy || merged.oversample_policy === 'none') {
      merged.oversample_policy = 'duplicate_to_min'
    }
  }
  if (exportLabelIds?.length) {
    merged.export_label_ids = exportLabelIds
  } else {
    merged.export_label_ids = parent.export_label_ids ?? null
    merged.export_taxonomy_version_id = parent.export_taxonomy_version_id ?? null
  }
  return merged
}
