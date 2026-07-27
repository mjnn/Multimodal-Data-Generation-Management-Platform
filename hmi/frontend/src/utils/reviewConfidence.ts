/** Align with backend LOW_CONFIDENCE_THRESHOLD in hmi/review/v2_tasks.py */
export const LOW_CONFIDENCE_THRESHOLD = 0.75

export function parseReviewV2OpenMode(raw: string | null): 'confidence' | null {
  if (raw === 'confidence' || raw === 'ai_dispute') return 'confidence'
  return null
}

export function isLowConfidence(
  aiValue: unknown,
  confidence: number | null | undefined,
): boolean {
  if (aiValue === null || aiValue === undefined || aiValue === '') return false
  if (confidence == null || !Number.isFinite(confidence)) return true
  return confidence < LOW_CONFIDENCE_THRESHOLD
}

export function lowConfidenceLabelIdsFromHints(
  hints: Record<string, { confidence?: number | null }>,
  labelsJson: Record<string, unknown> | null | undefined,
): string[] {
  const labels = labelsJson ?? {}
  const out: string[] = []
  for (const labelId of Object.keys(labels)) {
    const hint = hints[labelId]
    if (isLowConfidence(labels[labelId], hint?.confidence)) {
      out.push(labelId)
    }
  }
  return out.sort()
}
