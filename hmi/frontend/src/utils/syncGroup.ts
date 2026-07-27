import type { SampledFrame } from '../api/types'

export function isSyncGroupFrame(frame: SampledFrame): boolean {
  return Boolean(frame.is_sync_group && frame.sync_group_id)
}

export function sceneTimestampNs(frame: SampledFrame): number {
  if (isSyncGroupFrame(frame) && frame.anchor_timestamp_ns != null) {
    return frame.anchor_timestamp_ns
  }
  return frame.timestamp_ns
}

/** Group labeled frames for display: one card per sync_group, else per frame. */
export function groupLabeledFramesForDisplay(frames: SampledFrame[]): SampledFrame[] {
  const out: SampledFrame[] = []
  const seenGroups = new Set<string>()
  const seenFrames = new Set<string>()
  for (const f of frames) {
    if (isSyncGroupFrame(f) && f.sync_group_id) {
      if (seenGroups.has(f.sync_group_id)) continue
      seenGroups.add(f.sync_group_id)
      out.push(f)
    } else {
      if (seenFrames.has(f.composite_id)) continue
      seenFrames.add(f.composite_id)
      out.push(f)
    }
  }
  return out
}

export function camerasInSyncGroup(frames: SampledFrame[], syncGroupId: string): string[] {
  return [...new Set(frames.filter((f) => f.sync_group_id === syncGroupId).map((f) => f.camera))].sort()
}
