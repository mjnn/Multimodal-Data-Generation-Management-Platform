import type { ClipOverview } from '../api/types'

const STORAGE_KEY = 'hmi-overview-cache'

export type OverviewSnapshot = {
  clips: ClipOverview[]
  cacheKey: string
}

function readSnapshot(): OverviewSnapshot | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as OverviewSnapshot
  } catch {
    return null
  }
}

export function getOverviewSnapshot(cacheKey: string): OverviewSnapshot | null {
  const snapshot = readSnapshot()
  if (!snapshot || snapshot.cacheKey !== cacheKey) return null
  return snapshot
}

export function setOverviewSnapshot(cacheKey: string, clips: ClipOverview[]): void {
  const payload: OverviewSnapshot = { clips, cacheKey }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
}

export function clearOverviewSnapshot(): void {
  sessionStorage.removeItem(STORAGE_KEY)
}
