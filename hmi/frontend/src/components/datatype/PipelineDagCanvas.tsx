import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  getSmoothStepPath,
  useNodesInitialized,
  useReactFlow,
  type Connection,
  type DefaultEdgeOptions,
  type Edge,
  type EdgeChange,
  type EdgeProps,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { GraphNodeType, PlatformOperator, RecipeGraph, RecipeGraphEdge, RecipeGraphNode } from '../../api/types'
import { graphToSteps } from '../../utils/recipeGraph'
import { nextSourceTitle } from '../../utils/recipePipeline'
import { ComponentPalette } from './ComponentPalette'
import './PipelineOrchestrator.css'
import './PipelineDagCanvas.css'

type DagNodeData = { type: GraphNodeType; title: string; op_id?: string }

type DagRfNode = Node<DagNodeData, GraphNodeType>

type Props = {
  graph: RecipeGraph
  onChange: (next: RecipeGraph) => void
  operators: PlatformOperator[]
  categoryTitles?: Record<string, string>
  selectedKey?: string | null
  onSelect?: (key: string | null) => void
  children?: ReactNode
}

const CONTROL_TITLES: Record<string, string> = {
  if: '条件',
  review: '校核',
  export: '导出',
  source: '数据源',
  label: '打标器',
}

function toRfNodes(nodes: RecipeGraphNode[], selectedKey?: string | null): DagRfNode[] {
  return (nodes || []).map((n) => ({
    id: n.key,
    type: n.type,
    position: n.position || { x: 0, y: 0 },
    data: { type: n.type, title: n.title, op_id: n.op_id },
    deletable: n.type !== 'label',
    selected: selectedKey === n.key,
  }))
}

const EDGE_ARROW: DefaultEdgeOptions = {
  type: 'smoothstep',
  markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
}

function toRfEdges(edges: RecipeGraphEdge[]): Edge[] {
  return (edges || []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_port,
    targetHandle: e.target_port,
    ...EDGE_ARROW,
  }))
}

/** Merge xyflow positions onto the recipe graph. Never drop nodes: xyflow's
 * onNodeDragStop third argument is the dragged subset, not the full canvas. */
function persistNodePositions(
  graph: RecipeGraph,
  rfNodes: Array<{ id: string; position: { x: number; y: number } }>,
): RecipeGraphNode[] {
  const byId = new Map(rfNodes.map((n) => [n.id, n]))
  return graph.nodes.map((n) => {
    const rf = byId.get(n.key)
    return rf ? { ...n, position: { ...rf.position } } : n
  })
}

function DagFlowNode({ id, data }: NodeProps<DagRfNode>) {
  const { deleteElements } = useReactFlow()
  const ntype = data.type
  const isIf = ntype === 'if'
  const isSource = ntype === 'source'
  const isExport = ntype === 'export'
  const isLabel = ntype === 'label'
  return (
    <div className={`dag-node dag-node--${ntype}`} data-testid={`dag-node-${id}`}>
      {isLabel ? (
        <div className="dag-node__title" data-testid="dag-node-label">
          {data.title || '打标器'}
        </div>
      ) : (
        <>
          <div className="dag-node__title">{data.title || id}</div>
          <button
            type="button"
            className="nodrag nopan dag-node__remove"
            data-testid={`dag-remove-${id}`}
            aria-label="删除节点"
            onClick={(e) => {
              e.stopPropagation()
              void deleteElements({ nodes: [{ id }] })
            }}
          >
            ×
          </button>
        </>
      )}
      {data.op_id ? <div className="dag-node__op">{data.op_id}</div> : null}
      {!isSource ? <Handle type="target" position={Position.Top} id="in" /> : null}
      {isIf ? (
        <>
          <div className="dag-node__ports">
            <span>then</span>
            <span>else</span>
          </div>
          <Handle type="source" position={Position.Bottom} id="then" style={{ left: '30%' }} />
          <Handle type="source" position={Position.Bottom} id="else" style={{ left: '70%' }} />
        </>
      ) : isExport ? null : (
        <Handle type="source" position={Position.Bottom} id="out" />
      )}
    </div>
  )
}

