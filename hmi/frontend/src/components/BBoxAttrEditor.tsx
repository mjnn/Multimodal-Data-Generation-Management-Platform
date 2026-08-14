import { Form, Input, InputNumber, Select, Space, Typography } from 'antd'
import type { EditableBox } from './BBoxOverlayLayer'

export function buildDisplayLabel(box: Pick<EditableBox, 'element' | 'gender' | 'age_approx' | 'age_range'>): string {
  const parts = [(box.element || '').trim() || 'element']
  if (box.gender) parts.push(String(box.gender).trim().toLowerCase())
  if (box.age_approx != null && Number.isFinite(box.age_approx)) {
    parts.push(`~${Math.round(box.age_approx)}y`)
  } else if (box.age_range) {
    parts.push(String(box.age_range).trim())
  }
  return parts.join('/')
}

type Props = {
  box: EditableBox | null
  camera?: string | null
  frameTs?: number | null
  disabled?: boolean
  onChange: (patch: Partial<EditableBox>) => void
}

const ELEMENT_OPTIONS = [
  { value: 'face', label: 'face（人脸）' },
  { value: 'person', label: 'person（人）' },
  { value: 'element', label: 'element（通用）' },
]

export function BBoxAttrEditor({ box, camera, frameTs, disabled, onChange }: Props) {
  if (!box) {
    return (
      <div className="bbox-attr-editor" data-testid="bbox-attr-editor-empty">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          在视频上点选一个框，或点「新建框」后拖拽绘制，即可编辑识别内容。
        </Typography.Text>
      </div>
    )
  }

  return (
    <div className="bbox-attr-editor" data-testid="bbox-attr-editor">
      <Space size={8} wrap style={{ marginBottom: 8 }}>
        <Typography.Text strong style={{ fontSize: 13 }}>
          识别内容
        </Typography.Text>
        {camera ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>{camera}</Typography.Text> : null}
        {frameTs != null ? (
          <Typography.Text type="secondary" code style={{ fontSize: 11 }}>
            ts={frameTs}
          </Typography.Text>
        ) : null}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          显示：{buildDisplayLabel(box)}
        </Typography.Text>
      </Space>
      <Form layout="inline" size="small" disabled={disabled} style={{ rowGap: 8 }}>
        <Form.Item label="元素">
          <Select
            style={{ width: 160 }}
            value={box.element || 'face'}
            options={ELEMENT_OPTIONS}
            showSearch
            allowClear={false}
            onChange={(v) => onChange({ element: v, display_label: buildDisplayLabel({ ...box, element: v }) })}
            data-testid="bbox-attr-element"
          />
        </Form.Item>
        <Form.Item label="自定义元素">
          <Input
            style={{ width: 120 }}
            placeholder="如 cell phone"
            value={
              ELEMENT_OPTIONS.some((o) => o.value === box.element) ? '' : box.element || ''
            }
            onChange={(e) => {
              const element = e.target.value.trim() || 'element'
              onChange({ element, display_label: buildDisplayLabel({ ...box, element }) })
            }}
            data-testid="bbox-attr-element-custom"
          />
        </Form.Item>
        <Form.Item label="性别">
          <Select
            style={{ width: 100 }}
            allowClear
            placeholder="—"
            value={box.gender ?? undefined}
            options={[
              { value: 'male', label: 'male' },
              { value: 'female', label: 'female' },
            ]}
            onChange={(v) =>
              onChange({
                gender: v ?? null,
                display_label: buildDisplayLabel({ ...box, gender: v ?? null }),
              })
            }
            data-testid="bbox-attr-gender"
          />
        </Form.Item>
        <Form.Item label="年龄约">
          <InputNumber
            style={{ width: 88 }}
            min={0}
            max={120}
            placeholder="岁"
            value={box.age_approx ?? undefined}
            onChange={(v) =>
              onChange({
                age_approx: typeof v === 'number' ? v : null,
                display_label: buildDisplayLabel({
                  ...box,
                  age_approx: typeof v === 'number' ? v : null,
                }),
              })
            }
            data-testid="bbox-attr-age"
          />
        </Form.Item>
        <Form.Item label="年龄段">
          <Input
            style={{ width: 100 }}
            placeholder="如 25-32"
            value={box.age_range ?? ''}
            onChange={(e) => {
              const age_range = e.target.value.trim() || null
              onChange({
                age_range,
                display_label: buildDisplayLabel({ ...box, age_range }),
              })
            }}
            data-testid="bbox-attr-age-range"
          />
        </Form.Item>
      </Form>
    </div>
  )
}
