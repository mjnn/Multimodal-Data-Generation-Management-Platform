import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  MiniMap,
  Panel,
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
import { graphToSteps, dropBindingsToRemoved } from '../../utils/recipeGraph'
import { displayNodeTitle, nextSourceTitle } from '../../utils/recipePipeline'
import { canConnectGraph, diagnoseGraph, graphPortFromHandle, outputHandleSpecs, rfHandleId } from '../../utils/ioContract'
import { layoutGraphElk } from '../../utils/dagLayout'
import { ComponentPalette, PALETTE_OP_MIME } from './ComponentPalette'
import './PipelineOrchestrator.css'
import './PipelineDagCanvas.css'

type DagNodeData = {
  type: GraphNodeType
  title: string
  op_id?: string
  ioWarn?: string
  outputHandles?: Array<{ id: string; title: string }>
}

type DagRfNode = Node<DagNodeData, GraphNodeType>

type Props = {
  graph: RecipeGraph
  onChange: (next: RecipeGraph) => void
  operators: PlatformOperator[]
  categoryTitles?: Record<string, string>
  selectedKey?: string | null
  onSelect?: (key: string | null) => void
  typeProvides?: Record<string, string[]>
  children?: ReactNode
}

const CONTROL_TITLES: Record<string, string> = {
  if: '条件',
  review: '校核',
  export: '导出',
  source: '数据源',
  label: 'AI打标器',
}

function toRfNodes(
  nodes: RecipeGraphNode[],
  operators: PlatformOperator[],
  graph: RecipeGraph,
  selectedKey?: string | null,
  typeProvides?: Record<string, string[]>,
): DagRfNode[] {
  const diag = diagnoseGraph(graph, operators, typeProvides || {})
  return (nodes || []).map((n) => ({
    id: n.key,
    type: n.type,
    position: n.position || { x: 0, y: 0 },
    data: {
      type: n.type,
      title: displayNodeTitle(n, operators),
      op_id: n.op_id,
      ioWarn: diag[n.key]?.level === 'warn' ? diag[n.key].message : '',
      outputHandles: outputHandleSpecs(n, operators),
    },
    deletable: true,
    selected: selectedKey === n.key,
  }))
}

const EDGE_ARROW: DefaultEdgeOptions = {
  type: 'smoothstep',
  markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
}

function edgeAppearance(port: string): { className: string; stroke?: string; label?: string } {
  if (port === 'then') return { className: 'dag-edge--then', stroke: '#27a644', label: 'then' }
  if (port === 'else') return { className: 'dag-edge--else', stroke: '#c43c3c', label: 'else' }
  return { className: '' }
}

function toRfEdges(edges: RecipeGraphEdge[]): Edge[] {
  return (edges || []).map((e) => {
    const port = e.source_port || 'out'
    const look = edgeAppearance(port)
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: rfHandleId(port),
      targetHandle: rfHandleId(e.target_port || 'in'),
      type: 'smoothstep',
      className: look.className,
      data: { sourcePort: port, label: look.label || '' },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 18,
        height: 18,
        ...(look.stroke ? { color: look.stroke } : {}),
      },
      style: look.stroke ? { stroke: look.stroke, strokeWidth: 1.8 } : undefined,
    }
  })
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
      {data.ioWarn ? (
        <span
          className="dag-node__io-warn"
          data-testid={`dag-io-warn-${id}`}
          title={data.ioWarn}
          aria-label={data.ioWarn}
        >
          !
        </span>
      ) : null}
      {isLabel ? (
        <div className="dag-node__title" data-testid="dag-node-label">
          {data.title || 'AI打标器'}
        </div>
      ) : (
        <div className="dag-node__title">{data.title || id}</div>
      )}
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
      {data.op_id ? <div className="dag-node__op">{data.op_id}</div> : null}
      {!isSource ? <Handle type="target" position={Position.Left} id="in" className="dag-handle dag-handle--in" /> : null}
      {isIf ? (
        <>
          <span className="dag-node__port-tag dag-node__port-tag--then">then</span>
          <span className="dag-node__port-tag dag-node__port-tag--else">else</span>
          <Handle type="source" position={Position.Right} id="then" className="dag-handle dag-handle--then" style={{ top: '36%' }} />
          <Handle type="source" position={Position.Right} id="else" className="dag-handle dag-handle--else" style={{ top: '72%' }} />
        </>
      ) : isExport ? null : (data.outputHandles || [{ id: 'out', title: 'out' }]).length > 1 ? (
        <>
          <div className="dag-node__ports dag-node__ports--out">
            {(data.outputHandles || []).map((h) => (
              <span key={h.id}>{h.title}</span>
            ))}
          </div>
          {(data.outputHandles || []).map((h, i, arr) => (
            <Handle
              key={h.id}
              type="source"
              position={Position.Right}
              id={h.id}
              className="dag-handle"
              style={{ top: `${((i + 1) / (arr.length + 1)) * 100}%` }}
            />
          ))}
        </>
      ) : (
        <Handle
          type="source"
          position={Position.Right}
          id={data.outputHandles?.[0]?.id || 'out'}
          className="dag-handle"
        />
      )}
    </div>
  )
}

