import { AudioOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { Alert, Empty, Space, Spin, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { ClipOverview, TimelineMeta, TimelineSnapshot } from '../api/types'
import { AudioWaveform } from './AudioWaveform'
import { ClipSyncedAudio } from './ClipSyncedAudio'
import { ClipPreviewVideo, type PreviewContext } from './ClipPreviewVideo'
import { TimelineMinimap } from './TimelineMinimap'
import { TimelineScrubber } from './TimelineScrubber'
import { useTimelineKeyboard } from '../hooks/useTimelineKeyboard'
import { buildSnapPoints, snapToNearest } from '../utils/timeline'

export type ClipTimelineState = {
  clip: ClipOverview
  meta: TimelineMeta
  cursorNs: number
  snapshot: TimelineSnapshot | null
  /** Clip-centric HMI: no frame composite; similar-search uses clip embedding elsewhere. */
  previewCompositeId: string | null
  /** Mirrors meta.preview — whether baked bbox MP4s are available. */
  hasBboxPreview: boolean
}

type ClipTimelinePanelProps = {
  clipId: string
  runId: string
  initialTimestampNs?: number
  /** Put preview above timeline controls (review workbench). */
  camerasFirst?: boolean
  /** browse = 总览；review = 校核 */
  previewContext?: PreviewContext
  onClipReady?: (clip: ClipOverview) => void
  onTimelineStateChange?: (state: ClipTimelineState) => void
  selectedBoxKey?: string | null
  onSelectedBoxChange?: (key: string | null) => void
  onOverlaySaved?: () => void
  /** When set, show only that camera (0-based). */
  cameraIndex?: number
  cursorNs?: number
  onCursorNsChange?: (ns: number) => void
}

function resolveInitialCursorNs(
  clip: ClipOverview,
  meta: TimelineMeta,
  initialTimestampNs?: number,
): number {
  if (initialTimestampNs != null && Number.isFinite(initialTimestampNs)) {
    return initialTimestampNs
  }
  if (meta.events.length > 0) {
    return meta.events[0].timestamp_ns
  }
  return clip.start_time_ns
}

export function ClipTimelinePanel({
  clipId,
  runId,
  initialTimestampNs,
  camerasFirst = false,
  previewContext = 'browse',
  onClipReady,
  onTimelineStateChange,
  selectedBoxKey,
  onSelectedBoxChange,
  onOverlaySaved,
  cameraIndex,
  cursorNs: cursorNsProp,
  onCursorNsChange,
}: ClipTimelinePanelProps) {
  const [clip, setClip] = useState<ClipOverview | null>(null)
  const [meta, setMeta] = useState<TimelineMeta | null>(null)
  const [cursorNs, setCursorNs] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [playing, setPlaying] = useState(false)
  const [rangeStartNs, setRangeStartNs] = useState<number | null>(null)
  const [rangeEndNs, setRangeEndNs] = useState<number | null>(null)
  const displayCursorNs = cursorNsProp ?? cursorNs
  const pushCursor = (ns: number) => {
    setCursorNs(ns)
    onCursorNsChange?.(ns)
  }

  useEffect(() => {
    if (!clipId || !runId) return
    setLoading(true)
    api
      .getExplorerBootstrap(clipId, runId)
      .then(({ clip: c, meta: m }) => {
        setClip(c)
        setMeta(m)
        setCursorNs(resolveInitialCursorNs(c, m, initialTimestampNs))
        onClipReady?.(c)
      })
      .catch(() => {
        setClip(null)
        setMeta(null)
      })
      .finally(() => setLoading(false))
  }, [clipId, runId, initialTimestampNs, onClipReady])

  const mp4Preview = meta?.preview?.mode === 'mp4' ? meta.preview : null

  const clipAudioUrl = useMemo(() => {
    for (const seg of meta?.asr_segments ?? []) {
      if (seg.audio_url) return seg.audio_url
    }
    return undefined
  }, [meta?.asr_segments])

  const snapPoints = useMemo(
    () => (meta ? buildSnapPoints([], meta.events, meta.asr_segments) : []),
    [meta],
  )

  const snapped = useMemo(() => {
    if (displayCursorNs == null || snapPoints.length === 0) return false
    return snapToNearest(displayCursorNs, snapPoints) === displayCursorNs
  }, [displayCursorNs, snapPoints])

  useTimelineKeyboard({
    enabled: displayCursorNs != null && !!clip,
    cursorNs: displayCursorNs ?? 0,
    startNs: clip?.start_time_ns ?? 0,
    endNs: clip?.end_time_ns ?? 0,
    snapPoints,
    onCursorChange: pushCursor,
    playing,
    onPlayingChange: setPlaying,
  })

  const clipLabel = meta?.clip_label ?? null

  useEffect(() => {
    if (!onTimelineStateChange || !clip || !meta || displayCursorNs == null) return
    const preview = meta.preview?.mode === 'mp4' ? meta.preview : null
    const hasBboxPreview = Boolean(
      preview?.has_bbox_preview ||
        preview?.cameras?.some((c) => Boolean(c.bbox_url)),
    )
    onTimelineStateChange({
      clip,
      meta,
      cursorNs: displayCursorNs,
      snapshot: null,
      previewCompositeId: null,
      hasBboxPreview,
    })
  }, [clip, meta, displayCursorNs, onTimelineStateChange])

  const filteredEvents = useMemo(() => {
    const events = meta?.events ?? []
    if (rangeStartNs == null || rangeEndNs == null) return events
    return events.filter((e) => e.timestamp_ns >= rangeStartNs && e.timestamp_ns <= rangeEndNs)
  }, [meta?.events, rangeStartNs, rangeEndNs])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }} data-testid="clip-timeline-panel-loading">
        <Spin tip="加载 Clip 预览…" />
      </div>
    )
  }

  if (!clip || displayCursorNs == null || !meta) {
    return (
      <Empty
        description="无法加载 Clip 预览，请确认管线已完成或稍后重试"
        data-testid="clip-timeline-panel-empty"
      />
    )
  }

  const previewCameras =
    cameraIndex == null
      ? mp4Preview?.cameras
      : (mp4Preview?.cameras || []).filter((_, i) => i === cameraIndex)

  const previewBlock = mp4Preview ? (
    <div className="clip-preview-stage">
      <ClipPreviewVideo
        clipId={clipId}
        runId={runId}
        previewContext={previewContext}
        gridUrl={cameraIndex == null ? mp4Preview.grid_url : ''}
        cameras={previewCameras}
        hasBboxPreview={Boolean(
          mp4Preview.has_bbox_preview ||
            previewCameras?.some((c) => Boolean(c.bbox_url)),
        )}
        hasPlainPreview={
          typeof mp4Preview.has_plain_preview === 'boolean'
            ? mp4Preview.has_plain_preview
            : undefined
        }
        startNs={clip.start_time_ns}
        endNs={clip.end_time_ns}
        cursorNs={displayCursorNs}
        playing={playing}
        fps={mp4Preview.fps}
        onCursorChange={pushCursor}
        onPlayingChange={setPlaying}
        height={camerasFirst ? 520 : 480}
        selectedBoxKey={selectedBoxKey}
        onSelectedBoxChange={onSelectedBoxChange}
        onOverlaySaved={onOverlaySaved}
      />
      {clipAudioUrl ? (
        <ClipSyncedAudio
          audioUrl={clipAudioUrl}
          startNs={clip.start_time_ns}
          endNs={clip.end_time_ns}
          cursorNs={displayCursorNs}
          playing={playing}
        />
      ) : null}
    </div>
  ) : (
    <Alert
      type="warning"
      showIcon
      message="无 MP4 预览"
      description="校核以 Clip 为单位，请用 scripts/import_real_data_clips.py --preview-mode mp4 重新导入以生成本地预览视频。"
    />
  )

  const timelineControls = (
    <>
      <TimelineMinimap
        startNs={clip.start_time_ns}
        endNs={clip.end_time_ns}
        cursorNs={displayCursorNs}
        sampledTimestamps={[]}
        events={meta.events}
        asrSegments={meta.asr_segments}
        rangeStartNs={rangeStartNs}
        rangeEndNs={rangeEndNs}
        onCursorChange={pushCursor}
        onRangeChange={(s, e) => {
          setRangeStartNs(s)
          setRangeEndNs(e)
        }}
      />

      <TimelineScrubber
        startNs={clip.start_time_ns}
        endNs={clip.end_time_ns}
        valueNs={displayCursorNs}
        onChange={pushCursor}
        snapPoints={snapPoints}
        snapped={snapped}
      />

      <AudioWaveform
        startNs={clip.start_time_ns}
        endNs={clip.end_time_ns}
        cursorNs={displayCursorNs}
        playing={playing}
        onCursorChange={pushCursor}
        onPlayingChange={setPlaying}
        externalPlayback={!!mp4Preview}
      />
    </>
  )

  const footerMeta = (
    <>
      {filteredEvents.length > 0 && (
        <Space wrap aria-label="事件跳转">
          {filteredEvents.map((e, i) => (
            <Tag
              key={i}
              color="orange"
              style={{ cursor: 'pointer' }}
              onClick={() => pushCursor(e.timestamp_ns)}
            >
              {e.parsed_label} @ {api.formatTimestampNs(e.timestamp_ns, clip.start_time_ns)}
            </Tag>
          ))}
        </Space>
      )}

      {clip.asr_segment_count > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          <AudioOutlined /> ASR {clip.asr_segment_count} 段 · 时长 {clip.duration_sec.toFixed(1)}s
        </Typography.Text>
      )}
    </>
  )

  return (
    <div
      className={`clip-timeline-panel${camerasFirst ? ' clip-timeline-panel--cameras-first' : ''}`}
      data-testid="clip-timeline-panel"
    >
      {!camerasFirst ? (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          <ClockCircleOutlined /> 以 Clip 为校核单位：MP4 四宫格浏览整段，时间轴仅用于定位 ASR/事件（无逐帧对齐）
        </Typography.Paragraph>
      ) : null}

      {!camerasFirst && clipLabel?.clip_label_ready && clipLabel.label_preview ? (
        <div className="review-sync-group-banner" style={{ marginBottom: 12 }}>
          <Space wrap style={{ marginBottom: 6 }}>
            <Tag color="purple">Clip 标签</Tag>
          </Space>
          <Typography.Paragraph style={{ margin: 0, fontSize: 13, color: 'var(--color-primary)' }}>
            {clipLabel.label_preview}
          </Typography.Paragraph>
        </div>
      ) : null}

      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {camerasFirst ? (
          <>
            {previewBlock}
            {timelineControls}
            {footerMeta}
          </>
        ) : (
          <>
            {timelineControls}
            {previewBlock}
            {footerMeta}
          </>
        )}
      </Space>
    </div>
  )
}
