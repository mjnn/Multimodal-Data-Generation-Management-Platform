import { ClockCircleOutlined, TagOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import type { ClipOverview } from '../api/types'
import { formatCollectionPeriod } from '../utils/format'
import { ClipTimelinePanel, type ClipTimelineState } from './ClipTimelinePanel'

export type ClipMediaPanelProps = {
  clipId: string
  runId: string
  initialTimestampNs?: number
  title: string
  labelPreview?: string
  metaTags?: ReactNode
  className?: string
  testId?: string
  /** When false, hide title/label block under the video (detail shown elsewhere). */
  showMetaBelow?: boolean
  onTimelineStateChange?: (state: ClipTimelineState) => void
}

export function ClipMediaPanel({
  clipId,
  runId,
  initialTimestampNs,
  title,
  labelPreview,
  metaTags,
  className,
  testId,
  showMetaBelow = true,
  onTimelineStateChange,
}: ClipMediaPanelProps) {
  const [clipOverview, setClipOverview] = useState<ClipOverview | null>(null)

  const handleClipReady = useCallback((clip: ClipOverview) => {
    setClipOverview(clip)
  }, [])

  useEffect(() => {
    setClipOverview(null)
  }, [clipId, runId])

  const collectionPeriod =
    clipOverview != null
      ? formatCollectionPeriod(
          clipOverview.start_time_ns,
          clipOverview.end_time_ns,
          clipOverview.duration_sec,
        )
      : null

  return (
    <div className={`clip-media-panel ${className ?? ''}`.trim()} data-testid={testId}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div className="review-clip-card__media review-clip-card__media--cameras-top">
          <ClipTimelinePanel
            key={`${clipId}:${runId}:${initialTimestampNs ?? ''}`}
            clipId={clipId}
            runId={runId}
            initialTimestampNs={initialTimestampNs}
            camerasFirst
            onClipReady={handleClipReady}
            onTimelineStateChange={onTimelineStateChange}
          />
          <Typography.Text type="secondary" className="review-clip-card__media-hint">
            <VideoCameraOutlined /> Clip 级 MP4 预览 · 空格播放（含音频）
          </Typography.Text>
        </div>

        {showMetaBelow ? (
        <div className="review-clip-card__meta review-clip-card__meta--below">
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              {title}
            </Typography.Title>
            <Typography.Text type="secondary" className="mono" style={{ fontSize: 12, wordBreak: 'break-all' }}>
              {clipId}
            </Typography.Text>
            {collectionPeriod ? (
              <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                <ClockCircleOutlined /> 采集时间：{collectionPeriod}
              </Typography.Text>
            ) : null}
            {labelPreview ? (
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }} ellipsis={{ rows: 2 }}>
                <TagOutlined /> {labelPreview}
              </Typography.Paragraph>
            ) : null}
            {metaTags ? <Space size={6} wrap>{metaTags}</Space> : null}
          </Space>
        </div>
        ) : null}
      </Space>
    </div>
  )
}
