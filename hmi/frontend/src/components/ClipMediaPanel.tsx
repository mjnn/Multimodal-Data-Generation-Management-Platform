import { ClockCircleOutlined, TagOutlined, VideoCameraOutlined } from '@ant-design/icons'
import { Space, Spin, Typography } from 'antd'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AudioNvhBootstrap, ClipOverview, ViewCard } from '../api/types'
import { formatCollectionPeriod } from '../utils/format'
import { portIdToChannelIndex } from '../utils/overviewLayout'
import { asBindingList } from '../utils/recipePipeline'
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
  /** From recipe.overview.detail. Empty/undefined → auto-detect fallback. */
  detailCards?: ViewCard[]
  /** Shared playheads keyed by sync_group. */
  syncCursors?: Record<string, number>
  onSyncSeek?: (group: string, t: number) => void
}

const MEDIA_WIDGETS = new Set(['spectrum_timeline', 'video_timeline', 'frame_gallery_bbox'])

function cardPortId(card: ViewCard): string {
  const bind = asBindingList(card.bindings?.in)[0]
  return bind && bind.kind === 'upstream' ? String(bind.port_id || '') : ''
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
  detailCards,
  syncCursors,
  onSyncSeek,
}: ClipMediaPanelProps) {
  const composed = (detailCards || []).filter((c) => MEDIA_WIDGETS.has(c.widget_id))
  const useLayout = composed.length > 0
  const hasSpectrum = composed.some((c) => c.widget_id === 'spectrum_timeline')
  const [clipOverview, setClipOverview] = useState<ClipOverview | null>(null)
  const [mode, setMode] = useState<'pending' | 'cabin' | 'audio_nvh'>(
    useLayout ? (hasSpectrum ? 'audio_nvh' : 'cabin') : mediaMode === 'auto' ? 'pending' : mediaMode,
  )

  const handleClipReady = useCallback((clip: ClipOverview) => {
    setClipOverview(clip)
  }, [])

  useEffect(() => {
    setClipOverview(null)
    if (useLayout) {
      const next = hasSpectrum ? 'audio_nvh' : 'cabin'
      setMode(next)
      onMediaModeChange?.(next)
      return
    }
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
  }, [clipId, runId, mediaMode, onMediaModeChange, useLayout, hasSpectrum])

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

  const firstSpectrumKey = composed.find((c) => c.widget_id === 'spectrum_timeline')?.key
  const firstVideoKey = composed.find((c) => c.widget_id === 'video_timeline')?.key

  const renderCard = (card: ViewCard) => {
    const port = cardPortId(card)
    const chIndex = portIdToChannelIndex(port)
    const group = String(card.sync_group || '').trim()
    const seekS = group && syncCursors && group in syncCursors ? syncCursors[group] : undefined
    const onSeekS = group && onSyncSeek ? (t: number) => onSyncSeek(group, t) : undefined
    if (card.widget_id === 'spectrum_timeline') {
      return (
        <div
          key={card.key}
          className="review-clip-card__media"
          data-testid={`overview-runtime-spectrum_timeline-${port || card.key}`}
        >
          <AudioNvhTimelinePanel
            clipId={clipId}
            runId={runId}
            previewContext={previewContext}
            testId={card.key === firstSpectrumKey ? 'audio-nvh-timeline' : undefined}
            onReady={onAudioReady}
            channelIndex={card.key === 'fallback-spectrum' ? undefined : (chIndex ?? 0)}
            cursorS={seekS}
            onCursorChange={onSeekS}
            enableAudio={card.key === firstSpectrumKey}
          />
          <Typography.Text type="secondary" className="review-clip-card__media-hint">
            单路梅尔频谱 + SPL + 波形 · 点击谱图/曲线跳转
          </Typography.Text>
        </div>
      )
    }
    if (card.widget_id === 'video_timeline' || card.widget_id === 'frame_gallery_bbox') {
      const cam = card.widget_id === 'video_timeline' ? chIndex ?? undefined : undefined
      const seekNs = seekS != null ? Math.round(seekS * 1e9) : undefined
      return (
        <div
          key={card.key}
          className="review-clip-card__media review-clip-card__media--cameras-top"
          data-testid={`overview-runtime-${card.widget_id}`}
        >
          <ClipTimelinePanel
            key={`${clipId}:${runId}:${initialTimestampNs ?? ''}:${card.key}`}
            clipId={clipId}
            runId={runId}
            initialTimestampNs={initialTimestampNs}
            camerasFirst
            previewContext={previewContext}
            onClipReady={handleClipReady}
            onTimelineStateChange={card.key === firstVideoKey || card.widget_id === 'frame_gallery_bbox' ? onTimelineStateChange : undefined}
            selectedBoxKey={selectedBoxKey}
            onSelectedBoxChange={onSelectedBoxChange}
            onOverlaySaved={onOverlaySaved}
            cameraIndex={cam}
            cursorNs={seekNs}
            onCursorNsChange={
              group && onSyncSeek
                ? (ns) => onSyncSeek(group, ns / 1e9)
                : undefined
            }
          />
          <Typography.Text type="secondary" className="review-clip-card__media-hint">
            <VideoCameraOutlined /> Clip 级 MP4 预览 · 空格播放（含音频）
          </Typography.Text>
        </div>
      )
    }
    return null
  }

  const fallbackCard: ViewCard =
    mode === 'audio_nvh'
      ? { key: 'fallback-spectrum', widget_id: 'spectrum_timeline', bindings: {} }
      : { key: 'fallback-video', widget_id: 'frame_gallery_bbox', bindings: {} }

  const mediaBody = useLayout
    ? composed.map(renderCard)
    : mode === 'pending'
      ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      )
      : renderCard(fallbackCard)

  return (
    <div className={`clip-media-panel ${className ?? ''}`.trim()} data-testid={testId}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {mediaBody}

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
