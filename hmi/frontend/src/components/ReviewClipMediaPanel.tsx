import { ExportOutlined } from '@ant-design/icons'
import { Alert, Button, Empty, Space, Tabs, Tag, Typography } from 'antd'
import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReviewTarget, ReviewV2ClipCard as ClipCard, ReviewV2Task } from '../api/types'
import { ClipMediaPanel } from './ClipMediaPanel'
import type { ClipTimelineState } from './ClipTimelinePanel'
import { clipDisplayName } from '../utils/clipDisplay'

type Props = {
  task: ReviewV2Task
  /** From assignment batch; default labels-only (legacy). */
  reviewTargets?: ReviewTarget[]
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

export function ReviewClipMediaPanel({ task, reviewTargets }: Props) {
  const { clip_card: card } = task
  const [liveHasBbox, setLiveHasBbox] = useState<boolean | null>(null)
  const [sideTab, setSideTab] = useState<'asr'>('asr')
  const hasBbox = liveHasBbox ?? Boolean(card.has_bbox_preview)
  const targets = reviewTargets?.length ? reviewTargets : (['labels'] as ReviewTarget[])
  const reviewBboxes = targets.includes('bboxes')
  const reviewLabels = targets.includes('labels')

  const onTimelineStateChange = useCallback((state: ClipTimelineState) => {
    setLiveHasBbox(state.hasBboxPreview)
  }, [])

  const mediaKey = `${task.clip_id}:${task.run_id}`

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} key={mediaKey}>
      {reviewBboxes ? (
        <Alert
          type="info"
          showIcon
          message="识别框校核"
          description="切换到「带可编辑框」按帧新建/删除/调整与改识别内容，保存本帧写回 bboxes.jsonl。「原图参考」无叠加框。"
          data-testid="review-bbox-edit-notice"
          action={
            <Link to={explorerHref(task)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<ExportOutlined />} data-testid="review-open-explorer">
                打开总览
              </Button>
            </Link>
          }
        />
      ) : hasBbox ? (
        <Alert
          type="info"
          showIcon
          message="检测框预览"
          description="本任务校核目标为标签。可在「带可编辑框」查看/改框；若需框校核任务，请派发时选择校核目标「识别框」。总览「带识别框预览」为只读 jsonl 叠加。"
          data-testid="review-bbox-preview-notice"
          action={
            <Link to={explorerHref(task)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<ExportOutlined />} data-testid="review-open-explorer">
                打开总览
              </Button>
            </Link>
          }
        />
      ) : (
        <div style={{ textAlign: 'right' }}>
          <Link to={explorerHref(task)} target="_blank" rel="noreferrer">
            <Button size="small" type="link" icon={<ExportOutlined />} data-testid="review-open-explorer">
              打开总览
            </Button>
          </Link>
        </div>
      )}

      <ClipMediaPanel
        clipId={task.clip_id}
        runId={task.run_id}
        previewContext="review"
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
            {hasBbox ? <Tag color="blue">有 BBox</Tag> : null}
            {reviewBboxes ? <Tag color="geekblue">校核识别框</Tag> : null}
            {reviewLabels ? <Tag>校核标签</Tag> : null}
          </>
        }
      />

      <Tabs
        activeKey={sideTab}
        onChange={(k) => setSideTab(k as 'asr')}
        items={[
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
