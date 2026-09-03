import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Input, InputNumber, Select, Space, Switch, Typography } from 'antd'
import type { PipelineStep } from '../../api/types'
import { PipelineCardShell } from './PipelineCardShell'

type KindOption = { value: string; label: string }

type SourceRow = {
  step: PipelineStep
  index: number
}

type Props = {
  sources: SourceRow[]
  kindOptions: KindOption[]
  onChangeRow: (index: number, next: PipelineStep) => void
  onRemoveRow: (index: number) => void
  onAdd: () => void
}

export function PipelineSourceCard({ sources, kindOptions, onChangeRow, onRemoveRow, onAdd }: Props) {
  const summaryKinds = sources.flatMap((row) => (row.step.kinds || []).filter(Boolean))

  return (
    <PipelineCardShell
      testId="pipe-source-card"
      variant="source"
      title="数据源"
      subtitle={sources.length ? `${sources.length} 路输入` : '还没有数据源'}
      summary={
        summaryKinds.length ? (
          <span className="pipe-step__chips">
            {summaryKinds.map((k, i) => (
              <span key={`${k}-${i}`} className="pipe-chip">{k}</span>
            ))}
          </span>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>未选 kinds</Typography.Text>
        )
      }
      extra={
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          htmlType="button"
          data-testid="pipe-add-source"
          onClick={onAdd}
        >
          添加数据源
        </Button>
      }
    >
      {sources.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>
          点右上角「添加数据源」在本卡内增加一路输入（名称、后缀、数量）。
        </Typography.Paragraph>
      ) : (
        <div className="pipe-source-rows">
          {sources.map((row) => (
            <SourceRowFields
              key={row.step.key}
              step={row.step}
              kindOptions={kindOptions}
              onChange={(next) => onChangeRow(row.index, next)}
              onRemove={() => onRemoveRow(row.index)}
            />
          ))}
        </div>
      )}
    </PipelineCardShell>
  )
}

function SourceRowFields({
  step,
  kindOptions,
  onChange,
  onRemove,
}: {
  step: PipelineStep
  kindOptions: KindOption[]
  onChange: (next: PipelineStep) => void
  onRemove: () => void
}) {
  const kinds = (step.kinds || []).filter(Boolean)

  const setKinds = (nextKinds: string[]) => {
    onChange({
      ...step,
      kinds: nextKinds,
      produces: [...nextKinds],
    })
  }

  return (
    <div className="pipe-source-row" data-testid="pipe-source-row">
      <div className="pipe-step__params">
        <div className="pipe-step__field" style={{ minWidth: 160 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>名称</Typography.Text>
          <Input
            value={step.title || ''}
            placeholder="数据源"
            onChange={(e) => onChange({ ...step, title: e.target.value })}
          />
        </div>
        <div className="pipe-step__field" style={{ minWidth: 220, flex: 1 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>允许 kinds</Typography.Text>
          <Select
            mode="multiple"
            allowClear
            placeholder="至少一种后缀"
            style={{ width: '100%', minWidth: 200, display: 'block' }}
            options={kindOptions}
            value={kinds}
            onChange={(v: string[]) => setKinds(v || [])}
          />
        </div>
        <div className="pipe-step__field" style={{ width: 88 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>最少</Typography.Text>
          <InputNumber
            min={0}
            max={64}
            style={{ width: '100%' }}
            value={step.cardinality_min ?? 1}
            onChange={(v) => onChange({ ...step, cardinality_min: Number(v ?? 1) })}
          />
        </div>
        <div className="pipe-step__field" style={{ width: 88 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>最多</Typography.Text>
          <InputNumber
            min={1}
            max={64}
            style={{ width: '100%' }}
            value={step.cardinality_max ?? 1}
            onChange={(v) => onChange({ ...step, cardinality_max: Number(v ?? 1) })}
          />
        </div>
        <div className="pipe-step__field">
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block' }}>必填</Typography.Text>
          <Space>
            <Switch
              checked={step.required !== false}
              onChange={(v) => onChange({ ...step, required: v })}
            />
            <Button size="small" danger icon={<DeleteOutlined />} onClick={onRemove} data-testid="pipe-remove-source" />
          </Space>
        </div>
      </div>
    </div>
  )
}
