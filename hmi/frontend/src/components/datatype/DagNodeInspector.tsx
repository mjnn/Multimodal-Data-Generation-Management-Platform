import { CloseOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { AutoComplete, Button, Form, Input, InputNumber, Select, Space, Switch, Typography } from 'antd'
import type { GraphConditionPred, PipelineBinding, PipelinePortBindings, PipelineStep, PlatformOperator, RecipeGraph, RecipeGraphNode } from '../../api/types'
import { PARSE_BAG_MODALITIES, sourceKindOptions } from '../../utils/fileKinds'
import {
  asBindingList,
  bindingOptions,
  decodeBinding,
  encodeBinding,
  getOp,
  inputPorts,
  slotsFromSteps,
  typeLabel,
} from '../../utils/recipePipeline'
import { graphToSteps, upstreamProductOptions } from '../../utils/recipeGraph'
import './PipelineOrchestrator.css'
import './DagNodeInspector.css'

const FIELD_PRESETS = [
  { value: 'source.kind', label: 'source.kind' },
  { value: 'source.slot_id', label: 'source.slot_id' },
  { value: 'asr.avg_confidence', label: 'asr.avg_confidence' },
  { value: 'asr.has_text', label: 'asr.has_text' },
  { value: 'label.avg_confidence', label: 'label.avg_confidence' },
  { value: 'labels.', label: 'labels.*（自定义）' },
]

const OP_OPTIONS = [
  { value: 'eq', label: 'eq' },
  { value: 'neq', label: 'neq' },
  { value: 'gt', label: 'gt' },
  { value: 'gte', label: 'gte' },
  { value: 'lt', label: 'lt' },
  { value: 'lte', label: 'lte' },
  { value: 'in', label: 'in' },
  { value: 'not_in', label: 'not_in' },
  { value: 'exists', label: 'exists' },
  { value: 'not_exists', label: 'not_exists' },
]

const LABEL_MODELS = [
  { value: 'default', label: 'default（SDK Omni）' },
  { value: 'nvh_sem_ast', label: 'nvh_sem_ast' },
  { value: 'nvh_sem_heuristic', label: 'nvh_sem_heuristic' },
]

const NO_VALUE_OPS = new Set(['exists', 'not_exists'])

type Props = {
  graph: RecipeGraph
  selectedKey: string | null
  onChange: (next: RecipeGraph) => void
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  sourceKinds?: string[]
  disabled?: boolean
  onClose?: () => void
}

function patchNode(graph: RecipeGraph, key: string, patch: Partial<RecipeGraphNode>): RecipeGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.key === key ? { ...n, ...patch } : n)),
  }
}

function normalizePreds(raw: GraphConditionPred[] | undefined): GraphConditionPred[] {
  return (raw || []).map((p) => {
    const op = String(p.op || 'eq')
    const item: GraphConditionPred = { field: String(p.field || '').trim(), op }
    if (!NO_VALUE_OPS.has(op)) item.value = p.value
    return item
  })
}

function PredicateValueItem({ name }: { name: number }) {
  const op = Form.useWatch(['all', name, 'op']) as string | undefined
  if (NO_VALUE_OPS.has(String(op || ''))) return null
  return (
    <Form.Item name={[name, 'value']} style={{ marginBottom: 0, flex: 1, minWidth: 80 }}>
      <Input placeholder="value" />
    </Form.Item>
  )
}

export function IfConditionForm({
  node,
  disabled,
  onChange,
}: {
  node: RecipeGraphNode
  disabled?: boolean
  onChange: (all: GraphConditionPred[]) => void
}) {
  return (
    <Form
      component="div"
      layout="vertical"
      size="small"
      disabled={disabled}
      initialValues={{ all: node.condition?.all?.length ? node.condition.all : [] }}
      onValuesChange={(_changed, values: { all?: GraphConditionPred[] }) => {
        onChange(normalizePreds(values.all))
      }}
    >
      <Form.List name="all">
        {(fields, { add, remove }) => (
          <div className="dag-inspector__preds">
            {fields.map((field) => (
              <Space key={field.key} align="start" wrap className="dag-inspector__pred">
                <Form.Item name={[field.name, 'field']} style={{ marginBottom: 0, minWidth: 160 }}>
                  <AutoComplete
                    options={FIELD_PRESETS}
                    placeholder="字段"
                    filterOption={(input, option) =>
                      String(option?.value || '').toLowerCase().includes(input.toLowerCase())
                    }
                  />
                </Form.Item>
                <Form.Item name={[field.name, 'op']} style={{ marginBottom: 0, width: 110 }}>
                  <Select options={OP_OPTIONS} placeholder="op" />
                </Form.Item>
                <PredicateValueItem name={field.name} />
                <Button
                  type="text"
                  danger
                  icon={<MinusCircleOutlined />}
                  onClick={() => remove(field.name)}
                />
              </Space>
            ))}
            <Button
              type="dashed"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => add({ field: 'source.kind', op: 'eq', value: '' })}
            >
              添加条件
            </Button>
          </div>
        )}
      </Form.List>
    </Form>
  )
}

