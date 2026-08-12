import { UndoOutlined } from '@ant-design/icons'
import { Alert, Button, Checkbox, Modal, Space, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import type { BBoxYoloClassOption, BBoxYoloClassPreset } from '../../api/types'

type Props = {
  open: boolean
  catalog: BBoxYoloClassOption[]
  /** Optional presets from API; falls back to built-in cabin-oriented set. */
  presets?: BBoxYoloClassPreset[]
  /** Comma-separated class names (or ids) currently saved. */
  value: string
  onCancel: () => void
  onOk: (nextCsv: string) => void
}

/** Fallback when API has not yet returned presets (must match SDK COCO names). */
const FALLBACK_PRESETS: BBoxYoloClassPreset[] = [
  { id: 'person', label: '人物', mode: 'add', names: ['person'] },
  {
    id: 'vehicle',
    label: '车辆',
    mode: 'add',
    names: ['car', 'bus', 'truck', 'motorcycle', 'bicycle'],
  },
  {
    id: 'cabin_leftover',
    label: '舱内遗留物',
    mode: 'replace',
    names: [
      'backpack',
      'umbrella',
      'handbag',
      'suitcase',
      'bottle',
      'cup',
      'laptop',
      'mouse',
      'remote',
      'keyboard',
      'cell phone',
      'book',
    ],
    hint: '标准 YOLOv8n/COCO 无 face；人脸请改用检测器 OpenCV（Haar/YuNet）',
  },
]

function parseSelectedNames(raw: string, catalog: BBoxYoloClassOption[]): string[] {
  const byId = new Map(catalog.map((c) => [String(c.id), c.name]))
  const byName = new Set(catalog.map((c) => c.name.toLowerCase()))
  const out: string[] = []
  const seen = new Set<string>()
  for (const part of (raw || '').split(',')) {
    const token = part.trim()
    if (!token) continue
    let name = token
    if (/^\d+$/.test(token) && byId.has(token)) {
      name = byId.get(token)!
    } else if (!byName.has(token.toLowerCase())) {
      // Keep custom tokens as-is so non-COCO models can still be typed later.
      name = token
    } else {
      const hit = catalog.find((c) => c.name.toLowerCase() === token.toLowerCase())
      name = hit?.name ?? token
    }
    const key = name.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(name)
  }
  return out
}

function catalogNamesInOrder(names: string[], catalog: BBoxYoloClassOption[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const name of names) {
    const hit = catalog.find((c) => c.name.toLowerCase() === name.toLowerCase())
    if (!hit) continue
    const key = hit.name.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(hit.name)
  }
  return out
}

export function BBoxYoloClassesModal({ open, catalog, presets, value, onCancel, onOk }: Props) {
  const [selected, setSelected] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    setSelected(parseSelectedNames(value, catalog))
  }, [open, value, catalog])

  const options = useMemo(
    () =>
      catalog.map((c) => ({
        label: `${c.name} (id=${c.id})`,
        value: c.name,
      })),
    [catalog],
  )

  const effectivePresets = presets?.length ? presets : FALLBACK_PRESETS
  const cabinHint =
    effectivePresets.find((p) => p.id === 'cabin_leftover')?.hint ||
    '标准 YOLOv8n/COCO 无 face；人脸请改用检测器 OpenCV（Haar/YuNet）'

  function applyPreset(preset: BBoxYoloClassPreset) {
    const names = catalogNamesInOrder(preset.names, catalog)
    if (preset.mode === 'replace') {
      setSelected(names)
      return
    }
    const next = new Set(selected.map((s) => s.toLowerCase()))
    const merged = [...selected]
    for (const name of names) {
      if (next.has(name.toLowerCase())) continue
      next.add(name.toLowerCase())
      merged.push(name)
    }
    setSelected(merged)
  }

  return (
    <Modal
      title="YOLO 识别类别清单"
      open={open}
      onCancel={onCancel}
      onOk={() => onOk(selected.join(','))}
      width={720}
      destroyOnClose
      okText="应用"
      footer={
        <Space>
          <Button icon={<UndoOutlined />} onClick={() => setSelected([])}>
            清空（检测全部类别）
          </Button>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" onClick={() => onOk(selected.join(','))}>
            应用
          </Button>
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        勾选要保留的 YOLO 类别（默认 COCO-80 / yolov8n）。留空表示不过滤、保留模型输出的全部类别。
        应用到表单后，请再点「保存执行参数」写入配置。
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="舱内场景提示"
        description={
          <>
            <div>
              <strong>遗留物</strong>：点「舱内遗留物」一键设为手机/电脑/箱包等 COCO 类（会替换当前勾选）。
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>人脸</strong>：{cabinHint}
            </div>
            <div style={{ marginTop: 4, color: 'rgba(0,0,0,0.45)' }}>
              当前管线为单检测器；人脸与遗留物需分次跑（OpenCV → YOLO），或后续换舱内专用权重。
            </div>
          </>
        }
      />
      <Space wrap style={{ marginBottom: 12 }}>
        {effectivePresets.map((p) => (
          <Button
            key={p.id || p.label}
            size="small"
            type={p.id === 'cabin_leftover' ? 'primary' : 'default'}
            onClick={() => applyPreset(p)}
          >
            {p.mode === 'replace' ? `设为 · ${p.label}` : `+ ${p.label}`}
          </Button>
        ))}
      </Space>
      <Checkbox.Group
        style={{ width: '100%' }}
        value={selected}
        onChange={(vals) => setSelected(vals as string[])}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: '6px 12px',
            maxHeight: 360,
            overflowY: 'auto',
            padding: 4,
          }}
        >
          {options.map((opt) => (
            <Checkbox key={opt.value} value={opt.value}>
              {opt.label}
            </Checkbox>
          ))}
        </div>
      </Checkbox.Group>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 12 }}>
        已选 {selected.length} 类
        {selected.length
          ? `：${selected.slice(0, 8).join(', ')}${selected.length > 8 ? '…' : ''}`
          : '（全部）'}
      </Typography.Text>
    </Modal>
  )
}
