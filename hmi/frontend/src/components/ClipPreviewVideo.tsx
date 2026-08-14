import { Button, message, Segmented, Space, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react'
import { api } from '../api'
import type { ClipBboxDetection } from '../api/types'
import { apiErrorMessage } from '../utils/apiError'
import { resolveMediaUrl } from '../utils/mediaUrl'
import { BBoxAttrEditor, buildDisplayLabel } from './BBoxAttrEditor'
import { BBoxOverlayLayer, boxesFromDetections, type EditableBox } from './BBoxOverlayLayer'

const CAMERA_SLOTS = ['camera0', 'camera1', 'camera2', 'camera3'] as const

export type ClipPreviewCamera = {
  camera: string
  url: string
  bbox_url?: string
}

export type PreviewVariant = 'plain' | 'bbox' | 'edit'
/** browse = 总览/Explorer 只看；review = 校核可编辑框 */
export type PreviewContext = 'browse' | 'review'

type FrameDraft = {
  camera: string
  topic: string
  timestamp_ns: number
  boxes: EditableBox[]
  dirty: boolean
  image_width?: number | null
  image_height?: number | null
}

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
  /** Controlled variant; when omitted, component manages toggle. */
  variant?: PreviewVariant
  onVariantChange?: (v: PreviewVariant) => void
  hasBboxPreview?: boolean
  /** False when only bbox MP4s exist (encode_plain off). */
  hasPlainPreview?: boolean
  /** browse: 原图/带识别框预览；review: 原图参考/带可编辑框 */
  previewContext?: PreviewContext
  /** Local jsonl overlay: browse=readonly on「带识别框」; review=editable on「带可编辑框」. */
  clipId?: string
  runId?: string
  overlayEnabled?: boolean
  selectedBoxKey?: string | null
  onSelectedBoxChange?: (key: string | null) => void
  onOverlaySaved?: () => void
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

function resolveCameraUrl(cam: ClipPreviewCamera, _variant: PreviewVariant): string {
  // Always prefer plain MP4; boxes come from jsonl overlay (browse readonly / review editable).
  if (cam.url) return cam.url
  return cam.bbox_url || ''
}

function boxKey(camera: string, timestamp_ns: number, index: number): string {
  return `${camera}:${timestamp_ns}:${index}`
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
  hasBboxPreview: _hasBboxPreview,
  hasPlainPreview,
  previewContext = 'browse',
  clipId,
  runId,
  overlayEnabled = true,
  selectedBoxKey,
  onSelectedBoxChange,
  onOverlaySaved,
}: ClipPreviewVideoProps) {
  const durationSec = Math.max(0.001, (endNs - startNs) / 1e9)
  const multiRefs = useRef<(HTMLVideoElement | null)[]>([])
  const singleRef = useRef<HTMLVideoElement>(null)
  const singleScrubbingRef = useRef(false)
  const [, bumpVideoEl] = useState(0)
  const isReview = previewContext === 'review'
  const canJsonlOverlay = Boolean(overlayEnabled && clipId && runId)

  const hasPlain =
    hasPlainPreview === true ||
    (hasPlainPreview !== false &&
      ((cameras ?? []).some((c) => Boolean(c.url) && c.url !== (c.bbox_url || '')) ||
        Boolean(gridUrl) ||
        (cameras ?? []).some((c) => Boolean(c.url))))

  // browse「带识别框」= plain + readonly jsonl；不再依赖烧录 MP4
  const browseBoxedOk = Boolean(!isReview && hasPlain && canJsonlOverlay)
  const reviewEditOk = Boolean(isReview && canJsonlOverlay && hasPlain)

  // browse: prefer 原图; review: prefer 带可编辑框（可直接调框）
  const defaultVariant: PreviewVariant = isReview
    ? reviewEditOk
      ? 'edit'
      : hasPlain
        ? 'plain'
        : 'edit'
    : hasPlain
      ? 'plain'
      : 'plain'
  const [internalVariant, setInternalVariant] = useState<PreviewVariant>(defaultVariant)
  const userPickedRef = useRef(false)

  const rawVariant: PreviewVariant = variantProp ?? internalVariant
  const variant: PreviewVariant = (() => {
    if (isReview) {
      if (rawVariant === 'bbox') return hasPlain ? 'plain' : 'edit'
      if (rawVariant === 'plain' && !hasPlain) return reviewEditOk ? 'edit' : 'plain'
      if (rawVariant === 'edit' && !reviewEditOk && hasPlain) return 'plain'
      return rawVariant === 'edit' || rawVariant === 'plain' ? rawVariant : 'plain'
    }
    if (rawVariant === 'edit') return 'plain'
    if (rawVariant === 'bbox' && !browseBoxedOk) return 'plain'
    if (rawVariant === 'plain' && !hasPlain && browseBoxedOk) return 'bbox'
    return rawVariant === 'bbox' || rawVariant === 'plain' ? rawVariant : 'plain'
  })()

  const setVariant = (v: PreviewVariant) => {
    if (isReview) {
      if (v === 'plain' && !hasPlain) return
      if (v === 'edit' && !reviewEditOk) return
    } else {
      if (v === 'plain' && !hasPlain) return
      if (v === 'bbox' && !browseBoxedOk) return
    }
    userPickedRef.current = true
    if (variantProp === undefined) setInternalVariant(v)
    onVariantChange?.(v)
  }

  useEffect(() => {
    if (variantProp !== undefined) return
    if (!isReview) {
      if (internalVariant === 'bbox' && !browseBoxedOk) {
        setInternalVariant('plain')
        return
      }
      if (!userPickedRef.current && hasPlain && internalVariant !== 'plain') {
        setInternalVariant('plain')
      }
      return
    }
    if (internalVariant === 'bbox') {
      setInternalVariant(hasPlain ? 'plain' : 'edit')
      return
    }
    if (internalVariant === 'edit' && !reviewEditOk && hasPlain) {
      setInternalVariant('plain')
    }
  }, [hasPlain, browseBoxedOk, reviewEditOk, internalVariant, variantProp, isReview])

  const cameraBySlot = useMemo(() => {
    const map = new Map<string, ClipPreviewCamera>()
    for (const c of cameras ?? []) {
      map.set(c.camera, c)
    }
    return map
  }, [cameras])

  const useMulti = (cameras?.length ?? 0) >= 2
  const [hasJsonl, setHasJsonl] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, FrameDraft>>({})
  const [saving, setSaving] = useState(false)
  const [activeCamera, setActiveCamera] = useState<string | null>(null)
  const [createMode, setCreateMode] = useState(false)
  const [editEnabled, setEditEnabled] = useState(false)
  const [internalSelectedKey, setInternalSelectedKey] = useState<string | null>(null)

  // browse「带识别框」= readonly jsonl；review「带可编辑框」= editable jsonl
  const overlayMode: 'off' | 'readonly' | 'edit' =
    !canJsonlOverlay
      ? 'off'
      : isReview && variant === 'edit'
        ? 'edit'
        : !isReview && variant === 'bbox'
          ? 'readonly'
          : 'off'
  const overlayActive = overlayMode !== 'off'
  const overlayEditable = overlayMode === 'edit'
  const dirtyAny = Object.values(drafts).some((d) => d.dirty)
  // Readonly: show as soon as tab active (empty frames ok). Edit: need jsonl or explicit start.
  const overlayVisible =
    overlayMode === 'readonly'
      ? overlayActive
      : overlayActive && (hasJsonl || editEnabled)

  // Review page often omits selection props — keep uncontrolled selection so resize/delete work.
  const effectiveSelectedKey =
    selectedBoxKey !== undefined ? selectedBoxKey : internalSelectedKey
  const setSelectedKey = useCallback(
    (key: string | null) => {
      if (selectedBoxKey === undefined) setInternalSelectedKey(key)
      onSelectedBoxChange?.(key)
    },
    [selectedBoxKey, onSelectedBoxChange],
  )

  // Clear edit chrome when leaving edit tab
  useEffect(() => {
    if (overlayMode !== 'edit') {
      setCreateMode(false)
      setEditEnabled(false)
      if (selectedBoxKey === undefined) setInternalSelectedKey(null)
    }
  }, [overlayMode, selectedBoxKey])


  // Throttled fetch of bbox frames at playhead
  useEffect(() => {
    if (!overlayActive || !clipId || !runId) return
    let cancelled = false
    const delay = playing ? 120 : 0
    const timer = window.setTimeout(() => {
      void api
        .getClipBboxes(clipId, runId, { timestamp_ns: cursorNs, window_ms: 200 })
        .then((res) => {
          if (cancelled) return
          const exists = Boolean(res.has_bboxes)
          setHasJsonl(exists)
          if (exists && overlayMode === 'edit') setEditEnabled(true)
          setDrafts((prev) => {
            const next: Record<string, FrameDraft> = { ...prev }
            const seen = new Set<string>()
            for (const fr of res.frames_at_cursor ?? []) {
              const cam = fr.camera
              seen.add(cam)
              const existing = prev[cam]
              if (existing?.dirty) continue
              next[cam] = {
                camera: cam,
                topic: fr.topic,
                timestamp_ns: fr.timestamp_ns,
                boxes: boxesFromDetections(fr.boxes as ClipBboxDetection[]),
                dirty: false,
                image_width: fr.image_width ?? null,
                image_height: fr.image_height ?? null,
              }
            }
            for (const key of Object.keys(next)) {
              if (!seen.has(key) && !next[key].dirty) delete next[key]
            }
            return next
          })
        })
        .catch(() => {
          if (!cancelled) setHasJsonl(false)
        })
    }, delay)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [overlayActive, overlayMode, clipId, runId, cursorNs, playing])

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

  const selectedParsed = useMemo(() => {
    if (!effectiveSelectedKey) return null
    const [camera, ts, idx] = effectiveSelectedKey.split(':')
    return { camera, timestamp_ns: Number(ts), index: Number(idx) }
  }, [effectiveSelectedKey])

  const updateBoxes = (camera: string, boxes: EditableBox[]) => {
    setDrafts((prev) => {
      const cur = prev[camera]
      if (!cur) return prev
      return { ...prev, [camera]: { ...cur, boxes, dirty: true } }
    })
    setActiveCamera(camera)
  }

  const handleSave = async () => {
    if (!clipId || !runId) return
    const dirty = Object.values(drafts).filter((d) => d.dirty)
    if (!dirty.length) return
    setSaving(true)
    try {
      for (const fr of dirty) {
        await api.putClipBboxes(clipId, runId, {
          mode: 'upsert_frame',
          frame: {
            camera: fr.camera,
            topic: fr.topic,
            timestamp_ns: fr.timestamp_ns,
            boxes: fr.boxes.map(({ display_label: _d, ...rest }) => rest),
          },
        })
      }
      setDrafts((prev) => {
        const next = { ...prev }
        for (const fr of dirty) {
          if (next[fr.camera]) next[fr.camera] = { ...next[fr.camera], dirty: false }
        }
        return next
      })
      message.success('BBox 已写回 bboxes.jsonl')
      onOverlaySaved?.()
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '保存 BBox 失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleDiscard = () => {
    setDrafts((prev) => {
      const next = { ...prev }
      for (const cam of Object.keys(next)) {
        if (next[cam].dirty) delete next[cam]
      }
      return next
    })
    // Refetch by bumping via cursor dependency: force clear then effect reloads
    if (clipId && runId) {
      void api.getClipBboxes(clipId, runId, { timestamp_ns: cursorNs, window_ms: 200 }).then((res) => {
        setHasJsonl(Boolean(res.has_bboxes))
        const rebuilt: Record<string, FrameDraft> = {}
        for (const fr of res.frames_at_cursor ?? []) {
          rebuilt[fr.camera] = {
            camera: fr.camera,
            topic: fr.topic,
            timestamp_ns: fr.timestamp_ns,
            boxes: boxesFromDetections(fr.boxes as ClipBboxDetection[]),
            dirty: false,
            image_width: (fr as { image_width?: number }).image_width ?? null,
            image_height: (fr as { image_height?: number }).image_height ?? null,
          }
        }
        setDrafts(rebuilt)
      })
    }
  }

  const majorityElement = (boxes: EditableBox[]) => {
    const counts = new Map<string, number>()
    for (const b of boxes) {
      const el = b.element || 'face'
      counts.set(el, (counts.get(el) || 0) + 1)
    }
    let best = 'face'
    let n = 0
    for (const [k, v] of counts) {
      if (v > n) {
        best = k
        n = v
      }
    }
    return best
  }

  const selectedBox: EditableBox | null = useMemo(() => {
    if (!selectedParsed) return null
    const draft = drafts[selectedParsed.camera]
    if (!draft) return null
    return draft.boxes[selectedParsed.index] ?? null
  }, [selectedParsed, drafts])

  const patchSelectedBox = (patch: Partial<EditableBox>) => {
    if (!selectedParsed) return
    const cam = selectedParsed.camera
    const draft = drafts[cam]
    if (!draft) return
    const next = draft.boxes.map((b, i) => {
      if (i !== selectedParsed.index) return b
      const merged = { ...b, ...patch }
      return { ...merged, display_label: buildDisplayLabel(merged) }
    })
    updateBoxes(cam, next)
  }

  const deleteSelectedBox = () => {
    if (!selectedParsed) return
    const cam = selectedParsed.camera
    const draft = drafts[cam]
    if (!draft) return
    const next = draft.boxes.filter((_, i) => i !== selectedParsed.index)
    updateBoxes(cam, next)
    if (next.length === 0) {
      setSelectedKey(null)
    } else {
      const idx = Math.min(selectedParsed.index, next.length - 1)
      setSelectedKey(boxKey(cam, draft.timestamp_ns, idx))
    }
  }

  const ensureDraftShell = (camera: string) => {
    if (overlayMode !== 'edit') return
    setDrafts((prev) => {
      if (prev[camera]) return prev
      return {
        ...prev,
        [camera]: {
          camera,
          topic: `/${camera}/image_raw/compressed`,
          timestamp_ns: cursorNs,
          boxes: [],
          dirty: false,
        },
      }
    })
  }

  const startCreateOnCamera = (camera?: string | null) => {
    if (overlayMode !== 'edit') return
    if (playing) {
      onPlayingChange?.(false)
    }
    const cam =
      camera ||
      activeCamera ||
      selectedParsed?.camera ||
      (cameras ?? [])[0]?.camera ||
      'camera0'
    setActiveCamera(cam)
    setEditEnabled(true)
    ensureDraftShell(cam)
    setCreateMode(true)
    setSelectedKey(null)
    message.info(`在 ${cam} 画面上拖拽绘制新框`)
  }

  const renderOverlay = (camera: string, videoEl: HTMLVideoElement | null) => {
    if (!overlayVisible) return null
    const draft = drafts[camera]
    const boxes = draft?.boxes ?? []
    const ts = draft?.timestamp_ns ?? cursorNs
    const sel =
      selectedParsed && selectedParsed.camera === camera ? selectedParsed.index : null
    return (
      <BBoxOverlayLayer
        videoEl={videoEl}
        boxes={boxes}
        imageWidth={draft?.image_width}
        imageHeight={draft?.image_height}
        editable={overlayEditable && !playing}
        createMode={
          overlayEditable && createMode && (activeCamera == null || activeCamera === camera)
        }
        selectedIndex={sel}
        defaultElement={majorityElement(boxes)}
        onCreateModeConsumed={() => setCreateMode(false)}
        onSelect={(index) => {
          setActiveCamera(camera)
          if (overlayEditable) setCreateMode(false)
          if (draft && Math.abs(cursorNs - draft.timestamp_ns) > 1_000_000) {
            onCursorChange(draft.timestamp_ns)
          }
          if (index == null) setSelectedKey(null)
          else setSelectedKey(boxKey(camera, ts, index))
        }}
        onBoxesChange={(next) => {
          if (!overlayEditable) return
          if (!draft) {
            setDrafts((prev) => ({
              ...prev,
              [camera]: {
                camera,
                topic: `/${camera}/image_raw/compressed`,
                timestamp_ns: cursorNs,
                boxes: next,
                dirty: true,
              },
            }))
          } else {
            updateBoxes(camera, next)
          }
          // Auto-select last box after create
          if (next.length > boxes.length) {
            setSelectedKey(boxKey(camera, draft?.timestamp_ns ?? cursorNs, next.length - 1))
          }
        }}
      />
    )
  }

  const editToolbar =
    overlayEditable ? (
      <div className="bbox-edit-panel" data-testid="bbox-edit-panel" style={{ marginBottom: 8 }}>
        <Space wrap size={8} style={{ marginBottom: 8 }}>
          {!editEnabled && !hasJsonl ? (
            <Button
              size="small"
              type="primary"
              onClick={() => {
                setEditEnabled(true)
                startCreateOnCamera(null)
              }}
              data-testid="bbox-start-edit"
            >
              开始编辑框
            </Button>
          ) : (
            <>
              <Button
                size="small"
                type={createMode ? 'primary' : 'default'}
                icon={<PlusOutlined />}
                disabled={playing}
                onClick={() => startCreateOnCamera(null)}
                data-testid="bbox-btn-create"
              >
                新建框
              </Button>
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                disabled={playing || !selectedBox}
                onClick={deleteSelectedBox}
                data-testid="bbox-btn-delete"
              >
                删除选中
              </Button>
              <Button
                size="small"
                type="primary"
                icon={<SaveOutlined />}
                loading={saving}
                disabled={!dirtyAny}
                onClick={() => void handleSave()}
                data-testid="bbox-btn-save"
              >
                保存本帧
              </Button>
              <Button size="small" disabled={saving || !dirtyAny} onClick={handleDiscard}>
                丢弃修改
              </Button>
            </>
          )}
          {createMode ? (
            <Typography.Text type="warning" style={{ fontSize: 12 }}>
              新建模式：在画面上按住拖拽画出框
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              暂停后：拖动框/角点调大小；点选后可改识别内容
            </Typography.Text>
          )}
          {activeCamera && drafts[activeCamera] ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {activeCamera} · 帧 ts={drafts[activeCamera].timestamp_ns}
              {dirtyAny ? ' · 未保存' : ''}
            </Typography.Text>
          ) : null}
        </Space>
        <BBoxAttrEditor
          box={selectedBox}
          camera={selectedParsed?.camera}
          frameTs={
            selectedParsed ? drafts[selectedParsed.camera]?.timestamp_ns ?? null : null
          }
          disabled={playing}
          onChange={patchSelectedBox}
        />
      </div>
    ) : null

  const tabOptions = isReview
    ? [
        { label: '原图参考', value: 'plain' as const, disabled: !hasPlain },
        { label: '带可编辑框', value: 'edit' as const, disabled: !reviewEditOk },
      ]
    : [
        { label: '原图预览', value: 'plain' as const, disabled: !hasPlain },
        { label: '带识别框预览', value: 'bbox' as const, disabled: !browseBoxedOk },
      ]

  const showTabs = isReview ? hasPlain || reviewEditOk : hasPlain || browseBoxedOk

  const toggleBar = (
    <Space direction="vertical" size={4} style={{ marginBottom: 8 }} data-testid="preview-variant-toggle">
      {showTabs ? (
        <Space size={8} wrap>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            预览
          </Typography.Text>
          <Segmented
            size="small"
            value={variant === 'bbox' || variant === 'edit' || variant === 'plain' ? variant : 'plain'}
            onChange={(v) => setVariant(v as PreviewVariant)}
            options={tabOptions}
          />
        </Space>
      ) : null}
      {!isReview && variant === 'bbox' ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }} data-testid="bbox-preview-hint">
          带识别框预览为 bboxes.jsonl 只读叠加，与校核写回一致；不可编辑。
        </Typography.Text>
      ) : null}
      {isReview && variant === 'plain' ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          原图参考：无叠加框。切换到「带可编辑框」进行新建/删除/调整与识别内容编辑。
        </Typography.Text>
      ) : null}
      {editToolbar}
    </Space>
  )

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
                <div
                  className="clip-camera-tile__media"
                  onMouseEnter={() => {
                    if (overlayEditable) ensureDraftShell(slot)
                  }}
                >
                  <video
                    {...bindVideo(index)}
                    src={resolveMediaUrl(src)}
                    className="clip-camera-tile__video"
                    playsInline
                    preload="metadata"
                    muted
                    onLoadedMetadata={() => bumpVideoEl((n) => n + 1)}
                  />
                  {overlayActive ? renderOverlay(slot, multiRefs.current[index]) : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const singleCam =
    (cameras ?? []).find((c) => c.url)?.camera ||
    (cameras ?? []).find((c) => c.bbox_url)?.camera ||
    'camera0'
  const singleSrc =
    gridUrl ||
    (cameras ?? []).find((c) => c.url)?.url ||
    (cameras ?? []).find((c) => c.bbox_url)?.bbox_url ||
    ''

  return (
    <div>
      {toggleBar}
      <div
        className="clip-camera-tile__media"
        onMouseEnter={() => {
          if (overlayEditable) ensureDraftShell(singleCam)
        }}
      >
        <video
          key={`${variant}-${singleSrc}`}
          ref={singleRef}
          src={resolveMediaUrl(singleSrc)}
          className="clip-preview-video"
          playsInline
          preload="metadata"
          onLoadedMetadata={() => bumpVideoEl((n) => n + 1)}
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
        {overlayActive ? renderOverlay(singleCam, singleRef.current) : null}
      </div>
    </div>
  )
}
