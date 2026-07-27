import type { ClipOverview } from '../api/types'

const OVERVIEW_CLIENT_TTL_MS = 60_000

type OverviewSnapshot = {
  realClips: ClipOverview[]
  demoClips: ClipOverview[]
  demoDataVersion: number
  fetchedAt: number
}

let snapshot: OverviewSnapshot | null = null

export function getOverviewSnapshot(demoDataVersion: number): OverviewSnapshot | null {
  if (!snapshot) return null
  if (snapshot.demoDataVersion !== demoDataVersion) return null
  if (Date.now() - snapshot.fetchedAt > OVERVIEW_CLIENT_TTL_MS) return null
  return snapshot
}

export function setOverviewSnapshot(
  demoDataVersion: number,
  realClips: ClipOverview[],
  demoClips: ClipOverview[],
): void {
  snapshot = {
    realClips,
    demoClips,
    demoDataVersion,
    fetchedAt: Date.now(),
  }
}

export function clearOverviewSnapshot(): void {
  snapshot = null
}
