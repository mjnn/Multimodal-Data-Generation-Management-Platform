import { ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined } from '@ant-design/icons'
import { Button, Input, InputNumber, Select, Space, Switch, Typography } from 'antd'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { DataTypeSlot, PipelineBinding, PipelinePortBindings, PipelineStep, PlatformOperator } from '../../api/types'
import {
  PARSE_BAG_MODALITIES,
  asBindingList,
  bindingOptions,
  decodeBinding,
  effectiveProduces,
  encodeBinding,
  getOp,
  inputPorts,
  stripOutputLabels,
  typeLabel,
} from '../../utils/recipePipeline'
import { PipelineCardShell } from './PipelineCardShell'

const DOT: Record<string, string> = {
  '.bag': '#5e6ad2',
  '.mp4': '#27a644',
  '.webm': '#27a644',
  '.mov': '#27a644',
  '.mkv': '#27a644',
  '.avi': '#27a644',
  '.jpg': '#27a644',
  '.jpeg': '#27a644',
  '.png': '#27a644',
  '.webp': '#27a644',
  '.bmp': '#27a644',
  '.wav': '#d97706',
  '.mp3': '#d97706',
  '.m4a': '#d97706',
  '.flac': '#d97706',
  '.ogg': '#d97706',
  '.aac': '#d97706',
  '.dat': '#d97706',
  '.txt': '#8a8f98',
  '.json': '#8a8f98',
  '.md': '#8a8f98',
  '.csv': '#8a8f98',
  frames: '#27a644',
  labelable: '#828fff',
}

function dotColor(t: string): string {
  if (DOT[t]) return DOT[t]
  if (t.includes('audio') || t.includes('mel') || t.includes('stft') || t.includes('spl') || t.includes('pcm')) {
    return '#d97706'
  }
  if (t.includes('label') || t.includes('embed') || t.includes('bbox')) return '#828fff'
  return '#5e6ad2'
}

const LABEL_MODELS = [
  { value: 'default', label: 'default（SDK Omni）' },
  { value: 'nvh_sem_ast', label: 'nvh_sem_ast' },
  { value: 'nvh_sem_heuristic', label: 'nvh_sem_heuristic' },
]

type Props = {
  step: PipelineStep
  index: number
  total: number
  /** Real array index for move disable; defaults to `index`. */
  listIndex?: number
  listTotal?: number
  pinnedLast?: boolean
  canMoveUp?: boolean
  canMoveDown?: boolean
  slots: DataTypeSlot[]
  upstream: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  onChange: (next: PipelineStep) => void
  onMove: (delta: number) => void
  onRemove: () => void
  dragging?: boolean
  dragOver?: boolean
  onHandlePointerDown?: (e: ReactPointerEvent<HTMLButtonElement>) => void
}

