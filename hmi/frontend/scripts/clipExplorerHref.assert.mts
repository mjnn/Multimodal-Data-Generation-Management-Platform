/**
 * Smoke asserts for src/utils/clipExplorerHref.ts (no vitest in frontend package).
 * Run from hmi/frontend:
 *   node --experimental-strip-types scripts/clipExplorerHref.assert.mts
 */
import { buildClipExplorerHref } from '../src/utils/clipExplorerHref.ts'

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg)
}

assert(
  buildClipExplorerHref('clip-a') === '/clips/clip-a',
  'clip only',
)
assert(
  buildClipExplorerHref('clip-a', { runId: 'run-1' }) === '/clips/clip-a?run_id=run-1',
  'run_id',
)
assert(
  buildClipExplorerHref('clip-a', { runId: 'run-1', dataTypeId: 'audio_defect' }) ===
    '/clips/clip-a?run_id=run-1&data_type_id=audio_defect',
  'run + data type',
)
assert(
  buildClipExplorerHref('c/id', { runId: 'r', dataTypeId: 'oms_cabin', t: 12 }) ===
    '/clips/c%2Fid?run_id=r&data_type_id=oms_cabin&t=12',
  'encodes clip id and keeps t',
)
assert(buildClipExplorerHref('clip-a', { runId: '  ', dataTypeId: '' }) === '/clips/clip-a', 'blank opts omitted')

console.log('clipExplorerHref.assert.mts ok')
