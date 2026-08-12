import type { ClipOverview } from '../api/types'

const STORAGE_KEY = 'hmi-overview-cache-v2'
/** Client-side overview cache TTL: 6 hours. */
export const OVERVIEW_CACHE_TTL_MS = 6 * 60 * 60 * 1000

export type OverviewSnapshot = {
  clips: ClipOverview[]
  cacheKey: string
  /** epoch ms when this snapshot was written after a successful fetch */
  savedAt: number
}

function readRaw(): OverviewSnapshot | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) ?? sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<OverviewSnapshot>
    if (!parsed || !Array.isArray(parsed.clips) || typeof parsed.cacheKey !== 'string') {
      return null
    }
    return {
      clips: parsed.clips,
      cacheKey: parsed.cacheKey,
      savedAt: typeof parsed.savedAt === 'number' ? parsed.savedAt : 0,
    }
  } catch {
    return null
  }
}

export function isOverviewSnapshotFresh(snapshot: OverviewSnapshot, now = Date.now()): boolean {
  if (!snapshot.savedAt) return false
  return now - snapshot.savedAt < OVERVIEW_CACHE_TTL_MS
}

/** Valid (non-expired) snapshot for this cacheKey, or null. */
export function getOverviewSnapshot(cacheKey: string): OverviewSnapshot | null {
  const snapshot = readRaw()
  if (!snapshot || snapshot.cacheKey !== cacheKey) return null
  if (!isOverviewSnapshotFresh(snapshot)) return null
  return snapshot
}

/** Any snapshot for key (even expired) — useful for stale-while-revalidate UI. */
export function getOverviewSnapshotStale(cacheKey: string): OverviewSnapshot | null {
  const snapshot = readRaw()
  if (!snapshot || snapshot.cacheKey !== cacheKey) return null
  return snapshot
}

export function setOverviewSnapshot(cacheKey: string, clips: ClipOverview[]): void {
  const payload: OverviewSnapshot = { clips, cacheKey, savedAt: Date.now() }
  const text = JSON.stringify(payload)
  try {
    localStorage.setItem(STORAGE_KEY, text)
  } catch {
    /* quota / private mode */
  }
  try {
    sessionStorage.removeItem(STORAGE_KEY)
    // drop legacy key
    sessionStorage.removeItem('hmi-overview-cache')
  } catch {
    /* ignore */
  }
}

export function clearOverviewSnapshot(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
  try {
    sessionStorage.removeItem(STORAGE_KEY)
    sessionStorage.removeItem('hmi-overview-cache')
  } catch {
    /* ignore */
  }
}

export function overviewCacheAgeLabel(savedAt: number, now = Date.now()): string {
  const ageMs = Math.max(0, now - savedAt)
  const mins = Math.floor(ageMs / 60_000)
  if (mins < 1) return '刚刚更新'
  if (mins < 60) return `${mins} 分钟前更新`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前更新`
  return `${Math.floor(hours / 24)} 天前更新`
}
