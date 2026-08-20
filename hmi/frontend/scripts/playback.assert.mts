/**
 * Smoke asserts for src/utils/playback.ts (no vitest in frontend package).
 * Run from hmi/frontend:
 *   node --experimental-strip-types scripts/playback.assert.mts
 */
import {
  isNearClipEnd,
  NEAR_END_NS,
  replayFromStart,
  togglePlayWithReplay,
} from '../src/utils/playback.ts'

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg)
}

const start = 1_000_000_000
const end = start + 5_000_000_000

assert(!isNearClipEnd(start, start, end), 'start is not near end')
assert(!isNearClipEnd(end - NEAR_END_NS - 1, start, end), 'just outside threshold')
assert(isNearClipEnd(end - NEAR_END_NS, start, end), 'at threshold is near end')
assert(isNearClipEnd(end, start, end), 'exact end is near end')
assert(!isNearClipEnd(start, start, start), 'zero-length clip')

let cursor = end
let playing = false as boolean
togglePlayWithReplay({
  playing,
  cursorNs: cursor,
  startNs: start,
  endNs: end,
  onCursorChange: (ns) => {
    cursor = ns
  },
  onPlayingChange: (v) => {
    playing = v
  },
})
assert(cursor === start, 'play at end seeks to start')
assert(playing === true, 'play at end starts playing')

playing = true
togglePlayWithReplay({
  playing,
  cursorNs: cursor,
  startNs: start,
  endNs: end,
  onCursorChange: (ns) => {
    cursor = ns
  },
  onPlayingChange: (v) => {
    playing = v
  },
})
assert(playing === false, 'toggle pauses')
assert(cursor === start, 'pause does not move cursor')

cursor = start + 1_000_000_000
playing = false
togglePlayWithReplay({
  playing,
  cursorNs: cursor,
  startNs: start,
  endNs: end,
  onCursorChange: (ns) => {
    cursor = ns
  },
  onPlayingChange: (v) => {
    playing = v
  },
})
assert(cursor === start + 1_000_000_000, 'mid-clip play does not seek')
assert(playing === true, 'mid-clip play starts')

cursor = end
playing = false
replayFromStart({
  startNs: start,
  onCursorChange: (ns) => {
    cursor = ns
  },
  onPlayingChange: (v) => {
    playing = v
  },
})
assert(cursor === start && playing === true, 'replayFromStart seeks and plays')

console.log('playback.assert.mts: ok')
