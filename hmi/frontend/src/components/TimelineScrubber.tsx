import { Slider, Space, Typography } from 'antd'
import { api } from '../api'
import { snapToNearest, type SnapPoint } from '../utils/timeline'

interface Props {
  startNs: number
  endNs: number
  valueNs: number
  onChange: (ns: number) => void
  snapPoints?: SnapPoint[]
  snapped?: boolean
}

export function TimelineScrubber({
  startNs,
  endNs,
  valueNs,
  onChange,
  snapPoints = [],
  snapped = false,
}: Props) {
  const durationMs = (endNs - startNs) / 1e6
  const valueMs = (valueNs - startNs) / 1e6

  const handleChange = (v: number) => {
    onChange(startNs + v * 1e6)
  }

  const handleComplete = (v: number) => {
    const raw = startNs + v * 1e6
    onChange(snapPoints.length ? snapToNearest(raw, snapPoints) : raw)
  }

  return (
    <div style={{ padding: '4px 4px 0' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 4 }}>
        <Typography.Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
          {api.formatTimestampNs(startNs, startNs)}
        </Typography.Text>
        <Space size={8}>
          <Typography.Text strong style={{ fontFamily: 'monospace' }}>
            {api.formatTimestampNs(valueNs, startNs)}
          </Typography.Text>
          {snapped && <Typography.Text type="success" style={{ fontSize: 11 }}>已磁吸</Typography.Text>}
        </Space>
        <Typography.Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
          {api.formatTimestampNs(endNs, startNs)}
        </Typography.Text>
      </Space>
      <Slider
        min={0}
        max={durationMs}
        step={50}
        value={valueMs}
        onChange={handleChange}
        onChangeComplete={handleComplete}
        tooltip={{ formatter: (v) => api.formatTimestampNs(startNs + (v ?? 0) * 1e6, startNs) }}
      />
      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
        ←/→ 微调 · Shift+←/→ 跳转事件/ASR · 松手磁吸标记点
      </Typography.Text>
    </div>
  )
}