export function PipelineStepCard({
  step,
  index,
  total,
  listIndex,
  listTotal,
  pinnedLast,
  canMoveUp,
  canMoveDown,
  slots,
  upstream,
  operators,
  typeProvides,
  onChange,
  onMove,
  onRemove,
  dragging,
  dragOver,
  onHandlePointerDown,
}: Props) {
  const op = getOp(operators, step.op_id)
  const ins = inputPorts(op)
  const outTypes = effectiveProduces(step, op)
  const title = op?.title || step.op_id
  const isStage = (step.role || op?.role) === 'stage'
  const moveIndex = listIndex ?? index
  const moveTotal = listTotal ?? total
  const moveUp = canMoveUp ?? moveIndex > 0
  const moveDown = canMoveDown ?? moveIndex < moveTotal - 1

  const setOutputLabel = (typeName: string, label: string) => {
    const labels = { ...(step.output_labels || {}) }
    if (label.trim()) labels[typeName] = label
    else delete labels[typeName]
    onChange({ ...step, output_labels: labels })
  }

  const setBinding = (portId: string, value: string | string[] | null, multiple: boolean) => {
    const bindings: Record<string, PipelinePortBindings> = { ...(step.bindings || {}) }
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
    const next: PipelineStep = { ...step, bindings }
    const first = asBindingList(bindings[portId])[0]
    if (first?.kind === 'slot') {
      const slot = slots.find((s) => s.id === first.slot_id)
      const kinds = (slot?.kinds || []).filter(Boolean)
      next.when_kind = kinds.length === 1 ? kinds[0] : null
    }
    onChange(next)
  }

  const setParam = (key: string, value: unknown) => {
    onChange({ ...step, params: { ...(step.params || {}), [key]: value } })
  }

  return (
    <PipelineCardShell
      testId={`pipe-step-${step.op_id}`}
      title={`${index + 1}. ${title}`}
      subtitle={`${step.op_id}${pinnedLast ? ' · 固定最后 · 输出标签树' : isStage ? ' · AI 阶段' : ''}`}
      dragging={dragging}
      dragOver={dragOver}
      onHandlePointerDown={pinnedLast ? undefined : onHandlePointerDown}
      summary={
        outTypes.length ? (
          <span className="pipe-step__chips">
            {outTypes.map((t) => (
              <span key={t} className="pipe-chip">
                <span className="pipe-chip__dot" style={{ background: dotColor(t) }} />
                {step.output_labels?.[t] || typeLabel(t)}
              </span>
            ))}
          </span>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>折叠</Typography.Text>
        )
      }
      extra={
        pinnedLast ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            固定最后
          </Typography.Text>
        ) : (
        <Space>
          <Button size="small" icon={<ArrowUpOutlined />} disabled={!moveUp} onClick={() => onMove(-1)} />
          <Button size="small" icon={<ArrowDownOutlined />} disabled={!moveDown} onClick={() => onMove(1)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={onRemove} data-testid={`pipe-remove-${step.op_id}`} />
        </Space>
        )
      }
    >

      <div className="pipe-step__ports">
        <div className="pipe-step__port-col">
          <div className="pipe-step__port-kicker">输入</div>
          {ins.map((port) => {
            const options = bindingOptions({
              neededTypes: port.types || [],
              slots,
              upstream,
              operators,
              typeProvides,
            })
            const bind = step.bindings?.[port.id]
            const multiple = Boolean(port.multiple)
            const bindList = asBindingList(bind)
            return (
              <div key={port.id} style={{ marginBottom: 8 }}>
                <div className="pipe-step__chips" style={{ marginBottom: 6 }}>
                  {(port.types || []).map((t) => (
                    <span key={t} className="pipe-chip">
                      <span className="pipe-chip__dot" style={{ background: dotColor(t) }} />
                      {typeLabel(t)}
                    </span>
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
                  style={{ width: '100%', maxWidth: 360 }}
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
        <div className="pipe-step__port-col">
          <div className="pipe-step__port-kicker">产出</div>
          {outTypes.length ? (
            <div className="pipe-step__chips">
              {outTypes.map((t) => (
                <span key={t} className="pipe-out">
                  <span className="pipe-chip">
                    <span className="pipe-chip__dot" style={{ background: dotColor(t) }} />
                    {step.output_labels?.[t] || typeLabel(t)}
                  </span>
                  <Input
                    size="small"
                    placeholder="显示名"
                    value={step.output_labels?.[t] || ''}
                    onChange={(e) => setOutputLabel(t, e.target.value)}
                    className="pipe-out__label"
                  />
                </span>
              ))}
            </div>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>未选择产物</Typography.Text>
          )}
        </div>
      </div>

      <div className="pipe-step__params">
        {step.op_id === 'parse_bag' ? (
          <div className="pipe-step__field" data-testid="pipe-parse-modalities" style={{ minWidth: 280 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>解析产出</Typography.Text>
            <Select
              mode="multiple"
              allowClear
              placeholder="连续帧 / .wav / .json"
              style={{ width: 280, display: 'block' }}
              value={outTypes}
              options={[
                { value: 'frames', label: '连续帧' },
                { value: '.wav', label: '.wav' },
                { value: '.json', label: '.json' },
              ]}
              onChange={(v: string[]) => {
                const mods = (v || [])
                  .map((m) => (PARSE_BAG_MODALITIES as readonly string[]).includes(m) ? m : '')
                  .filter(Boolean)
                onChange({
                  ...step,
                  params: { ...(step.params || {}), emit_modalities: mods },
                  produces: mods,
                  output_labels: stripOutputLabels(step.output_labels, mods),
                })
              }}
            />
          </div>
        ) : null}
        {step.op_id === 'label' ? (
            <div className="pipe-step__field" data-testid="pipe-label-model">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>打标模型</Typography.Text>
              <Select
                style={{ width: 220, display: 'block' }}
                value={String(step.params?.model || 'default')}
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
                style={{ width: 140, display: 'block' }}
                value={String(step.params?.detector || 'opencv')}
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
                value={String(step.params?.yolo_classes || '')}
                onChange={(e) => setParam('yolo_classes', e.target.value)}
              />
            </div>
            <div className="pipe-step__field">
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>写入 bbox 开跑开关</Typography.Text>
              <Switch
                checked={step.bbox_enabled !== false}
                onChange={(v) => onChange({ ...step, bbox_enabled: v })}
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
              style={{ width: 120, display: 'block' }}
              value={typeof step.params?.sample_fps === 'number' ? step.params.sample_fps : undefined}
              onChange={(v) => setParam('sample_fps', v)}
            />
          </div>
        ) : null}
        {step.op_id === 'transcribe' ? (
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>ASR 模型</Typography.Text>
            <Input
              placeholder="可选，本刀 worker 不读"
              value={String(step.params?.model || '')}
              onChange={(e) => setParam('model', e.target.value)}
            />
          </div>
        ) : null}
        {step.op_id === 'text_to_json' ? (
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>schema_id</Typography.Text>
            <Input
              placeholder="generic_json"
              value={String(step.params?.schema_id || '')}
              onChange={(e) => setParam('schema_id', e.target.value)}
            />
          </div>
        ) : null}
        {!isStage ? (
          <div className="pipe-step__field">
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>必跑</Typography.Text>
            <Switch checked={Boolean(step.required)} onChange={(v) => onChange({ ...step, required: v })} />
          </div>
        ) : null}
      </div>
    </PipelineCardShell>
  )
}
