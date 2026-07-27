import { CloseOutlined } from '@ant-design/icons'
import { Button, Space, Tag, Typography } from 'antd'
import { useCallback, useRef, useState } from 'react'
import { api } from '../api'
import type { AudioSegment, EventLabel } from '../api/types'

interface Props {
  startNs: number
  endNs: number
  cursorNs: number
  sampledTimestamps: number[]
  events: EventLabel[]
  asrSegments: AudioSegment[]
  rangeStartNs: number | null
  rangeEndNs: number | null
  onCursorChange: (ns: number) => void
  onRangeChange: (start: number | null, end: number | null) => void
}

export function TimelineMinimap({
  startNs,
  endNs,
  cursorNs,
  sampledTimestamps,
  events,
  asrSegments,
  rangeStartNs,
  rangeEndNs,
  onCursorChange,
  onRangeChange,
}: Props) {
  const barRef = useRef<HTMLDivElement>(null)
  const [brushing, setBrushing] = useState(false)
  const [brushStart, setBrushStart] = useState<number | null>(null)

  const duration = endNs - startNs
  const pct = (ns: number) => ((ns - startNs) / duration) * 100

  const nsFromClientX = useCallback(
    (clientX: number) => {
      const el = barRef.current
      if (!el) return startNs
      const rect = el.getBoundingClientRect()
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      return startNs + ratio * duration
    },
    [startNs, duration],
  )

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.shiftKey) {
      setBrushing(true)
      const ns = nsFromClientX(e.clientX)
      setBrushStart(ns)
      onRangeChange(ns, ns)
      return
    }
    onCursorChange(nsFromClientX(e.clientX))
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!brushing || brushStart == null) return
    const end = nsFromClientX(e.clientX)
    onRangeChange(Math.min(brushStart, end), Math.max(brushStart, end))
  }

  const handleMouseUp = () => setBrushing(false)

  const hasRange = rangeStartNs != null && rangeEndNs != null && rangeEndNs > rangeStartNs

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          迷你地图 · 点击跳转 · Shift+拖拽选时间段
        </Typography.Text>
        <Space size={4}>
          <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>锚点</Tag>
          <Tag color="orange" style={{ fontSize: 10, margin: 0 }}>事件</Tag>
          <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>ASR</Tag>
        </Space>
      </div>
      <div
        ref={barRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{
          position: 'relative',
          height: 36,
          background: '#f5f5f5',
          borderRadius: 4,
          cursor: 'crosshair',
          border: '1px solid #e8e8e8',
        }}
      >
        {asrSegments.map((s) => (
          <div
            key={`asr-${s.segment_id}`}
            style={{
              position: 'absolute',
              left: `${pct(s.start_ns)}%`,
              width: `${Math.max(0.5, pct(s.end_ns) - pct(s.start_ns))}%`,
              top: 4,
              height: 28,
              background: 'rgba(22, 119, 255, 0.15)',
              borderRadius: 2,
            }}
          />
        ))}
        {sampledTimestamps.map((ts, i) => (
          <div
            key={`s-${i}`}
            style={{
              position: 'absolute',
              left: `${pct(ts)}%`,
              top: 6,
              width: 2,
              height: 24,
              background: '#1677ff',
              transform: 'translateX(-1px)',
            }}
          />
        ))}
        {events.map((e, i) => (
          <div
            key={`e-${i}`}
            title={e.parsed_label}
            style={{
              position: 'absolute',
              left: `${pct(e.timestamp_ns)}%`,
              top: 14,
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: '#fa8c16',
              transform: 'translateX(-4px)',
            }}
          />
        ))}
        {hasRange && (
          <div
            style={{
              position: 'absolute',
              left: `${pct(rangeStartNs!)}%`,
              width: `${pct(rangeEndNs!) - pct(rangeStartNs!)}%`,
              top: 0,
              height: '100%',
              background: 'rgba(114, 46, 209, 0.12)',
              border: '1px solid rgba(114, 46, 209, 0.4)',
              pointerEvents: 'none',
            }}
          />
        )}
        <div
          style={{
            position: 'absolute',
            left: `${pct(cursorNs)}%`,
            top: 0,
            width: 2,
            height: '100%',
            background: '#722ed1',
            transform: 'translateX(-1px)',
            pointerEvents: 'none',
          }}
        />
      </div>
      {hasRange && (
        <Space style={{ marginTop: 6 }}>
          <Tag color="purple">
            筛选 {api.formatTimestampNs(rangeStartNs!, startNs)} —{' '}
            {api.formatTimestampNs(rangeEndNs!, startNs)}
          </Tag>
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            onClick={() => onRangeChange(null, null)}
          >
            清除
          </Button>
        </Space>
      )}
    </div>
  )
}
