import { Typography } from 'antd'
import type { CSSProperties } from 'react'
import {
  CLIP_BUCKET_COLORS,
  CLIP_BUCKET_LABELS,
  CLIP_BUCKET_ORDER,
  type ClipOverviewBucketCounts,
} from '../utils/overviewClipBuckets'

type Props = {
  counts: ClipOverviewBucketCounts
  total: number
  size?: number
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function describeSlice(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, endAngle)
  const end = polarToCartesian(cx, cy, r, startAngle)
  const largeArc = endAngle - startAngle <= 180 ? 0 : 1
  return `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y} Z`
}

export function OverviewClipPieChart({ counts, total, size = 280 }: Props) {
  if (total <= 0) {
    return (
      <Typography.Text type="secondary" className="overview-clip-pie__empty">
        暂无 Clip 数据
      </Typography.Text>
    )
  }

  const cx = 100
  const cy = 100
  const r = 88
  const hole = 50
  let cursor = 0
  const slices = CLIP_BUCKET_ORDER.map((key) => {
    const value = counts[key]
    const start = cursor
    const sweep = (value / total) * 360
    cursor += sweep
    return {
      key,
      value,
      color: CLIP_BUCKET_COLORS[key],
      d: value > 0 ? describeSlice(cx, cy, r, start, start + sweep) : null,
    }
  }).filter((s) => s.value > 0)

  return (
    <div className="overview-clip-pie overview-clip-pie--solo">
      <svg
        viewBox="0 0 200 200"
        width={size}
        height={size}
        aria-label="Clip 阶段分布饼图"
        role="img"
      >
        {slices.length === 1 ? (
          <circle cx={cx} cy={cy} r={r} fill={slices[0].color} />
        ) : (
          slices.map((s) => (s.d ? <path key={s.key} d={s.d} fill={s.color} /> : null))
        )}
        <circle cx={cx} cy={cy} r={hole} fill="var(--color-surface-1, #fff)" />
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          fontSize={28}
          fontWeight={600}
          fill="var(--color-ink, #111)"
        >
          {total}
        </text>
        <text x={cx} y={cy + 18} textAnchor="middle" fontSize={13} fill="var(--color-ink-subtle, #888)">
          Clip 总数
        </text>
      </svg>
    </div>
  )
}

type GridProps = {
  counts: ClipOverviewBucketCounts
  total: number
}

export function OverviewClipMetricsGrid({ counts, total }: GridProps) {
  return (
    <div className="overview-metrics-grid">
      {CLIP_BUCKET_ORDER.map((key) => {
        const value = counts[key]
        const pct = total > 0 ? Math.round((value / total) * 1000) / 10 : 0
        return (
          <div
            key={key}
            className="overview-metrics-grid__cell"
            style={{ '--metric-accent': CLIP_BUCKET_COLORS[key] } as CSSProperties}
          >
            <span className="overview-metrics-grid__label">{CLIP_BUCKET_LABELS[key]}</span>
            <span className="overview-metrics-grid__value">{value}</span>
            <span className="overview-metrics-grid__pct">{pct}%</span>
          </div>
        )
      })}
    </div>
  )
}
