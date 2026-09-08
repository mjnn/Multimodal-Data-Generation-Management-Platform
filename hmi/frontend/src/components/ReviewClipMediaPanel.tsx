import { ExportOutlined } from '@ant-design/icons'
import { Alert, Button, Empty, Space, Tabs, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { ReviewTarget, ReviewV2ClipCard as ClipCard, ReviewV2Task } from '../api/types'
import { ClipMediaPanel } from './ClipMediaPanel'
import type { ClipTimelineState } from './ClipTimelinePanel'
import { clipDisplayName } from '../utils/clipDisplay'
import { buildClipExplorerHref } from '../utils/clipExplorerHref'
import { useDataTypeRecipe } from '../context/DataTypeWorkspaceContext'
import { resolveDetailCards } from '../utils/overviewLayout'

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

function explorerHref(task: ReviewV2Task, dataTypeId?: string | null): string {
  const t = parseAnchorTimestampNs(task.clip_card.anchor_timestamp_ns)
  return buildClipExplorerHref(task.clip_id, {
    runId: task.run_id,
    dataTypeId,
    t: t ?? null,
  })
}

export function ReviewClipMediaPanel({ task, reviewTargets }: Props) {
  const { clip_card: card } = task
  const recipe = useDataTypeRecipe()
  const detailCards = resolveDetailCards(recipe)
  const layoutNvh = detailCards.some((c) => c.widget_id === 'spectrum_timeline')
  const layoutLabelsTree = detailCards.some((c) => c.widget_id === 'labels_tree')
  const labelsJson =
    (card as ClipCard & { labels_json?: Record<string, unknown> }).labels_json ?? {}
  const [liveHasBbox, setLiveHasBbox] = useState<boolean | null>(null)
  const [sideTab, setSideTab] = useState<'asr' | 'nvh'>('asr')
  const [isAudioNvh, setIsAudioNvh] = useState(false)
  const nvh = layoutNvh || isAudioNvh
  const hasBbox = liveHasBbox ?? Boolean(card.has_bbox_preview)
  const targets = reviewTargets?.length ? reviewTargets : (['labels'] as ReviewTarget[])
  const reviewBboxes = targets.includes('bboxes')
  const reviewLabels = targets.includes('labels')

  const onTimelineStateChange = useCallback((state: ClipTimelineState) => {
    setLiveHasBbox(state.hasBboxPreview)
  }, [])

  const onMediaModeChange = useCallback((mode: 'cabin' | 'audio_nvh') => {
    const nvh = mode === 'audio_nvh'
    setIsAudioNvh(nvh)
    setSideTab(nvh ? 'nvh' : 'asr')
  }, [])

  useEffect(() => {
    setLiveHasBbox(null)
    setIsAudioNvh(false)
    setSideTab(layoutNvh ? 'nvh' : 'asr')
  }, [task.clip_id, task.run_id, layoutNvh])

  const mediaKey = `${task.clip_id}:${task.run_id}`

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }} key={mediaKey}>
      {nvh ? (
        <Alert
          type="info"
          showIcon
          message="NVH 频谱校核"
          description="媒体区为四通道梅尔频谱 + SPL + 波形共用时间轴。客观标签只读；语义标签编辑保存待后续工单。"
          data-testid="review-nvh-notice"
          action={
            <Link to={explorerHref(task, recipe?.id)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<ExportOutlined />} data-testid="review-open-explorer">
                打开总览
              </Button>
            </Link>
          }
        />
      ) : reviewBboxes ? (
        <Alert
          type="info"
          showIcon
          message="识别框校核"
          description="切换到「带可编辑框」按帧新建/删除/调整与改识别内容，保存本帧写回 bboxes.jsonl。「原图参考」无叠加框。"
          data-testid="review-bbox-edit-notice"
          action={
            <Link to={explorerHref(task, recipe?.id)} target="_blank" rel="noreferrer">
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
            <Link to={explorerHref(task, recipe?.id)} target="_blank" rel="noreferrer">
              <Button size="small" icon={<ExportOutlined />} data-testid="review-open-explorer">
                打开总览
              </Button>
            </Link>
          }
        />
      ) : (
        <div style={{ textAlign: 'right' }}>
          <Link to={explorerHref(task, recipe?.id)} target="_blank" rel="noreferrer">
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
        onMediaModeChange={onMediaModeChange}
        detailCards={detailCards}
        metaTags={
          <>
            {renderGateTags(card)}
            {card.review_status ? (
              <Tag color={card.review_status === 'reviewed' ? 'success' : 'warning'}>
                {card.review_status === 'reviewed' ? 'Clip 已校核' : 'Clip 待校核'}
              </Tag>
            ) : null}
            {nvh ? <Tag color="cyan">NVH 频谱</Tag> : null}
            {!nvh && hasBbox ? <Tag color="blue">有 BBox</Tag> : null}
            {!nvh && reviewBboxes ? <Tag color="geekblue">校核识别框</Tag> : null}
            {reviewLabels ? <Tag>校核标签</Tag> : null}
          </>
        }
      />

      {layoutLabelsTree ? (
        <pre data-testid="overview-runtime-labels_tree" style={{ maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
          {JSON.stringify(labelsJson, null, 2)}
        </pre>
      ) : null}

      <Tabs
        activeKey={sideTab}
        onChange={(k) => setSideTab(k as 'asr' | 'nvh')}
        items={
          nvh
            ? [
                {
                  key: 'nvh',
                  label: 'NVH 说明',
                  children: (
                    <Typography.Paragraph type="secondary" style={{ margin: 0 }} data-testid="review-nvh-side">
                      客观声压/频谱标签见媒体区右侧标签轨。语义类（L6）编辑与写回 API 尚未接线，本侧栏仅作校核上下文提示。
                    </Typography.Paragraph>
                  ),
                },
              ]
            : [
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
              ]
        }
      />
    </Space>
  )
}
