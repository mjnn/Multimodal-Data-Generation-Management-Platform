import { ExportOutlined } from '@ant-design/icons'
import { Alert, Button, Empty, Space, Tabs, Tag, Typography } from 'antd'
import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReviewV2ClipCard as ClipCard, ReviewV2Task } from '../api/types'
import { ClipMediaPanel } from './ClipMediaPanel'
import type { ClipTimelineState } from './ClipTimelinePanel'
import { ReviewBboxQaBar } from './ReviewBboxQaBar'
import { clipDisplayName } from '../utils/clipDisplay'

type Props = {
  task: ReviewV2Task
}

function parseAnchorTimestampNs(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function renderGateTags(card: ClipCard) {
  const gate = card.multi_ai_gate
  if (!gate) return null
  if (!gate.passed) {
    return (
      <Tag key="gate" color="orange">
        Gate 未通过
      </Tag>
    )
  }
  return null
}

function explorerHref(task: ReviewV2Task): string {
  const params = new URLSearchParams()
  params.set('run_id', task.run_id)
  const t = parseAnchorTimestampNs(task.clip_card.anchor_timestamp_ns)
  if (t != null) params.set('t', String(t))
  return `/clips/${encodeURIComponent(task.clip_id)}?${params}`
}

export function ReviewClipMediaPanel({ task }: Props) {
  const { clip_card: card } = task
  // Prefer live explorer preview (same source as 带框 tab); card flag can lag or miss.
  const [liveHasBbox, setLiveHasBbox] = useState<boolean | null>(null)
  const [sideTab, setSideTab] = useState<'bbox' | 'asr'>('bbox')
  const hasBbox = liveHasBbox ?? Boolean(card.has_bbox_preview)

  const onTimelineStateChange = useCallback((state: ClipTimelineState) => {
    setLiveHasBbox(state.hasBboxPreview)
  }, [])

  // Reset when switching tasks so we don't keep the previous clip's live flag.
  const mediaKey = `${task.clip_id}:${task.run_id}`

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} key={mediaKey}>
      {hasBbox ? (
        <Alert
          type="info"
          showIcon
          message="检测框预览"
          description="默认展示带框预览，仅供观察检测质量；校核目标仍是右侧 Taxonomy 字段，不是框本身。"
          data-testid="review-bbox-preview-notice"
          action={
            <Link to={explorerHref(task)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<ExportOutlined />} data-testid="review-open-explorer">
                打开 Explorer 细看
              </Button>
            </Link>
          }
        />
      ) : (
        <div style={{ textAlign: 'right' }}>
          <Link to={explorerHref(task)} target="_blank" rel="noreferrer">
            <Button size="small" type="link" icon={<ExportOutlined />} data-testid="review-open-explorer">
              打开 Explorer 细看
            </Button>
          </Link>
        </div>
      )}

      <ClipMediaPanel
        clipId={task.clip_id}
        runId={task.run_id}
        initialTimestampNs={parseAnchorTimestampNs(card.anchor_timestamp_ns)}
        title={clipDisplayName({ clip_id: card.clip_id })}
        labelPreview={card.label_preview}
        testId="review-clip-card"
        onTimelineStateChange={onTimelineStateChange}
        metaTags={
          <>
            {renderGateTags(card)}
            {card.review_status ? (
              <Tag color={card.review_status === 'reviewed' ? 'success' : 'warning'}>
                {card.review_status === 'reviewed' ? 'Clip 已校核' : 'Clip 待校核'}
              </Tag>
            ) : null}
            {hasBbox ? <Tag color="blue">有 BBox 预览</Tag> : null}
          </>
        }
      />

      <Tabs
        activeKey={sideTab}
        onChange={(k) => setSideTab(k as 'bbox' | 'asr')}
        items={[
          {
            key: 'bbox',
            label: 'BBox 质量',
            children:
              liveHasBbox === null && !card.has_bbox_preview ? (
                <Typography.Text type="secondary" data-testid="bbox-qa-pending">
                  正在确认是否有带框预览…
                </Typography.Text>
              ) : (
                <ReviewBboxQaBar
                  clipId={task.clip_id}
                  runId={task.run_id}
                  hasBboxPreview={hasBbox}
                  initial={card.bbox_qa ?? null}
                />
              ),
          },
          {
            key: 'asr',
            label: 'ASR 文本',
            children: card.asr_text?.trim() ? (
              <Typography.Paragraph className="clip-detail-asr review-workbench-asr" style={{ margin: 0 }}>
                {card.asr_text.trim()}
              </Typography.Paragraph>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="本 Clip 无 ASR 文本"
                style={{ margin: '8px 0' }}
              />
            ),
          },
        ]}
      />
    </Space>
  )
}