export function SourceFields({
  node,
  kindOptions,
  onPatch,
}: {
  node: RecipeGraphNode
  kindOptions: { value: string; label: string }[]
  onPatch: (patch: Partial<RecipeGraphNode>) => void
}) {
  const params = node.params || {}
  const kinds = Array.isArray(params.kinds) ? params.kinds.map((x) => String(x)) : []
  const setParam = (key: string, value: unknown) => {
    onPatch({ params: { ...params, [key]: value } })
  }
  return (
    <div className="pipe-step__params">
      <div className="pipe-step__field" style={{ minWidth: 160 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>名称</Typography.Text>
        <Input value={node.title || ''} onChange={(e) => onPatch({ title: e.target.value })} />
      </div>
      <div className="pipe-step__field" style={{ minWidth: 200, flex: 1 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>允许后缀</Typography.Text>
        <Select
          mode="multiple"
          allowClear
          placeholder="至少一种后缀"
          style={{ width: '100%' }}
          options={kindOptions}
          value={kinds}
          onChange={(v: string[]) => setParam('kinds', v || [])}
        />
      </div>
      <div className="pipe-step__field" style={{ width: 88 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>最少</Typography.Text>
        <InputNumber
          min={0}
          max={64}
          style={{ width: '100%' }}
          value={Number(params.cardinality_min ?? 1)}
          onChange={(v) => setParam('cardinality_min', Number(v ?? 1))}
        />
      </div>
      <div className="pipe-step__field" style={{ width: 88 }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>最多</Typography.Text>
        <InputNumber
          min={1}
          max={64}
          style={{ width: '100%' }}
          value={Number(params.cardinality_max ?? 1)}
          onChange={(v) => setParam('cardinality_max', Number(v ?? 1))}
        />
      </div>
      <div className="pipe-step__field">
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>必填</Typography.Text>
        <Switch checked={params.required !== false} onChange={(v) => setParam('required', v)} />
      </div>
    </div>
  )
}

function OpBindFields({
  node,
  step,
  steps,
  operators,
  typeProvides,
  onPatch,
}: {
  node: RecipeGraphNode
  step: PipelineStep
  steps: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  onPatch: (patch: Partial<RecipeGraphNode>) => void
}) {
  const op = getOp(operators, step.op_id)
  const ins = inputPorts(op)
  const slots = slotsFromSteps(steps)
  const upstream = steps.filter((s) => s.key !== step.key)
  const setBinding = (portId: string, value: string | string[] | null, multiple: boolean) => {
    const bindings: Record<string, PipelinePortBindings> = { ...(node.bindings || {}) }
    if (multiple) {
      const list = (Array.isArray(value) ? value : [])
        .map((v) => decodeBinding(v))
        .filter((b): b is PipelineBinding => Boolean(b))
      bindings[portId] = list
    } else {
      const decoded = decodeBinding(typeof value === 'string' ? value : '')
      if (!decoded) delete bindings[portId]
      else bindings[portId] = decoded
    }
    onPatch({ bindings })
  }
  return (
    <div className="pipe-step__ports">
      {ins.map((port) => {
        const options = bindingOptions({
          neededTypes: port.types || [],
          slots,
          upstream,
          operators,
          typeProvides,
        })
        const bind = node.bindings?.[port.id] ?? step.bindings?.[port.id]
        const multiple = Boolean(port.multiple)
        const bindList = asBindingList(bind)
        return (
          <div key={port.id} style={{ marginBottom: 8, width: '100%' }}>
            <div className="pipe-step__chips" style={{ marginBottom: 6 }}>
              {(port.types || []).map((t) => (
                <span key={t} className="pipe-chip">{typeLabel(t)}</span>
              ))}
            </div>
            <div data-testid={`pipe-bind-${step.op_id}-${port.id}`}>
              <Select
                allowClear
                mode={multiple ? 'multiple' : undefined}
                placeholder={
                  options.length
                    ? multiple
                      ? '可多选：数据源或上游产出'
                      : '绑定数据源或上游产出'
                    : '无兼容输入'
                }
                style={{ width: '100%' }}
                value={
                  multiple
                    ? bindList.map(encodeBinding)
                    : bindList[0]
                      ? encodeBinding(bindList[0])
                      : undefined
                }
                options={options.map((o) => ({ value: o.value, label: o.label }))}
                onChange={(v: string | string[] | null) => setBinding(port.id, v, multiple)}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function OpParamFields({
  node,
  step,
  operators,
  onPatch,
}: {
  node: RecipeGraphNode
  step: PipelineStep
  operators: PlatformOperator[]
  onPatch: (patch: Partial<RecipeGraphNode>) => void
}) {
  const op = getOp(operators, step.op_id)
  const isStage = node.type === 'label' || (step.role || op?.role) === 'stage'
  const params = node.params || {}
  const setParam = (key: string, value: unknown) => onPatch({ params: { ...params, [key]: value } })
  return (
    <div className="pipe-step__params">
      {step.op_id === 'parse_bag' ? (
        <div className="pipe-step__field" data-testid="pipe-parse-modalities" style={{ minWidth: 220 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析产出</Typography.Text>
          <Select
            mode="multiple"
            allowClear
            placeholder="连续帧 / .wav / .json"
            style={{ width: '100%' }}
            value={Array.isArray(params.emit_modalities) ? params.emit_modalities.map(String) : [...PARSE_BAG_MODALITIES]}
            options={[
              { value: 'frames', label: '连续帧' },
              { value: '.wav', label: '.wav' },
              { value: '.json', label: '.json' },
            ]}
            onChange={(v: string[]) => {
              const mods = (v || []).filter((m) => (PARSE_BAG_MODALITIES as readonly string[]).includes(m))
              onPatch({
                params: { ...params, emit_modalities: mods },
              })
            }}
          />
        </div>
      ) : null}
      {step.op_id === 'label' ? (
        <div className="pipe-step__field" data-testid="pipe-label-model">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>打标模型</Typography.Text>
          <Select
            style={{ width: '100%' }}
            value={String(params.model || 'default')}
            options={LABEL_MODELS}
            onChange={(v) => setParam('model', v)}
          />
        </div>
      ) : null}
      {step.op_id === 'detect_bbox' ? (
        <>
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>检测器</Typography.Text>
            <Select
              style={{ width: '100%' }}
              value={String(params.detector || 'opencv')}
              options={[
                { value: 'opencv', label: 'opencv' },
                { value: 'yolo', label: 'yolo' },
              ]}
              onChange={(v) => setParam('detector', v)}
            />
          </div>
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>YOLO 类别</Typography.Text>
            <Input
              placeholder="留空=全部"
              value={String(params.yolo_classes || '')}
              onChange={(e) => setParam('yolo_classes', e.target.value)}
            />
          </div>
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>写入 bbox 开跑开关</Typography.Text>
            <Switch
              checked={params.bbox_enabled !== false}
              onChange={(v) => setParam('bbox_enabled', v)}
            />
          </div>
        </>
      ) : null}
      {step.op_id === 'extract_frames' ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>抽帧 fps</Typography.Text>
          <InputNumber
            min={0.1}
            max={30}
            step={0.5}
            style={{ width: '100%' }}
            value={typeof params.sample_fps === 'number' ? params.sample_fps : undefined}
            onChange={(v) => setParam('sample_fps', v)}
          />
        </div>
      ) : null}
      {step.op_id === 'transcribe' ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>ASR 模型</Typography.Text>
          <Input
            placeholder="可选"
            value={String(params.model || '')}
            onChange={(e) => setParam('model', e.target.value)}
          />
        </div>
      ) : null}
      {step.op_id === 'text_to_json' ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>schema_id</Typography.Text>
          <Input
            placeholder="generic_json"
            value={String(params.schema_id || '')}
            onChange={(e) => setParam('schema_id', e.target.value)}
          />
        </div>
      ) : null}
      {!isStage ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>必跑</Typography.Text>
          <Switch checked={Boolean(params.required)} onChange={(v) => setParam('required', v)} />
        </div>
      ) : null}
    </div>
  )
}

export function DagNodeInspector({
  graph,
  selectedKey,
  onChange,
  operators,
  typeProvides,
  sourceKinds,
  disabled,
  onClose,
}: Props) {
  const node = graph.nodes.find((n) => n.key === selectedKey) ?? null
  const steps = graphToSteps(graph)
  const step = node ? steps.find((s) => s.key === node.key) : undefined
  const kindOptions = sourceKindOptions(sourceKinds)
  const typeTitle: Record<string, string> = {
    source: '数据源',
    op: '算子',
    if: '条件',
    label: '打标器',
    review: '校核',
    export: '导出',
  }

  const applyPatch = (patch: Partial<RecipeGraphNode>) => {
    if (!node) return
    onChange(patchNode(graph, node.key, patch))
  }
  const exportProductOpts = node?.type === 'export' ? upstreamProductOptions(graph, node.key, operators) : []

  if (!node) return null

  return (
    <div
      className="dag-inspector nowheel nopan nodrag"
      data-testid="dag-inspector"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="dag-inspector__head">
        <div>
          <Typography.Text strong>{node.title || node.key}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
            {typeTitle[node.type] || node.type}
            {node.op_id ? ` · ${node.op_id}` : ''}
          </Typography.Text>
        </div>
        <Space size={4}>
          {node.type !== 'label' ? (
            <Button
              size="small"
              danger
              htmlType="button"
              data-testid={`dag-inspector-remove-${node.key}`}
              onClick={() => {
                onChange({
                  nodes: graph.nodes.filter((n) => n.key !== node.key),
                  edges: graph.edges.filter((e) => e.source !== node.key && e.target !== node.key),
                })
                onClose?.()
              }}
            >
              删除节点
            </Button>
          ) : null}
          <Button
            size="small"
            type="text"
            htmlType="button"
            aria-label="关闭"
            data-testid="dag-inspector-close"
            icon={<CloseOutlined />}
            onClick={() => onClose?.()}
          />
        </Space>
      </div>
      {node.type === 'if' ? (
        <IfConditionForm
          key={node.key}
          node={node}
          disabled={disabled}
          onChange={(all) => applyPatch({ condition: { all } })}
        />
      ) : null}
      {node.type === 'source' ? (
        <SourceFields node={node} kindOptions={kindOptions} onPatch={applyPatch} />
      ) : null}
      {node.type === 'op' || node.type === 'label' ? (
        <>
          {step ? (
            <OpBindFields
              node={node}
              step={step}
              steps={steps}
              operators={operators}
              typeProvides={typeProvides}
              onPatch={applyPatch}
            />
          ) : null}
          {step ? (
            <OpParamFields node={node} step={step} operators={operators} onPatch={applyPatch} />
          ) : null}
        </>
      ) : null}
      {node.type === 'review' ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>名称</Typography.Text>
          <Input value={node.title || ''} onChange={(e) => applyPatch({ title: e.target.value })} />
        </div>
      ) : null}
      {node.type === 'export' ? (
        <>
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>名称</Typography.Text>
            <Input value={node.title || ''} onChange={(e) => applyPatch({ title: e.target.value })} />
          </div>
          <div className="pipe-step__field" data-testid="dag-export-products">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>上游产物</Typography.Text>
            <Select
              mode="multiple"
              allowClear
              placeholder={exportProductOpts.length ? '选择要登记的上游产物' : '先添加算子或连到上游'}
              style={{ width: '100%' }}
              value={(Array.isArray(node.params?.exported_product_ids)
                ? node.params.exported_product_ids
                : []
              ).map(String)}
              options={exportProductOpts}
              onChange={(v: string[]) =>
                applyPatch({
                  params: { ...(node.params || {}), exported_product_ids: v },
                })
              }
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
