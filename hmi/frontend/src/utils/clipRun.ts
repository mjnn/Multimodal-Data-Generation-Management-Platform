import type { ClipOverview } from '../api/types'

export function clipRunRowKey(clipId: string, runId: string): string {
  return `${clipId}::${runId}`
}

export function overviewRunId(clip: Pick<ClipOverview, 'run_id' | 'active_run_id'>): string {
  return (clip.run_id || clip.active_run_id || '').trim()
}

export function overviewRowKey(clip: Pick<ClipOverview, 'clip_id' | 'run_id' | 'active_run_id'>): string {
  return clipRunRowKey(clip.clip_id, overviewRunId(clip))
}
