/** Default: treat cursor within 100ms of end as "at end" for replay-on-play. */
export const NEAR_END_NS = 100_000_000

export function isNearClipEnd(
  cursorNs: number,
  startNs: number,
  endNs: number,
  nearEndNs: number = NEAR_END_NS,
): boolean {
  if (!(endNs > startNs)) return false
  const threshold = Math.max(startNs, endNs - nearEndNs)
  return cursorNs >= threshold
}

/**
 * Toggle play/pause. When starting play while at/near end, seek to start first
 * (common media UX: play again = replay from beginning).
 */
export function togglePlayWithReplay(opts: {
  playing: boolean
  cursorNs: number
  startNs: number
  endNs: number
  onCursorChange: (ns: number) => void
  onPlayingChange: (playing: boolean) => void
  nearEndNs?: number
}): void {
  const {
    playing,
    cursorNs,
    startNs,
    endNs,
    onCursorChange,
    onPlayingChange,
    nearEndNs = NEAR_END_NS,
  } = opts
  if (playing) {
    onPlayingChange(false)
    return
  }
  if (isNearClipEnd(cursorNs, startNs, endNs, nearEndNs)) {
    onCursorChange(startNs)
  }
  onPlayingChange(true)
}

/** Explicit restart: seek to start and begin playing. */
export function replayFromStart(opts: {
  startNs: number
  onCursorChange: (ns: number) => void
  onPlayingChange: (playing: boolean) => void
}): void {
  opts.onCursorChange(opts.startNs)
  opts.onPlayingChange(true)
}
