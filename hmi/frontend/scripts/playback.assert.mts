/**
 * Smoke asserts for src/utils/playback.ts (no vitest in frontend package).
 * Run from hmi/frontend:
 *   node --experimental-strip-types scripts/playback.assert.mts
 */
import {
  advancePlayhead,
  isNearClipEnd,
  NEAR_END_NS,
  PLAYHEAD_TICK_S,
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

let head = 0
for (let i = 0; i < 10; i += 1) {
  const step = advancePlayhead(head, 16.5)
  assert(!step.ended, `tick ${i} should not end`)
  assert(Math.abs(step.nextS - (i + 1) * PLAYHEAD_TICK_S) < 1e-9, 'ticks accumulate, not freeze at start+dt')
  head = step.nextS
}
assert(Math.abs(head - 1.0) < 1e-9, '10 ticks at 0.1s = 1.0s')
const last = advancePlayhead(16.4, 16.5)
assert(last.nextS === 16.5 && last.ended, 'tick past duration ends')

console.log('playback.assert.mts: ok')
