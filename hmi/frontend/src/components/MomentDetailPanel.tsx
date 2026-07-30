import { AudioOutlined, InfoCircleOutlined, TagOutlined } from '@ant-design/icons'
import { Collapse, Descriptions, Empty, Space, Tag, Typography } from 'antd'
import type { AxiosError } from 'axios'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type {
  AiLabelHint,
  AudioSegment,
  ClipLabelReview,
  ClipLabelView,
  ClipOverview,
  EventLabel,
  TaxonomyNodeDetail,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canAccessReview } from '../auth/roles'
import { ContentCard } from './ui'
import { ClipLabelTreeView } from './ClipLabelTreeView'
import { extractAiHintsFromLabels } from '../utils/labelDisplay'

interface Props {
  clip: ClipOverview
  runId: string
  cursorNs: number
  clipLabel?: ClipLabelView | null
  sceneDescription?: string | null
  asrSegments?: AudioSegment[]
  events?: EventLabel[]
}

function mergeAsrText(segments: AudioSegment[]): string {
  const parts = segments.map((s) => (s.asr_text ?? '').trim()).filter(Boolean)
  return parts.join('\n')
}

export function MomentDetailPanel({
  clip,
  runId,
  cursorNs,
  clipLabel,
  sceneDescription,
  asrSegments = [],
  events = [],
}: Props) {
  const { user } = useAuth()
  const canQuickReview = canAccessReview(user?.roles)
  const [review, setReview] = useState<ClipLabelReview | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [reviewLoading, setReviewLoading] = useState(false)

  const label = clipLabel ?? null
  const anchorNs =
    label?.anchor_timestamp_ns != null ? Number(label.anchor_timestamp_ns) : cursorNs

  const asrText = useMemo(() => mergeAsrText(asrSegments), [asrSegments])
  const labelsForTree = review?.labels_json ?? label?.labels_json ?? {}
  const aiLabelHints = useMemo((): Record<string, AiLabelHint> => {
    const fromReview = review?.ai_label_hints ?? {}
    if (Object.keys(fromReview).length > 0) return fromReview
    return extractAiHintsFromLabels((label?.labels_json ?? {}) as Record<string, unknown>)
  }, [review?.ai_label_hints, label?.labels_json])

  const loadReviewMeta = useCallback(async () => {
    if (!clip.clip_id || !runId) return
    setReviewLoading(true)
    try {
      let detail: ClipLabelReview
      try {
        detail = await api.getReviewDetail(clip.clip_id, runId)
      } catch (e) {
        if ((e as AxiosError)?.response?.status === 404) {
          setReview(null)
          const versions = await api.listTaxonomyVersions()
          const published = versions.find((v) => v.status === 'published')
          if (published) {
            const tree = await api.getTaxonomyTree(published.id)
            setTaxonomyNodes(tree.nodes)
          }
          return
        }
        throw e
      }
      setReview(detail)
      if (detail.taxonomy_version_id) {
        const tree = await api.getTaxonomyTree(detail.taxonomy_version_id)
        setTaxonomyNodes(tree.nodes)
      } else {
        const versions = await api.listTaxonomyVersions()
        const published = versions.find((v) => v.status === 'published')
        if (published) {
          const tree = await api.getTaxonomyTree(published.id)
          setTaxonomyNodes(tree.nodes)
        }
      }
    } catch {
      setReview(null)
    } finally {
      setReviewLoading(false)
    }
  }, [clip.clip_id, runId])

  useEffect(() => {
    void loadReviewMeta()
  }, [loadReviewMeta])

  const handleReviewSaved = (updated: ClipLabelReview) => {
    setReview(updated)
  }

  const collapseItems = [
    {
      key: 'meta',
      label: (
        <Typography.Text strong>
          <InfoCircleOutlined /> 基本信息
        </Typography.Text>
      ),
      children: (
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="当前时刻">
            {api.formatTimestampNs(cursorNs, clip.start_time_ns)}
          </Descriptions.Item>
          {label?.anchor_timestamp_ns != null ? (
            <Descriptions.Item label="Clip 锚点">
              {api.formatTimestampNs(anchorNs, clip.start_time_ns)}
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="时长">{clip.duration_sec.toFixed(1)}s</Descriptions.Item>
          {review ? (
            <Descriptions.Item label="校核状态">
              <Tag color={review.review_status === 'reviewed' ? 'success' : 'processing'}>
                {review.review_status === 'reviewed' ? 'Clip 已校核' : 'Clip 待校核'}
              </Tag>
            </Descriptions.Item>
          ) : null}
        </Descriptions>
      ),
    },
    {
      key: 'labels',
      label: (
        <Typography.Text strong>
          <TagOutlined /> Clip 标签
        </Typography.Text>
      ),
      children: label?.clip_label_ready ? (
        reviewLoading ? (
          <Typography.Text type="secondary">加载标签树…</Typography.Text>
        ) : (
          <ClipLabelTreeView
            taxonomyNodes={taxonomyNodes}
            labelsJson={labelsForTree as Record<string, unknown>}
            fieldReviewedLabelIds={review?.field_reviewed_label_ids ?? []}
            aiLabelHints={aiLabelHints}
            canQuickReview={canQuickReview && Boolean(label?.clip_label_ready)}
            clipId={clip.clip_id}
            runId={runId}
            onReviewSaved={handleReviewSaved}
          />
        )
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          该 Clip 尚无结构化标签
        </Typography.Text>
      ),
    },
    {
      key: 'asr',
      label: (
        <Typography.Text strong>
          <AudioOutlined /> ASR
        </Typography.Text>
      ),
      children: asrText ? (
        <Typography.Paragraph className="clip-detail-asr" style={{ margin: 0 }}>
          {asrText}
        </Typography.Paragraph>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无 ASR 文本" style={{ margin: '8px 0' }} />
      ),
    },
    {
      key: 'other',
      label: <Typography.Text strong>其他信息</Typography.Text>,
      children:
        events.length > 0 ? (
          <Space direction="vertical" size={6} style={{ width: '100%' }}>
            {events.map((e, i) => (
              <div key={i} style={{ padding: 8, background: '#fff7e6', borderRadius: 6 }}>
                <Tag color="volcano">{e.parsed_label ?? '事件'}</Tag>
                <Typography.Text code style={{ fontSize: 10, display: 'block', marginTop: 4 }}>
                  {e.event_data}
                </Typography.Text>
              </div>
            ))}
          </Space>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无其他信息" style={{ margin: '8px 0' }} />
        ),
    },
  ]

  return (
    <>
      <ContentCard title="Clip 详情" className="clip-detail-panel" noPadding>
        {sceneDescription ? (
          <Typography.Paragraph
            type="secondary"
            style={{ fontSize: 13, margin: '0 16px 12px', paddingTop: 12 }}
          >
            {sceneDescription}
          </Typography.Paragraph>
        ) : null}
        <Collapse
          className="clip-detail-panel__collapse"
          bordered={false}
          defaultActiveKey={[]}
          items={collapseItems}
        />
      </ContentCard>
    </>
  )
}
