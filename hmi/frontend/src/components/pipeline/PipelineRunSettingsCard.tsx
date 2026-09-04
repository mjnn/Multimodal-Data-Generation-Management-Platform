import { SaveOutlined } from '@ant-design/icons'
import { Alert, Button, Collapse, Select, Space, Typography, message } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../api'
import type {
  DataTypeRecipe,
  PipelineRunSettings,
  PlatformCatalog,
  RecipeGraph,
  RecipeGraphNode,
} from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { rememberDataTypeId } from '../../context/DataTypeWorkspaceContext'
import { apiErrorMessage } from '../../utils/apiError'
import {
  applyNodeParamOverrides,
  graphToSteps,
  hydrateGraphFromSteps,
  orderedGraphNodes,
  upstreamProductOptions,
} from '../../utils/recipeGraph'
import { hydrateRecipeToSteps } from '../../utils/recipePipeline'
import { sourceKindOptions } from '../../utils/fileKinds'
import { IfConditionForm, OpParamFields, SourceFields } from '../datatype/DagNodeInspector'
import '../datatype/PipelineOrchestrator.css'

const TYPE_TITLE: Record<string, string> = {
  source: '数据源',
  op: '算子',
  if: '条件',
  label: '打标器',
  review: '校核',
  export: '导出',
}

function patchNode(graph: RecipeGraph, key: string, patch: Partial<RecipeGraphNode>): RecipeGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.key === key ? { ...n, ...patch } : n)),
  }
}

function settingsFromGraph(graph: RecipeGraph, base: Partial<PipelineRunSettings>): Partial<PipelineRunSettings> {
  const extra: Partial<PipelineRunSettings> = {}
  for (const node of graph.nodes || []) {
    const params = node.params || {}
    const opId = String(node.op_id || '')
    if (opId === 'extract_frames' && typeof params.sample_fps === 'number') {
      extra.sample_fps = params.sample_fps
    }
    if (opId === 'label' && params.model) {
      extra.omni_model = String(params.model)
    }
    if (opId === 'detect_bbox') {
      extra.bbox_enabled = params.bbox_enabled !== false
      if (params.detector) extra.bbox_detector = String(params.detector)
      if (params.yolo_classes != null) extra.bbox_yolo_classes = String(params.yolo_classes)
    }
  }
  return { ...base, ...extra }
}

