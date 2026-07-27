export function formatLabelValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
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
