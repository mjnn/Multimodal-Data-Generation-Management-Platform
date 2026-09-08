import { CloseOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { AutoComplete, Button, Form, Input, InputNumber, Select, Space, Switch, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { GraphConditionPred, LabelCallField, PipelineBinding, PipelinePortBindings, PipelineStep, PlatformOperator, RecipeGraph, RecipeGraphNode } from '../../api/types'
import { PARSE_BAG_MODALITIES, sourceKindOptions } from '../../utils/fileKinds'
import {
  asBindingList,
  bindingDisplayLabel,
  bindingOptions,
  channelCountFromParams,
  decodeBinding,
  encodeBinding,
  expandOutputPorts,
  getOp,
  inputPorts,
  slotsFromSteps,
  typeLabel,
  displayNodeTitle,
} from '../../utils/recipePipeline'
import { graphToSteps, dropBindingsToRemoved, upstreamProductOptions } from '../../utils/recipeGraph'
import { JsonExtractFields } from './JsonExtractFields'
import { LabelTreeInputFields } from './LabelTreeInputFields'
import './PipelineOrchestrator.css'
import './DagNodeInspector.css'

const FIELD_PRESETS = [
  { value: 'source.kind', label: 'source.kind' },
  { value: 'source.slot_id', label: 'source.slot_id' },
  { value: 'asr.avg_confidence', label: 'asr.avg_confidence' },
  { value: 'asr.has_text', label: 'asr.has_text' },
  { value: 'json_extract.value', label: 'json_extract.value（提取值）' },
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

const FALLBACK_LABEL_MODELS = [
  { value: 'default', label: 'default（SDK Omni / Qwen）' },
  { value: 'nvh_sem_ast', label: 'nvh_sem_ast（AudioSet AST）' },
  { value: 'nvh_sem_heuristic', label: 'nvh_sem_heuristic（客观规则）' },
  { value: 'nvh_sem_vl', label: 'nvh_sem_vl（看 Mel 的 VL）' },
]

const FALLBACK_OMNI_PROMPT_FIELDS = [
  { key: 'system_role', label: '角色设定', multiline: false },
  { key: 'output_instruction', label: '输出要求', multiline: false },
  { key: 'json_format_hint', label: 'JSON 结构示例', multiline: true },
  { key: 'labeling_rules', label: '打标规则 / 参考约束', multiline: true },
  { key: 'labels_section_title', label: '标签列表标题', multiline: false },
  { key: 'user_task_intro', label: '用户任务开场', multiline: false },
  { key: 'user_modality_hint', label: '模态说明', multiline: false },
  { key: 'user_taxonomy_task', label: '打标任务句', multiline: false },
  { key: 'user_asr_hint', label: 'ASR 使用说明', multiline: false },
  { key: 'user_bbox_hint', label: 'BBox 使用说明', multiline: false },
]

const FALLBACK_CALL_FIELDS_BY_MODEL: Record<string, LabelCallField[]> = {
  default: [
    { key: 'omni_model_id', label: '调用模型 ID', type: 'string', placeholder: 'qwen3.5-omni-plus' },
    { key: 'temperature', label: '温度', type: 'number', min: 0, max: 2, step: 0.1 },
    { key: 'max_tokens', label: 'max_tokens', type: 'integer', min: 256, max: 16384 },
    { key: 'bbox_in_label_prompt', label: '把 BBox 写入提示词', type: 'boolean' },
    { key: 'omni_label_prompt', label: 'Omni 提示词', type: 'omni_prompt' },
  ],
  nvh_sem_ast: [
    { key: 'ast_top_k', label: 'AudioSet top-k', type: 'integer', min: 1, max: 20 },
    { key: 'reference_constraints', label: '参考约束', type: 'textarea' },
  ],
  nvh_sem_heuristic: [
    { key: 'reference_constraints', label: '参考约束 / 规则备注', type: 'textarea' },
  ],
  nvh_sem_vl: [
    { key: 'vl_model', label: 'VL 模型 ID', type: 'string', placeholder: 'qwen-vl-plus' },
    { key: 'vl_prompt', label: '提示词', type: 'textarea' },
    { key: 'reference_constraints', label: '参考约束', type: 'textarea' },
  ],
}

const popupToBody = () => document.body

function labelModelOptions(operators: PlatformOperator[]) {
  const models = getOp(operators, 'label')?.models
  if (models?.length) return models.map((m) => ({ value: m.id, label: m.title }))
  return FALLBACK_LABEL_MODELS
}

export function LabelModelParamFields({
  params,
  operators,
  omniPromptDefaults,
  onSetParam,
}: {
  params: Record<string, unknown>
  operators: PlatformOperator[]
  omniPromptDefaults?: Record<string, string>
  onSetParam: (key: string, value: unknown) => void
}) {
  const model = String(params.model || 'default')
  const labelOp = getOp(operators, 'label')
  const fields: LabelCallField[] =
    labelOp?.call_fields_by_model?.[model] ||
    FALLBACK_CALL_FIELDS_BY_MODEL[model] ||
    FALLBACK_CALL_FIELDS_BY_MODEL.default
  const omniFields = labelOp?.omni_prompt_fields?.length
    ? labelOp.omni_prompt_fields
    : FALLBACK_OMNI_PROMPT_FIELDS
  const promptObj =
    params.omni_label_prompt && typeof params.omni_label_prompt === 'object' && !Array.isArray(params.omni_label_prompt)
      ? (params.omni_label_prompt as Record<string, unknown>)
      : {}

  const setOmniPromptKey = (key: string, value: string) => {
    onSetParam('omni_label_prompt', { ...promptObj, [key]: value })
  }

  const renderField = (field: LabelCallField) => {
    const key = field.key
    const raw = params[key]
    const testId = `pipe-label-call-${key}`
    if (field.type === 'omni_prompt') {
      return (
        <div key={key} className="dag-inspector__call" data-testid={testId}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {field.label}
          </Typography.Text>
          {omniFields.map((f) => {
            const multiline = Boolean(f.multiline)
            const stored = promptObj[f.key]
            const value = typeof stored === 'string' ? stored : ''
            const placeholder = omniPromptDefaults?.[f.key] || ''
            return (
              <div key={f.key} className="pipe-step__field" data-testid={`pipe-label-omni-${f.key}`} style={{ width: '100%' }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }} title={'description' in f ? f.description : undefined}>
                  {f.label}
                </Typography.Text>
                {multiline ? (
                  <Input.TextArea
                    rows={2}
                    placeholder={placeholder}
                    value={value}
                    onChange={(e) => setOmniPromptKey(f.key, e.target.value)}
                  />
                ) : (
                  <Input
                    placeholder={placeholder}
                    value={value}
                    onChange={(e) => setOmniPromptKey(f.key, e.target.value)}
                  />
                )}
              </div>
            )
          })}
        </div>
      )
    }
    if (field.type === 'boolean') {
      const checked = typeof raw === 'boolean' ? raw : true
      return (
        <div key={key} className="pipe-step__field" data-testid={testId} style={{ width: '100%' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }} title={field.description}>
            {field.label}
          </Typography.Text>
          <Switch checked={checked} onChange={(v) => onSetParam(key, v)} />
        </div>
      )
    }
    if (field.type === 'integer' || field.type === 'number') {
      const num = typeof raw === 'number' ? raw : raw == null || raw === '' ? undefined : Number(raw)
      return (
        <div key={key} className="pipe-step__field" data-testid={testId} style={{ width: '100%' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} title={field.description}>
            {field.label}
          </Typography.Text>
          <InputNumber
            style={{ width: '100%' }}
            min={field.min}
            max={field.max}
            step={field.step ?? (field.type === 'integer' ? 1 : 0.1)}
            value={Number.isFinite(num as number) ? (num as number) : undefined}
            onChange={(v) => onSetParam(key, v)}
          />
        </div>
      )
    }
    if (field.type === 'textarea') {
      return (
        <div key={key} className="pipe-step__field" data-testid={testId} style={{ width: '100%' }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} title={field.description}>
            {field.label}
          </Typography.Text>
          <Input.TextArea
            rows={2}
            placeholder={field.placeholder || ''}
            value={typeof raw === 'string' ? raw : ''}
            onChange={(e) => onSetParam(key, e.target.value)}
          />
        </div>
      )
    }
    return (
      <div key={key} className="pipe-step__field" data-testid={testId} style={{ width: '100%' }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }} title={field.description}>
          {field.label}
        </Typography.Text>
        <Input
          placeholder={field.placeholder || ''}
          value={typeof raw === 'string' ? raw : raw == null ? '' : String(raw)}
          onChange={(e) => onSetParam(key, e.target.value)}
        />
      </div>
    )
  }

  return (
    <>
      <div className="pipe-step__field" data-testid="pipe-label-model" style={{ width: '100%' }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>打标模型</Typography.Text>
        <Select
          style={{ width: '100%' }}
          value={model}
          options={labelModelOptions(operators)}
          getPopupContainer={popupToBody}
          onChange={(v) => onSetParam('model', v)}
        />
      </div>
      {fields.map(renderField)}
    </>
  )
}

const NO_VALUE_OPS = new Set(['exists', 'not_exists'])

type Props = {
  graph: RecipeGraph
  selectedKey: string | null
  onChange: (next: RecipeGraph) => void
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  sourceKinds?: string[]
  taxonomyId?: string
  dataTypeId?: string
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
  graph,
  disabled,
  onChange,
}: {
  node: RecipeGraphNode
  graph?: RecipeGraph
  disabled?: boolean
  onChange: (all: GraphConditionPred[]) => void
}) {
  const extractPresets = (graph?.nodes || [])
    .filter((n) => n.op_id === 'json_extract')
    .map((n) => ({
      value: `${n.key}.value`,
      label: `${n.title || 'JSON 值提取'} · 提取值`,
    }))
  const fieldOptions = [...FIELD_PRESETS, ...extractPresets]
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
                    options={fieldOptions}
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
      <div className="pipe-step__field" style={{ minWidth: 200, flex: 1 }} data-testid="dag-source-kinds">
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
        const optionValues = new Set(options.map((o) => o.value))
        const multiple = Boolean(port.multiple)
        const bindList = asBindingList(node.bindings?.[port.id]).filter((b) => optionValues.has(encodeBinding(b)))
        const selected = bindList.map(encodeBinding)
        const chipLabel = (value: unknown) => bindingDisplayLabel(String(value ?? ''), options, steps, operators)
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
                showSearch
                optionFilterProp="label"
                mode={multiple ? 'multiple' : undefined}
                placeholder={
                  options.length
                    ? multiple
                      ? '可多选：数据源或上游产出'
                      : '绑定数据源或上游产出'
                    : '无兼容输入'
                }
                style={{ width: '100%' }}
                getPopupContainer={popupToBody}
                optionLabelProp="label"
                labelRender={(item) => chipLabel(item.value)}
                tagRender={(props) => (
                  <Tag
                    closable={props.closable}
                    onClose={props.onClose}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                    }}
                    style={{ marginInlineEnd: 4 }}
                  >
                    {chipLabel(props.value)}
                  </Tag>
                )}
                value={multiple ? selected : selected[0]}
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
  steps,
  typeProvides,
  taxonomyId,
  omniPromptDefaults,
  onPatch,
}: {
  node: RecipeGraphNode
  step: PipelineStep
  operators: PlatformOperator[]
  steps?: PipelineStep[]
  typeProvides?: Record<string, string[]>
  taxonomyId?: string
  omniPromptDefaults?: Record<string, string>
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
                params: { ...params, emit_modalities: mods, produces: mods },
              })
            }}
            />
        </div>
      ) : null}
      {op?.expand_outputs_from === 'channel_count' ? (
        <>
          <div className="pipe-step__field" data-testid="node-channel-count" style={{ minWidth: 160 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>通道数</Typography.Text>
            <InputNumber
              min={1}
              max={16}
              style={{ width: '100%', marginTop: 4 }}
              value={channelCountFromParams(params)}
              onChange={(v) => setParam('channel_count', Number(v ?? 1))}
            />
          </div>
          {Array.from({ length: channelCountFromParams(params) }, (_, i) => {
            const pid = `ch${i + 1}`
            const titles =
              params.port_titles && typeof params.port_titles === 'object' && !Array.isArray(params.port_titles)
                ? (params.port_titles as Record<string, unknown>)
                : {}
            return (
              <div key={pid} className="pipe-step__field">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>端口 {pid} 名称</Typography.Text>
                <Input
                  data-testid={`node-port-title-${pid}`}
                  placeholder={pid}
                  value={String(titles[pid] ?? '')}
                  onChange={(e) => setParam('port_titles', { ...titles, [pid]: e.target.value })}
                />
              </div>
            )
          })}
        </>
      ) : null}
      {step.op_id === 'label' ? (
        <LabelModelParamFields
          params={params}
          operators={operators}
          omniPromptDefaults={omniPromptDefaults}
          onSetParam={setParam}
        />
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
      {step.op_id === 'json_extract' ? <JsonExtractFields node={node} onPatch={onPatch} /> : null}
      {step.op_id === 'label_tree_input' ? (
        <LabelTreeInputFields
          node={node}
          step={step}
          steps={steps || []}
          operators={operators}
          typeProvides={typeProvides || {}}
          taxonomyId={taxonomyId}
          onPatch={onPatch}
        />
      ) : null}
      {!isStage ? (
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>必跑</Typography.Text>
          <Switch checked={Boolean(params.required)} onChange={(v) => setParam('required', v)} />
        </div>
      ) : null}
      <div className="pipe-step__field" data-testid="dag-expected-outputs">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>期望输出</Typography.Text>
        {(() => {
          const allowed = expandOutputPorts(op, params).flatMap((p) => {
            const types = (p.types || []).filter(Boolean)
            return types.length ? types : p.id ? [p.id] : []
          })
          const uniq = [...new Set(allowed)]
          const current = (
            step.op_id === 'parse_bag' && Array.isArray(params.emit_modalities)
              ? params.emit_modalities.map(String)
              : Array.isArray(params.produces)
                ? (params.produces as string[]).map(String)
                : step.produces && step.produces.length
                  ? step.produces
                  : uniq
          ).filter((x) => uniq.includes(x) || !uniq.length)
          if (uniq.length <= 1) {
            return (
              <Typography.Text style={{ display: 'block', fontSize: 12 }}>
                {current.join(' / ') || uniq.join(' / ') || '—'}
              </Typography.Text>
            )
          }
          return (
            <Select
              mode="multiple"
              allowClear
              style={{ width: '100%', marginTop: 4 }}
              value={current.length ? current : uniq}
              options={uniq.map((id) => ({ value: id, label: id }))}
              onChange={(v: string[]) => {
                const next = (v || []).filter((x) => uniq.includes(x))
                const patchParams: Record<string, unknown> = { ...params, produces: next }
                if (step.op_id === 'parse_bag') patchParams.emit_modalities = next
                onPatch({ params: patchParams })
              }}
            />
          )
        })()}
      </div>
    </div>
  )
}

function NodeProbePanel({
  graph,
  nodeKey,
  dataTypeId,
  disabled,
}: {
  graph: RecipeGraph
  nodeKey: string
  dataTypeId?: string
  disabled?: boolean
}) {
  const [sourceId, setSourceId] = useState<string | undefined>()
  const [sources, setSources] = useState<Array<{ value: string; label: string }>>([])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState('')
  useEffect(() => {
    let live = true
    void api
      .listPlatformSources(80, dataTypeId ? { eligibleFor: dataTypeId } : undefined)
      .then((res) => {
        if (!live) return
        setSources(
          (res.items || []).map((s) => ({
            value: s.source_id,
            label: `${s.filename || s.source_id} (${s.kind})`,
          })),
        )
      })
      .catch(() => {
        if (live) setSources([])
      })
    return () => {
      live = false
    }
  }, [dataTypeId])
  const run = async (includeAi: boolean) => {
    setBusy(true)
    setResult('')
    try {
      const out = await api.probePlatformGraph({
        until_key: nodeKey,
        graph,
        data_type_id: dataTypeId,
        include_ai: includeAi,
        source_ids: sourceId ? [sourceId] : [],
      })
      const bits = [
        out.ok ? '通过' : '未通过',
        out.error || '',
        out.produces_expected?.length ? `期望 ${out.produces_expected.join(',')}` : '',
        out.produces_found?.length ? `实际 ${out.produces_found.join(',')}` : '',
        out.missing?.length ? `缺少 ${out.missing.join(',')}` : '',
      ].filter(Boolean)
      setResult(bits.join(' · '))
    } catch (err) {
      const ax = err as { response?: { data?: { error?: string; detail?: unknown } } }
      const detail = ax.response?.data?.detail
      const fromDetail =
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object' && 'message' in detail
            ? String((detail as { message?: string }).message || '')
            : ''
      setResult(ax.response?.data?.error || fromDetail || (err instanceof Error ? err.message : String(err)))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="pipe-step__field" data-testid="dag-node-probe" style={{ marginTop: 12 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>节点试跑</Typography.Text>
      <Select
        allowClear
        placeholder="选择源湖数据"
        style={{ width: '100%', marginTop: 4 }}
        value={sourceId}
        options={sources}
        onChange={(v: string) => setSourceId(v)}
        disabled={disabled || busy}
        data-testid="dag-probe-source"
      />
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
        无法凭空单跑，会先执行上游再跑本节点。
      </Typography.Text>
      <Space size={8} style={{ marginTop: 8 }}>
        <Button
          size="small"
          htmlType="button"
          disabled={disabled || busy}
          data-testid="dag-probe-until"
          onClick={() => void run(false)}
        >
          运行到此节点
        </Button>
        <Button
          size="small"
          htmlType="button"
          disabled={disabled || busy}
          data-testid="dag-probe-single"
          onClick={() => void run(false)}
        >
          仅运行此节点
        </Button>
        <Button
          size="small"
          htmlType="button"
          disabled={disabled || busy}
          data-testid="dag-probe-ai"
          onClick={() => void run(true)}
        >
          含 AI 真跑
        </Button>
      </Space>
      {result ? (
        <Typography.Text data-testid="dag-probe-result" style={{ display: 'block', fontSize: 12, marginTop: 8 }}>
          {result}
        </Typography.Text>
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
  taxonomyId,
  dataTypeId,
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
    label: 'AI打标器',
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
          <Typography.Text strong>{displayNodeTitle(node, operators)}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
            {typeTitle[node.type] || node.type}
            {node.op_id ? ` · ${node.op_id}` : ''}
          </Typography.Text>
        </div>
        <Space size={4}>
          <Button
            size="small"
            danger
            htmlType="button"
            data-testid={`dag-inspector-remove-${node.key}`}
            onClick={() => {
              const removed = new Set([node.key])
              onChange({
                nodes: dropBindingsToRemoved(graph, removed),
                edges: graph.edges.filter((e) => e.source !== node.key && e.target !== node.key),
              })
              onClose?.()
            }}
          >
            删除节点
          </Button>
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
          graph={graph}
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
            <OpParamFields
              node={node}
              step={step}
              operators={operators}
              steps={steps}
              typeProvides={typeProvides}
              taxonomyId={taxonomyId}
              onPatch={applyPatch}
            />
          ) : null}
        </>
      ) : null}
      {node.type === 'op' || node.type === 'label' ? (
        <NodeProbePanel graph={graph} nodeKey={node.key} dataTypeId={dataTypeId} disabled={disabled} />
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