export function PipelineRunSettingsCard({
  dataTypeId,
  onDataTypeIdChange,
}: {
  dataTypeId?: string
  onDataTypeIdChange?: (id: string) => void
}) {
  const { dataSource } = useDataSourceMode()
  const cloud = dataSource === 'cloud'
  const [catalog, setCatalog] = useState<PlatformCatalog | null>(null)
  const [dataTypes, setDataTypes] = useState<DataTypeRecipe[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>(dataTypeId)
  const [graph, setGraph] = useState<RecipeGraph>({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [allOverrides, setAllOverrides] = useState<NonNullable<PipelineRunSettings['dag_node_overrides']>>({})

  const operators = catalog?.operators || []
  const selectedRecipe = useMemo(
    () => dataTypes.find((item) => item.id === selectedId) ?? null,
    [dataTypes, selectedId],
  )
  const ordered = useMemo(() => orderedGraphNodes(graph), [graph])
  const steps = useMemo(() => graphToSteps(graph), [graph])
  const kindOptions = sourceKindOptions(catalog?.source_kinds)

  const loadGraph = useCallback(
    async (dtypeId: string, overrides: NonNullable<PipelineRunSettings['dag_node_overrides']>, cat: PlatformCatalog) => {
      const rec = await api.getDataType(dtypeId)
      const ops = cat.operators || []
      const loadedSteps = hydrateRecipeToSteps(rec, ops, cat.type_provides || {})
      const base = rec.graph?.nodes?.length ? rec.graph : hydrateGraphFromSteps(loadedSteps)
      setGraph(applyNodeParamOverrides(base, overrides[dtypeId]))
    },
    [],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [cat, list, settingsRes] = await Promise.all([
        api.listPlatformCatalog(),
        api.listDataTypes(),
        api.getPipelineSettings(),
      ])
      setCatalog(cat)
      setDataTypes((list.items || []).filter((item) => item.status === 'published'))
      const ov = settingsRes.settings.dag_node_overrides || {}
      setAllOverrides(ov)
      const id = selectedId
      if (id) await loadGraph(id, ov, cat)
      else setGraph({ nodes: [], edges: [] })
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载执行参数失败'))
    } finally {
      setLoading(false)
    }
  }, [loadGraph, selectedId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (dataTypeId && dataTypeId !== selectedId) setSelectedId(dataTypeId)
  }, [dataTypeId, selectedId])

  const onSelectType = (value: string) => {
    setSelectedId(value)
    onDataTypeIdChange?.(value)
    rememberDataTypeId(value)
  }

  const save = async () => {
    if (!selectedId) return
    setSaving(true)
    try {
      const nodeMap: NonNullable<PipelineRunSettings['dag_node_overrides']>[string] = {}
      for (const node of graph.nodes) {
        const item: { params?: Record<string, unknown>; condition?: { all: { field: string; op: string; value?: unknown }[] } | null } =
          {}
        if (node.params) item.params = { ...node.params }
        if (node.type === 'if') item.condition = node.condition ? { all: node.condition.all || [] } : null
        if (item.params || item.condition !== undefined) nodeMap[node.key] = item
      }
      const nextOverrides = { ...allOverrides, [selectedId]: nodeMap }
      const extras = settingsFromGraph(graph, {})
      await api.savePipelineSettings({
        ...extras,
        dag_node_overrides: nextOverrides,
      })
      setAllOverrides(nextOverrides)
      message.success('节点参数已保存，下次开跑生效')
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const applyPatch = (key: string, patch: Partial<RecipeGraphNode>) => {
    setGraph((g) => patchNode(g, key, patch))
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} data-testid="pipeline-dag-params">
      {cloud ? (
        <Alert
          type="info"
          showIcon
          message="云端执行仍用 DataWorks 默认模板"
          description="此处保存的是本地配方节点参数覆盖，供本地开跑使用；不会改 DAG 顺序或连线。"
        />
      ) : (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          先选数据类型，再调整该 DAG 每个节点的参数。不能增删节点或改顺序；拓扑请到数据类型编辑器修改。
        </Typography.Paragraph>
      )}
      <Select
        data-testid="pipeline-dag-params-dtype"
        placeholder="先选择数据类型"
        style={{ width: '100%', maxWidth: 480 }}
        value={selectedId}
        options={dataTypes.map((item) => ({
          value: item.id,
          label: `${item.title}（${item.id}）`,
        }))}
        onChange={onSelectType}
      />
      {selectedRecipe ? (
        <Typography.Text type="secondary">{selectedRecipe.purpose}</Typography.Text>
      ) : null}
      {!selectedId ? (
        <Typography.Text type="secondary">请先选择数据类型，再调整各节点参数</Typography.Text>
      ) : loading ? (
        <Typography.Text type="secondary">加载节点…</Typography.Text>
      ) : ordered.length === 0 ? (
        <Typography.Text type="secondary">该类型还没有 DAG 节点</Typography.Text>
      ) : (
        <Collapse
          accordion
          items={ordered.map((node) => {
            const step = steps.find((s) => s.key === node.key)
            const extra =
              node.type === 'export' ? upstreamProductOptions(graph, node.key, operators) : []
            return {
              key: node.key,
              label: (
                <span data-testid={`pipeline-dag-node-${node.key}`}>
                  {node.title || node.key}
                  <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {TYPE_TITLE[node.type] || node.type}
                    {node.op_id ? ` · ${node.op_id}` : ''}
                  </Typography.Text>
                </span>
              ),
              children: (
                <div className="pipe-step__params">
                  {node.type === 'if' ? (
                    <IfConditionForm
                      key={node.key}
                      node={node}
                      onChange={(all) => applyPatch(node.key, { condition: { all } })}
                    />
                  ) : null}
                  {node.type === 'source' ? (
                    <SourceFields
                      node={node}
                      kindOptions={kindOptions}
                      onPatch={(patch) => applyPatch(node.key, patch)}
                    />
                  ) : null}
                  {node.type === 'op' || node.type === 'label' ? (
                    step ? (
                      <OpParamFields
                        node={node}
                        step={step}
                        operators={operators}
                        onPatch={(patch) => applyPatch(node.key, patch)}
                      />
                    ) : (
                      <Typography.Text type="secondary">此节点没有可调参数</Typography.Text>
                    )
                  ) : null}
                  {node.type === 'export' ? (
                    <div className="pipe-step__field" data-testid={`pipeline-dag-export-${node.key}`}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        上游产物
                      </Typography.Text>
                      <Select
                        mode="multiple"
                        allowClear
                        style={{ width: '100%' }}
                        value={(Array.isArray(node.params?.exported_product_ids)
                          ? node.params.exported_product_ids
                          : []
                        ).map(String)}
                        options={extra}
                        onChange={(v: string[]) =>
                          applyPatch(node.key, {
                            params: { ...(node.params || {}), exported_product_ids: v },
                          })
                        }
                      />
                    </div>
                  ) : null}
                  {node.type === 'review' ? (
                    <Typography.Text type="secondary">校核节点没有执行参数</Typography.Text>
                  ) : null}
                </div>
              ),
            }
          })}
        />
      )}
      <Button
        type="primary"
        icon={<SaveOutlined />}
        data-testid="pipeline-dag-params-save"
        disabled={!selectedId || loading}
        loading={saving}
        onClick={() => void save()}
      >
        保存节点参数
      </Button>
    </Space>
  )
}
