import type { AudioSegment, EventLabel, SampledFrame } from '../api/types'
import { sceneTimestampNs } from './syncGroup'

export const SNAP_THRESHOLD_NS = 150_000_000
export const SAMPLE_LABEL_SNAP_NS = 30_000_000
export const CLUSTER_WINDOW_NS = 2_000_000_000

export type SnapKind = 'sampled' | 'event' | 'asr_start' | 'asr_end'

export interface SnapPoint {
  timestamp_ns: number
  kind: SnapKind
  label?: string
}

export function formatDeltaMs(timestampNs: number, cursorNs: number): string {
  const ms = (timestampNs - cursorNs) / 1e6
  const sign = ms >= 0 ? '+' : ''
  return `${sign}${ms.toFixed(0)}ms`
}

export function snapToNearest(
  ns: number,
  points: SnapPoint[],
  thresholdNs = SNAP_THRESHOLD_NS,
): number {
  let best = ns
  let bestDist = thresholdNs + 1
  for (const p of points) {
    const d = Math.abs(p.timestamp_ns - ns)
    if (d <= thresholdNs && d < bestDist) {
      bestDist = d
      best = p.timestamp_ns
    }
  }
  return best
}

export function buildSnapPoints(
  sampledTimestamps: number[],
  events: EventLabel[],
  asrSegments: AudioSegment[],
): SnapPoint[] {
  const points: SnapPoint[] = []
  for (const ts of sampledTimestamps) {
    points.push({ timestamp_ns: ts, kind: 'sampled', label: 'Clip 锚点' })
  }
  for (const e of events) {
    points.push({
      timestamp_ns: e.timestamp_ns,
      kind: 'event',
      label: e.parsed_label ?? '事件',
    })
  }
  for (const s of asrSegments) {
    points.push({ timestamp_ns: s.start_ns, kind: 'asr_start', label: 'ASR 起' })
    points.push({ timestamp_ns: s.end_ns, kind: 'asr_end', label: 'ASR 止' })
  }
  points.sort((a, b) => a.timestamp_ns - b.timestamp_ns)
  return points
}

export function nextSnapPoint(points: SnapPoint[], cursorNs: number, dir: 1 | -1): number | null {
  if (dir > 0) {
    const next = points.find((p) => p.timestamp_ns > cursorNs + 1_000_000)
    return next?.timestamp_ns ?? null
  }
  const prev = [...points].reverse().find((p) => p.timestamp_ns < cursorNs - 1_000_000)
  return prev?.timestamp_ns ?? null
}

export function isOnSampledFrame(frame: SampledFrame, cursorNs: number): boolean {
  if (!frame.is_sampled) return false
  return Math.abs(sceneTimestampNs(frame) - cursorNs) <= SAMPLE_LABEL_SNAP_NS
}

export function dedupeSampledTimestamps(frames: SampledFrame[]): number[] {
  const seen = new Set<number>()
  const out: number[] = []
  for (const f of frames.filter((x) => x.is_sampled)) {
    const bucket = Math.round(f.timestamp_ns / 1_000_000_000)
    if (!seen.has(bucket)) {
      seen.add(bucket)
      out.push(f.timestamp_ns)
    }
  }
  return out.sort((a, b) => a - b)
}
