import { ClockCircleOutlined, TagOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { Space, Spin, Typography } from 'antd'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AudioNvhBootstrap, ClipOverview } from '../api/types'
import { formatCollectionPeriod } from '../utils/format'
import { AudioNvhTimelinePanel } from './AudioNvhTimelinePanel'
import { ClipTimelinePanel, type ClipTimelineState } from './ClipTimelinePanel'
import type { PreviewContext } from './ClipPreviewVideo'

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
  /** browse = 总览只读预览；review = 校核可编辑框 */
  previewContext?: PreviewContext
  onTimelineStateChange?: (state: ClipTimelineState) => void
  selectedBoxKey?: string | null
  onSelectedBoxChange?: (key: string | null) => void
  onOverlaySaved?: () => void
  /** Force media mode; default auto-detects audio_nvh via bootstrap API. */
  mediaMode?: 'auto' | 'cabin' | 'audio_nvh'
  /** Fires when resolved media mode is known (after auto-detect). */
  onMediaModeChange?: (mode: 'cabin' | 'audio_nvh') => void
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
  previewContext = 'browse',
  onTimelineStateChange,
  selectedBoxKey,
  onSelectedBoxChange,
  onOverlaySaved,
  mediaMode = 'auto',
  onMediaModeChange,
}: ClipMediaPanelProps) {
  const [clipOverview, setClipOverview] = useState<ClipOverview | null>(null)
  const [mode, setMode] = useState<'pending' | 'cabin' | 'audio_nvh'>(
    mediaMode === 'auto' ? 'pending' : mediaMode,
  )

  const handleClipReady = useCallback((clip: ClipOverview) => {
    setClipOverview(clip)
  }, [])

  useEffect(() => {
    setClipOverview(null)
    if (mediaMode !== 'auto') {
      setMode(mediaMode)
      onMediaModeChange?.(mediaMode)
      return
    }
    let cancelled = false
    setMode('pending')
    void api
      .getAudioNvhBootstrap(clipId, runId)
      .then(() => {
        if (!cancelled) {
          setMode('audio_nvh')
          onMediaModeChange?.('audio_nvh')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMode('cabin')
          onMediaModeChange?.('cabin')
        }
      })
    return () => {
      cancelled = true
    }
  }, [clipId, runId, mediaMode, onMediaModeChange])

  const onAudioReady = useCallback((_boot: AudioNvhBootstrap) => {
    /* reserved for explorer scene text */
  }, [])

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
        {mode === 'pending' ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : mode === 'audio_nvh' ? (
          <div className="review-clip-card__media">
            <AudioNvhTimelinePanel
              clipId={clipId}
              runId={runId}
              previewContext={previewContext}
              testId="audio-nvh-timeline"
              onReady={onAudioReady}
            />
            <Typography.Text type="secondary" className="review-clip-card__media-hint">
              四通道梅尔频谱 + SPL + 波形共用时间轴 · 点击谱图/曲线跳转
            </Typography.Text>
          </div>
        ) : (
          <div className="review-clip-card__media review-clip-card__media--cameras-top">
            <ClipTimelinePanel
              key={`${clipId}:${runId}:${initialTimestampNs ?? ''}`}
              clipId={clipId}
              runId={runId}
              initialTimestampNs={initialTimestampNs}
              camerasFirst
              previewContext={previewContext}
              onClipReady={handleClipReady}
              onTimelineStateChange={onTimelineStateChange}
              selectedBoxKey={selectedBoxKey}
              onSelectedBoxChange={onSelectedBoxChange}
              onOverlaySaved={onOverlaySaved}
            />
            <Typography.Text type="secondary" className="review-clip-card__media-hint">
              <VideoCameraOutlined /> Clip 级 MP4 预览 · 空格播放（含音频）
            </Typography.Text>
          </div>
        )}

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
