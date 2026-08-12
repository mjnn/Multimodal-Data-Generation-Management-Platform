import { Segmented, Space, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import { resolveMediaUrl } from '../utils/mediaUrl'

const CAMERA_SLOTS = ['camera0', 'camera1', 'camera2', 'camera3'] as const

export type ClipPreviewCamera = {
  camera: string
  url: string
  bbox_url?: string
}

export type PreviewVariant = 'plain' | 'bbox'

type ClipPreviewVideoProps = {
  gridUrl: string
  cameras?: ClipPreviewCamera[]
  startNs: number
  endNs: number
  cursorNs: number
  playing: boolean
  fps: number
  onCursorChange: (ns: number) => void
  onPlayingChange?: (playing: boolean) => void
  height?: number
  /** Controlled variant; when omitted, component manages toggle if any bbox_url exists. */
  variant?: PreviewVariant
  onVariantChange?: (v: PreviewVariant) => void
  hasBboxPreview?: boolean
  /** False when only bbox MP4s exist (encode_plain off). */
  hasPlainPreview?: boolean
}

function useSyncedClipVideos(
  videoRefs: MutableRefObject<(HTMLVideoElement | null)[]>,
  opts: {
    startNs: number
    durationSec: number
    cursorNs: number
    playing: boolean
    onCursorChange: (ns: number) => void
    onPlayingChange?: (playing: boolean) => void
  },
) {
  const scrubbingRef = useRef(false)
  const { startNs, durationSec, cursorNs, playing, onCursorChange, onPlayingChange } = opts

  const activeVideos = useCallback(
    () => videoRefs.current.filter((v): v is HTMLVideoElement => v != null),
    [videoRefs],
  )

  useEffect(() => {
    if (scrubbingRef.current) return
    const t = Math.min(durationSec, Math.max(0, (cursorNs - startNs) / 1e9))
    for (const v of activeVideos()) {
      if (Math.abs(v.currentTime - t) > 0.05) {
        v.currentTime = t
      }
    }
  }, [cursorNs, startNs, durationSec, activeVideos])

  useEffect(() => {
    const list = activeVideos()
    if (!list.length) return
    if (playing) {
      void Promise.all(list.map((v) => v.play())).catch(() => onPlayingChange?.(false))
    } else {
      list.forEach((v) => v.pause())
    }
  }, [playing, onPlayingChange, activeVideos])

  const handleTimeUpdate = useCallback(() => {
    if (scrubbingRef.current) return
    const lead = videoRefs.current.find((v) => v != null)
    if (!lead) return
    onCursorChange(startNs + Math.round(lead.currentTime * 1e9))
  }, [onCursorChange, startNs, videoRefs])

  const bindVideo = (index: number) => ({
    onTimeUpdate: handleTimeUpdate,
    onEnded: () => onPlayingChange?.(false),
    onSeeking: () => {
      scrubbingRef.current = true
    },
    onSeeked: () => {
      scrubbingRef.current = false
      handleTimeUpdate()
    },
    ref: (el: HTMLVideoElement | null) => {
      videoRefs.current[index] = el
    },
  })

  return { bindVideo }
}

function resolveCameraUrl(cam: ClipPreviewCamera, variant: PreviewVariant): string {
  if (variant === 'bbox' && cam.bbox_url) return cam.bbox_url
  if (cam.url) return cam.url
  return cam.bbox_url || ''
}

export function ClipPreviewVideo({
  gridUrl,
  cameras,
  startNs,
  endNs,
  cursorNs,
  playing,
  fps,
  onCursorChange,
  onPlayingChange,
  height: _maxPreviewHeight = 480,
  variant: variantProp,
  onVariantChange,
  hasBboxPreview,
  hasPlainPreview,
}: ClipPreviewVideoProps) {
  const durationSec = Math.max(0.001, (endNs - startNs) / 1e9)
  const multiRefs = useRef<(HTMLVideoElement | null)[]>([])
  const singleRef = useRef<HTMLVideoElement>(null)
  const singleScrubbingRef = useRef(false)

  const hasBbox =
    hasBboxPreview === true || (cameras ?? []).some((c) => Boolean(c.bbox_url))
  // Explicit false from API means encode_plain was off — do not fall back to grid.
  const hasPlain =
    hasPlainPreview === true ||
    (hasPlainPreview !== false &&
      ((cameras ?? []).some((c) => Boolean(c.url) && c.url !== (c.bbox_url || '')) ||
        (Boolean(gridUrl) && !hasBbox)))

  // Prefer BBox when available (detection preview); user can switch to 原图.
  const defaultVariant: PreviewVariant = hasBbox ? 'bbox' : 'plain'
  const [internalVariant, setInternalVariant] = useState<PreviewVariant>(defaultVariant)
  const userPickedRef = useRef(false)

  const showToggle = hasBbox

  const rawVariant: PreviewVariant = variantProp ?? internalVariant
  const variant: PreviewVariant =
    rawVariant === 'plain' && !hasPlain && hasBbox
      ? 'bbox'
      : rawVariant === 'bbox' && !hasBbox && hasPlain
        ? 'plain'
        : rawVariant

  const setVariant = (v: PreviewVariant) => {
    if (v === 'plain' && !hasPlain) return
    if (v === 'bbox' && !hasBbox) return
    userPickedRef.current = true
    if (variantProp === undefined) setInternalVariant(v)
    onVariantChange?.(v)
  }

  useEffect(() => {
    if (variantProp !== undefined) return
    if (internalVariant === 'plain' && !hasPlain && hasBbox) {
      setInternalVariant('bbox')
      return
    }
    // When bbox becomes available and user has not picked, default to BBox.
    if (!userPickedRef.current && hasBbox && internalVariant !== 'bbox') {
      setInternalVariant('bbox')
    }
  }, [hasPlain, hasBbox, internalVariant, variantProp])

  const cameraBySlot = useMemo(() => {
    const map = new Map<string, ClipPreviewCamera>()
    for (const c of cameras ?? []) {
      map.set(c.camera, c)
    }
    return map
  }, [cameras])

  const useMulti = (cameras?.length ?? 0) >= 2

  const { bindVideo } = useSyncedClipVideos(multiRefs, {
    startNs,
    durationSec,
    cursorNs,
    playing,
    onCursorChange,
    onPlayingChange,
  })

  useEffect(() => {
    if (useMulti) return
    const v = singleRef.current
    if (!v || singleScrubbingRef.current) return
    const t = Math.min(durationSec, Math.max(0, (cursorNs - startNs) / 1e9))
    if (Math.abs(v.currentTime - t) > 0.05) {
      v.currentTime = t
    }
  }, [cursorNs, startNs, durationSec, useMulti])

  useEffect(() => {
    if (useMulti) return
    const v = singleRef.current
    if (!v) return
    if (playing) {
      void v.play().catch(() => onPlayingChange?.(false))
    } else {
      v.pause()
    }
  }, [playing, onPlayingChange, useMulti])

  const handleSingleTimeUpdate = () => {
    const v = singleRef.current
    if (!v || singleScrubbingRef.current) return
    onCursorChange(startNs + Math.round(v.currentTime * 1e9))
  }

  const toggleBar = showToggle ? (
    <Space direction="vertical" size={4} style={{ marginBottom: 8 }} data-testid="preview-variant-toggle">
      <Space size={8}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          预览
        </Typography.Text>
        <Segmented
          size="small"
          value={variant}
          onChange={(v) => setVariant(v as PreviewVariant)}
          options={[
            { label: '原图', value: 'plain', disabled: !hasPlain },
            { label: '带框', value: 'bbox', disabled: !hasBbox },
          ]}
        />
      </Space>
      {variant === 'bbox' ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="bbox-preview-hint">
          带框为检测预览（辅助观察），不是 Taxonomy 字段校核对象。
        </Typography.Text>
      ) : null}
    </Space>
  ) : null

  if (useMulti) {
    const activeSlots = CAMERA_SLOTS.filter((slot) => cameraBySlot.has(slot))
    const gridClass =
      activeSlots.length === 1
        ? 'clip-explorer__cameras clip-explorer__cameras--n1'
        : activeSlots.length === 2
          ? 'clip-explorer__cameras clip-explorer__cameras--n2'
          : activeSlots.length === 3
            ? 'clip-explorer__cameras clip-explorer__cameras--n3'
            : 'clip-explorer__cameras clip-explorer__cameras--n4'

    return (
      <div>
        {toggleBar}
        <div
          className={gridClass}
          aria-label={`${cameras?.length ?? 0} 路摄像头同步预览 ${fps}fps (${variant})`}
        >
          {activeSlots.map((slot) => {
            const cam = cameraBySlot.get(slot)!
            const index = CAMERA_SLOTS.indexOf(slot)
            const src = resolveCameraUrl(cam, variant)
            return (
              <div key={`${slot}-${variant}`} className="clip-camera-tile">
                <div className="clip-camera-tile__label">{slot}</div>
                <div className="clip-camera-tile__media">
                  <video
                    {...bindVideo(index)}
                    src={resolveMediaUrl(src)}
                    className="clip-camera-tile__video"
                    playsInline
                    preload="metadata"
                    muted
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // Single / grid path: prefer first camera bbox when variant=bbox and available
  const singleSrc =
    variant === 'bbox'
      ? (cameras ?? []).find((c) => c.bbox_url)?.bbox_url || gridUrl
      : gridUrl || (cameras ?? []).find((c) => c.url)?.url || ''

  return (
    <div>
      {toggleBar}
      <div className="clip-camera-tile__media">
        <video
          key={`${variant}-${singleSrc}`}
          ref={singleRef}
          src={resolveMediaUrl(singleSrc)}
          className="clip-preview-video"
          playsInline
          preload="metadata"
          onTimeUpdate={handleSingleTimeUpdate}
          onEnded={() => onPlayingChange?.(false)}
          onSeeking={() => {
            singleScrubbingRef.current = true
          }}
          onSeeked={() => {
            singleScrubbingRef.current = false
            handleSingleTimeUpdate()
          }}
          aria-label={`预览 ${fps}fps (${variant})`}
        />
      </div>
    </div>
  )
}
