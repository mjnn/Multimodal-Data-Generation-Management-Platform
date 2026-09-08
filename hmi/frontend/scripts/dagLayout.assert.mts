/**
 * Smoke asserts for dagLayout.layoutGraphElk.
 *   node --experimental-strip-types scripts/dagLayout.assert.mts
 */
import { layoutGraphElk } from '../src/utils/dagLayout.ts'
import type { RecipeGraph } from '../src/api/types.ts'

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg)
}

const graph: RecipeGraph = {
  nodes: [
    { key: 'wav', type: 'source', title: '录音', params: { kinds: ['.wav'] }, position: { x: 0, y: 0 } },
    { key: 'js', type: 'op', op_id: 'json_extract', title: '提取', params: {}, position: { x: 0, y: 0 } },
    { key: 'lab', type: 'label', op_id: 'label', title: '打标', params: {}, position: { x: 0, y: 0 } },
  ],
  edges: [
    { id: 'wav-out->js-in', source: 'wav', source_port: 'out', target: 'js', target_port: 'in' },
    { id: 'js-out->lab-in', source: 'js', source_port: 'out', target: 'lab', target_port: 'in' },
  ],
}

const laid = await layoutGraphElk(graph)
assert(laid.nodes.length === 3, 'layout keeps nodes')
assert(
  laid.nodes.every((n) => Number.isFinite(n.position?.x) && Number.isFinite(n.position?.y)),
  'layout writes positions',
)
assert(
  new Set(laid.nodes.map((n) => `${n.position?.x},${n.position?.y}`)).size >= 2,
  'layout spreads at least two nodes',
)

console.log('dagLayout.assert.mts ok')