function DagEdge(props: EdgeProps) {
  const { id, selected, markerEnd, style, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data } =
    props
  const { deleteElements } = useReactFlow()
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })
  const portLabel = String((data as { label?: string } | undefined)?.label || '')
  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <div
          className={`nodrag nopan dag-edge__label${selected ? ' is-selected' : ''}${portLabel ? ` dag-edge__label--${portLabel}` : ''}`}
          data-testid={`dag-edge-${id}`}
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: 'all',
          }}
        >
          {portLabel ? <span className="dag-edge__port">{portLabel}</span> : null}
          <button
            type="button"
            className="dag-edge__remove"
            data-testid={`dag-remove-edge-${id}`}
            aria-label="删除连线"
            onClick={(e) => {
              e.stopPropagation()
              void deleteElements({ edges: [{ id }] })
            }}
          >
            ×
          </button>
        </div>
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

/** 校核/导出 stay as node types for old graphs, but are not offered in the palette. */
const PALETTE_EXTRAS = [
  {
    id: 'control',
    groupTitle: '控制流',
    items: [
      { id: 'source', title: '数据源', testId: 'palette-op-source' },
      { id: 'if', title: '条件 if / else', testId: 'palette-op-if' },
    ],
  },
]

function PipelineDagCanvasInner({
  graph,
  onChange,
  operators,
  categoryTitles,
  selectedKey,
  onSelect,
  typeProvides,
  children,
}: Props) {
  const graphRef = useRef(graph)
  graphRef.current = graph
  const { fitView, screenToFlowPosition } = useReactFlow()
  const nodesInitialized = useNodesInitialized()
  const structureKey = `${graph.nodes.map((n) => n.key).join('|')}::${graph.edges.map((e) => e.id).join('|')}`
  const dataKey = graph.nodes
    .map((n) => `${n.key}:${n.title}:${n.type}:${n.op_id ?? ''}:${JSON.stringify(n.params || {})}`)
    .join('|')
  const hasLabel = graph.nodes.some((n) => n.type === 'label')
  const opTitleKey = operators.map((o) => `${o.op_id}:${o.title}`).join('|')
  const [rfNodes, setRfNodes] = useState(() =>
    toRfNodes(graph.nodes, operators, graph, selectedKey, typeProvides),
  )
  const [rfEdges, setRfEdges] = useState(() => toRfEdges(graph.edges))

  useEffect(() => {
    setRfNodes(toRfNodes(graph.nodes, operators, graph, selectedKey, typeProvides))
    setRfEdges(toRfEdges(graph.edges))
    // structureKey covers add/remove/connect; dataKey covers title edits from inspector.
  }, [structureKey, dataKey, opTitleKey, graph, operators, selectedKey, typeProvides])

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
      if (!changes.length) return
      setRfNodes((curr) => applyNodeChanges(changes, curr))
      const removed = new Set(
        changes.filter((c) => c.type === 'remove' && 'id' in c).map((c) => (c as { id: string }).id),
      )
      if (!removed.size) return
      if (selectedKey && removed.has(selectedKey)) onSelect?.(null)
      applyGraph({
        nodes: dropBindingsToRemoved(g, removed),
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
      if (!canConnectGraph(g, operators, typeProvides || {}, conn)) return
      const sourcePort = graphPortFromHandle(conn.sourceHandle)
      const targetPort = conn.targetHandle ? graphPortFromHandle(conn.targetHandle) : 'in'
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
    [onChange, operators, typeProvides],
  )

  const addFromPalette = useCallback(
    (opId: string, position?: { x: number; y: number }) => {
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
      if (opId === 'json_extract') params.path_keys = ['']
      if (opId === 'label_tree_input') params.assignments = []
      const node: RecipeGraphNode = {
        key,
        type: ntype,
        op_id: ntype === 'if' || ntype === 'review' || ntype === 'export' ? ntype : opId,
        title,
        params,
        condition: ntype === 'if' ? { all: [] } : undefined,
        position: position || {
          x: 48 + (g.nodes.length % 3) * 240,
          y: 48 + Math.floor(g.nodes.length / 3) * 120,
        },
      }
      const selected = selectedKey ? g.nodes.find((n) => n.key === selectedKey) : undefined
      let edges = g.edges
      if (!position && selected && ntype !== 'source' && selected.type !== 'export') {
        const sourcePort = selected.type === 'if' ? 'then' : 'out'
        const eid = `${selected.key}-${sourcePort}->${key}-in`
        if (!edges.some((e) => e.id === eid)) {
          edges = [
            ...edges,
            {
              id: eid,
              source: selected.key,
              source_port: sourcePort,
              target: key,
              target_port: 'in',
            },
          ]
        }
      }
      onChange({ ...g, nodes: [...g.nodes, node], edges })
    },
    [onChange, operators, selectedKey],
  )

  const onNodeDragStop = useCallback(
    (_evt: MouseEvent | TouchEvent, node: DagRfNode, dragged: DagRfNode[]) => {
      const g = graphRef.current
      const patches = dragged.length ? dragged : [node]
      onChange({ ...g, nodes: persistNodePositions(g, patches) })
    },
    [onChange],
  )

  const onPaletteDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      const opId = e.dataTransfer.getData(PALETTE_OP_MIME) || e.dataTransfer.getData('text/plain')
      if (!opId.trim()) return
      const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      addFromPalette(opId.trim(), pos)
    },
    [addFromPalette, screenToFlowPosition],
  )

  const onAutoLayout = useCallback(() => {
    void layoutGraphElk(graphRef.current).then((next) => {
      onChange(next)
      window.setTimeout(() => {
        void fitView({ padding: 0.18, duration: 200 })
      }, 40)
    })
  }, [fitView, onChange])

  return (
    <div className="pipe-orch">
      <ComponentPalette
        operators={operators}
        categoryTitles={categoryTitles}
        onAdd={addFromPalette}
        hideOpIds={hasLabel ? ['label'] : []}
        extras={PALETTE_EXTRAS}
      />
      <div
        className="dag-canvas"
        data-testid="dag-canvas"
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
        }}
        onDrop={onPaletteDrop}
      >
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={DAG_NODE_TYPES}
          edgeTypes={DAG_EDGE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={(c) => canConnectGraph(graphRef.current, operators, typeProvides || {}, c)}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(evt, node) => {
            evt.stopPropagation()
            onSelect?.(node.id)
          }}
          onPaneClick={() => onSelect?.(null)}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 1, minZoom: 0.4 }}
          minZoom={0.2}
          deleteKeyCode={['Backspace', 'Delete']}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={EDGE_ARROW}
        >
          <Background gap={18} size={1} />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap pannable zoomable position="bottom-right" />
          <Panel position="top-left">
            <button type="button" className="dag-auto-layout" data-testid="dag-auto-layout" onClick={onAutoLayout}>
              自动排布
            </button>
          </Panel>
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
