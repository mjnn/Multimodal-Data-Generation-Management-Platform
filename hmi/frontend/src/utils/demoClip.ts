import type { ClipOverview } from '../api/types'

/** Demo clips use clip_id like `sha256:demo_*`. */
export function isDemoClip(clip: Pick<ClipOverview, 'clip_id'>): boolean {
  return clip.clip_id.includes(':demo_')
}