function DagEdge(props: EdgeProps) {
  const { id, selected, markerEnd, style, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props
  const { deleteElements } = useReactFlow()
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <button
          type="button"
          className={`nodrag nopan dag-edge__remove${selected ? ' is-selected' : ''}`}
          data-testid={`dag-remove-edge-${id}`}
          aria-label="删除连线"
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: 'all',
          }}
          onClick={(e) => {
            e.stopPropagation()
            void deleteElements({ edges: [{ id }] })
          }}
        >
          ×
        </button>
      </EdgeLabelRenderer>
    </>
  )
}

const DAG_NODE_TYPES: NodeTypes = {
  source: DagFlowNode,
  op: DagFlowNode,
  if: DagFlowNode,
  label: DagFlowNode,
  review: DagFlowNode,
  export: DagFlowNode,
}

const DAG_EDGE_TYPES: EdgeTypes = {
  smoothstep: DagEdge,
}

const PALETTE_EXTRAS = [
  {
    id: 'control',
    groupTitle: '控制流',
    items: [
      { id: 'source', title: '数据源', testId: 'palette-op-source' },
      { id: 'if', title: '条件 if / else', testId: 'palette-op-if' },
      { id: 'review', title: '校核', testId: 'palette-op-review' },
      { id: 'export', title: '导出', testId: 'palette-op-export' },
    ],
  },
]

