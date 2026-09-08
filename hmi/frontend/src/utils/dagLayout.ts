import ELK from 'elkjs/lib/elk.bundled.js'
import type { RecipeGraph } from '../api/types'

const elk = new ELK()

export async function layoutGraphElk(graph: RecipeGraph): Promise<RecipeGraph> {
  const children = (graph.nodes || []).map((n) => ({
    id: n.key,
    width: 208,
    height: n.type === 'if' ? 116 : 92,
  }))
  const edges = (graph.edges || []).map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }))
  const laid = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '48',
      'elk.layered.spacing.nodeNodeBetweenLayers': '88',
      'elk.edgeRouting': 'ORTHOGONAL',
    },
    children,
    edges,
  })
  const pos = new Map(
    (laid.children || []).map((c) => [String(c.id), { x: Number(c.x || 0), y: Number(c.y || 0) }]),
  )
  return {
    ...graph,
    nodes: (graph.nodes || []).map((n) => ({
      ...n,
      position: pos.get(n.key) || n.position || { x: 0, y: 0 },
    })),
  }
}