function PipelineDagCanvasInner({ graph, onChange, operators, categoryTitles, selectedKey, onSelect, children }: Props) {
  const graphRef = useRef(graph)
  graphRef.current = graph
  const { fitView } = useReactFlow()
  const nodesInitialized = useNodesInitialized()
  const structureKey = `${graph.nodes.map((n) => n.key).join('|')}::${graph.edges.map((e) => e.id).join('|')}`
  const dataKey = graph.nodes.map((n) => `${n.key}:${n.title}:${n.type}:${n.op_id ?? ''}`).join('|')
  const hasLabel = graph.nodes.some((n) => n.type === 'label')
  const [rfNodes, setRfNodes] = useState(() => toRfNodes(graph.nodes, selectedKey))
  const [rfEdges, setRfEdges] = useState(() => toRfEdges(graph.edges))

  useEffect(() => {
    setRfNodes(toRfNodes(graph.nodes, selectedKey))
    setRfEdges(toRfEdges(graph.edges))
    // structureKey covers add/remove/connect; dataKey covers title edits from inspector.
  }, [structureKey, dataKey])

  useEffect(() => {
    setRfNodes((curr) => curr.map((n) => ({ ...n, selected: n.id === selectedKey })))
  }, [selectedKey])

  useEffect(() => {
    if (!nodesInitialized) return
    const t = window.setTimeout(() => {
      void fitView({ padding: 0.2, duration: 0 })
    }, 40)
    return () => window.clearTimeout(t)
  }, [fitView, nodesInitialized, structureKey])

  const applyGraph = useCallback(
    (next: RecipeGraph) => {
      graphRef.current = next
      onChange(next)
    },
    [onChange],
  )

  const onNodesChange = useCallback(
    (changes: NodeChange<DagRfNode>[]) => {
      const g = graphRef.current
      const labelKeys = new Set(g.nodes.filter((n) => n.type === 'label').map((n) => n.key))
      const filtered = changes.filter((c) => !(c.type === 'remove' && 'id' in c && labelKeys.has(c.id)))
      if (!filtered.length) return
      setRfNodes((curr) => applyNodeChanges(filtered, curr))
      const removed = new Set(
        filtered.filter((c) => c.type === 'remove' && 'id' in c).map((c) => (c as { id: string }).id),
      )
      if (!removed.size) return
      if (selectedKey && removed.has(selectedKey)) onSelect?.(null)
      applyGraph({
        nodes: g.nodes.filter((n) => !removed.has(n.key)),
        edges: g.edges.filter((e) => !removed.has(e.source) && !removed.has(e.target)),
      })
    },
    [applyGraph, onSelect, selectedKey],
  )

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setRfEdges((curr) => applyEdgeChanges(changes, curr))
      const removed = new Set(changes.filter((c) => c.type === 'remove').map((c) => c.id))
      if (!removed.size) return
      const g = graphRef.current
      applyGraph({
        ...g,
        edges: g.edges.filter((e) => !removed.has(e.id)),
      })
    },
    [applyGraph],
  )

  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return
      const g = graphRef.current
      const sourcePort = conn.sourceHandle || 'out'
      const targetPort = conn.targetHandle || 'in'
      const id = `${conn.source}-${sourcePort}->${conn.target}-${targetPort}`
      if (g.edges.some((e) => e.id === id)) return
      const edge: RecipeGraphEdge = {
        id,
        source: conn.source,
        source_port: sourcePort,
        target: conn.target,
        target_port: targetPort,
      }
      onChange({ ...g, edges: [...g.edges, edge] })
    },
    [onChange],
  )

  const addFromPalette = useCallback(
    (opId: string) => {
      const g = graphRef.current
      if (opId === 'label' && g.nodes.some((n) => n.type === 'label')) return
      const key = `op-${opId}-${Date.now()}`
      let ntype: GraphNodeType = 'op'
      if (opId === 'label') ntype = 'label'
      else if (opId === 'if') ntype = 'if'
      else if (opId === 'review') ntype = 'review'
      else if (opId === 'export') ntype = 'export'
      else if (opId === 'source') ntype = 'source'
      const op = operators.find((item) => item.op_id === opId)
      let title = CONTROL_TITLES[opId] || op?.title || opId
      if (ntype === 'source') title = nextSourceTitle(graphToSteps(g))
      const params: Record<string, unknown> = {}
      if (ntype === 'source') {
        params.kinds = ['.mp4']
        params.required = true
        params.cardinality_min = 1
        params.cardinality_max = 1
      }
      if (ntype === 'label') params.model = 'default'
      const node: RecipeGraphNode = {
        key,
        type: ntype,
        op_id: ntype === 'if' || ntype === 'review' || ntype === 'export' ? ntype : opId,
        title,
        params,
        condition: ntype === 'if' ? { all: [] } : undefined,
        position: { x: 320, y: 80 * g.nodes.length },
      }
      onChange({ ...g, nodes: [...g.nodes, node] })
    },
    [onChange, operators],
  )

  const onNodeDragStop = useCallback(
    (_evt: MouseEvent | TouchEvent, node: DagRfNode, dragged: DagRfNode[]) => {
      const g = graphRef.current
      const patches = dragged.length ? dragged : [node]
      onChange({ ...g, nodes: persistNodePositions(g, patches) })
    },
    [onChange],
  )

  return (
    <div className="pipe-orch">
      <ComponentPalette
        operators={operators}
        categoryTitles={categoryTitles}
        onAdd={addFromPalette}
        hideOpIds={hasLabel ? ['label'] : []}
        extras={PALETTE_EXTRAS}
      />
      <div className="dag-canvas" data-testid="dag-canvas">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={DAG_NODE_TYPES}
          edgeTypes={DAG_EDGE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(_evt, node) => onSelect?.(node.id)}
          onPaneClick={() => onSelect?.(null)}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1, minZoom: 0.4 }}
          minZoom={0.2}
          deleteKeyCode={['Backspace', 'Delete']}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={EDGE_ARROW}
        >
          <Background gap={18} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
        {children}
      </div>
    </div>
  )
}

export function PipelineDagCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <PipelineDagCanvasInner {...props} />
    </ReactFlowProvider>
  )
}
