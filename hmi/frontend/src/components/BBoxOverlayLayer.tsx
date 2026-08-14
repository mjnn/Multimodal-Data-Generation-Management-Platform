import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { ClipBboxDetection } from '../api/types'
import {
  canvasBoxToNative,
  computeLongEdgeFit,
  nativeBoxToCanvas,
  type LongEdgeFit,
} from '../utils/bboxCoords'

export type EditableBox = {
  x1: number
  y1: number
  x2: number
  y2: number
  element: string
  score?: number | null
  class_id?: number | null
  gender?: string | null
  age_range?: string | null
  age_approx?: number | null
  gender_score?: number | null
  age_score?: number | null
  display_label?: string
}

type Letterbox = {
  scale: number
  offsetX: number
  offsetY: number
  videoW: number
  videoH: number
  clientW: number
  clientH: number
  ready: boolean
}

function computeLetterbox(video: HTMLVideoElement | null): Letterbox {
  if (!video || !video.videoWidth || !video.videoHeight) {
    return {
      scale: 1,
      offsetX: 0,
      offsetY: 0,
      videoW: 0,
      videoH: 0,
      clientW: 0,
      clientH: 0,
      ready: false,
    }
  }
  const vw = video.videoWidth
  const vh = video.videoHeight
  const cw = video.clientWidth
  const ch = video.clientHeight
  const scale = Math.min(cw / vw, ch / vh)
  const dispW = vw * scale
  const dispH = vh * scale
  return {
    scale,
    offsetX: (cw - dispW) / 2,
    offsetY: (ch - dispH) / 2,
    videoW: vw,
    videoH: vh,
    clientW: cw,
    clientH: ch,
    ready: true,
  }
}

function canvasToClient(
  box: { x1: number; y1: number; x2: number; y2: number },
  lb: Letterbox,
) {
  return {
    x: lb.offsetX + box.x1 * lb.scale,
    y: lb.offsetY + box.y1 * lb.scale,
    w: Math.max(1, (box.x2 - box.x1) * lb.scale),
    h: Math.max(1, (box.y2 - box.y1) * lb.scale),
  }
}

function clampCanvasBox(
  b: { x1: number; y1: number; x2: number; y2: number },
  vw: number,
  vh: number,
) {
  let x1 = Math.min(b.x1, b.x2)
  let x2 = Math.max(b.x1, b.x2)
  let y1 = Math.min(b.y1, b.y2)
  let y2 = Math.max(b.y1, b.y2)
  x1 = Math.max(0, Math.min(vw, x1))
  x2 = Math.max(0, Math.min(vw, x2))
  y1 = Math.max(0, Math.min(vh, y1))
  y2 = Math.max(0, Math.min(vh, y2))
  if (x2 - x1 < 2) x2 = Math.min(vw, x1 + 2)
  if (y2 - y1 < 2) y2 = Math.min(vh, y1 + 2)
  return { x1, y1, x2, y2 }
}

type DragMode =
  | { kind: 'move'; index: number; startX: number; startY: number; origCanvas: { x1: number; y1: number; x2: number; y2: number } }
  | {
      kind: 'resize'
      index: number
      corner: 'nw' | 'ne' | 'sw' | 'se'
      startX: number
      startY: number
      origCanvas: { x1: number; y1: number; x2: number; y2: number }
    }
  | { kind: 'create'; startX: number; startY: number; curX: number; curY: number }

type Props = {
  videoEl: HTMLVideoElement | null
  /** Boxes in native frame pixel space (bboxes.jsonl). */
  boxes: EditableBox[]
  /** Native frame size; when missing, treat boxes as already in video canvas space. */
  imageWidth?: number | null
  imageHeight?: number | null
  editable: boolean
  /** When true, drag on empty area creates a box (single press); otherwise double-click. */
  createMode?: boolean
  selectedIndex: number | null
  onSelect: (index: number | null) => void
  onBoxesChange: (boxes: EditableBox[]) => void
  defaultElement?: string
  onCreateModeConsumed?: () => void
}

export function boxesFromDetections(dets: ClipBboxDetection[]): EditableBox[] {
  return dets.map((d) => ({
    x1: d.x1,
    y1: d.y1,
    x2: d.x2,
    y2: d.y2,
    element: d.element || 'element',
    score: d.score,
    class_id: d.class_id,
    gender: d.gender,
    age_range: d.age_range,
    age_approx: d.age_approx,
    gender_score: d.gender_score,
    age_score: d.age_score,
    display_label: d.display_label,
  }))
}

export function BBoxOverlayLayer({
  videoEl,
  boxes,
  imageWidth,
  imageHeight,
  editable,
  createMode = false,
  selectedIndex,
  onSelect,
  onBoxesChange,
  defaultElement = 'face',
  onCreateModeConsumed,
}: Props) {
  const [lb, setLb] = useState<Letterbox>(() => computeLetterbox(videoEl))
  const dragRef = useRef<DragMode | null>(null)
  const [draftCreate, setDraftCreate] = useState<{ x: number; y: number; w: number; h: number } | null>(
    null,
  )

  const fit: LongEdgeFit | null = useMemo(() => {
    if (!lb.ready) return null
    if (imageWidth && imageHeight && imageWidth > 0 && imageHeight > 0) {
      return computeLongEdgeFit(
        { width: imageWidth, height: imageHeight },
        { width: lb.videoW, height: lb.videoH },
      )
    }
    // Legacy / unknown: assume jsonl already in video canvas pixels
    return {
      scale: 1,
      cropLeft: 0,
      cropTop: 0,
      offsetX: 0,
      offsetY: 0,
      contentW: lb.videoW,
      contentH: lb.videoH,
      canvasW: lb.videoW,
      canvasH: lb.videoH,
      nativeW: lb.videoW,
      nativeH: lb.videoH,
    }
  }, [lb, imageWidth, imageHeight])

  const canvasBoxes = useMemo(() => {
    if (!fit) return []
    return boxes.map((b) => ({
      ...b,
      ...nativeBoxToCanvas(b, fit),
    }))
  }, [boxes, fit])

  const refreshLb = useCallback(() => {
    setLb(computeLetterbox(videoEl))
  }, [videoEl])

  useEffect(() => {
    refreshLb()
    if (!videoEl) return
    const onMeta = () => refreshLb()
    videoEl.addEventListener('loadedmetadata', onMeta)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => refreshLb()) : null
    ro?.observe(videoEl)
    window.addEventListener('resize', refreshLb)
    return () => {
      videoEl.removeEventListener('loadedmetadata', onMeta)
      ro?.disconnect()
      window.removeEventListener('resize', refreshLb)
    }
  }, [videoEl, refreshLb])

  useEffect(() => {
    if (!editable) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (selectedIndex == null || selectedIndex < 0 || selectedIndex >= boxes.length) return
      e.preventDefault()
      const next = boxes.filter((_, i) => i !== selectedIndex)
      onBoxesChange(next)
      onSelect(next.length ? Math.min(selectedIndex, next.length - 1) : null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editable, selectedIndex, boxes, onBoxesChange, onSelect])

  const clientToCanvas = useCallback(
    (clientX: number, clientY: number) => {
      if (!videoEl || !lb.ready) return null
      const rect = videoEl.getBoundingClientRect()
      const dx = clientX - rect.left
      const dy = clientY - rect.top
      return {
        x: (dx - lb.offsetX) / lb.scale,
        y: (dy - lb.offsetY) / lb.scale,
      }
    },
    [videoEl, lb],
  )

  const emitNativeBoxes = useCallback(
    (nextCanvas: Array<{ x1: number; y1: number; x2: number; y2: number }>, base: EditableBox[]) => {
      if (!fit) return
      const next = base.map((b, i) => {
        const c = nextCanvas[i] ?? nativeBoxToCanvas(b, fit)
        const n = canvasBoxToNative(c, fit)
        return { ...b, ...n }
      })
      onBoxesChange(next)
    },
    [fit, onBoxesChange],
  )

  const onPointerDownBg = (e: ReactPointerEvent) => {
    if (!editable || !lb.ready || !fit) return
    const startCreate = createMode || e.detail >= 2
    if (startCreate) {
      const pt = clientToCanvas(e.clientX, e.clientY)
      if (!pt) return
      e.currentTarget.setPointerCapture(e.pointerId)
      dragRef.current = { kind: 'create', startX: pt.x, startY: pt.y, curX: pt.x, curY: pt.y }
      setDraftCreate({ x: pt.x, y: pt.y, w: 0, h: 0 })
      onSelect(null)
      if (createMode) onCreateModeConsumed?.()
    } else {
      onSelect(null)
    }
  }

  const onPointerDownBox = (e: ReactPointerEvent, index: number) => {
    if (!editable || !lb.ready || !fit) {
      onSelect(index)
      return
    }
    e.stopPropagation()
    const pt = clientToCanvas(e.clientX, e.clientY)
    if (!pt) return
    onSelect(index)
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      kind: 'move',
      index,
      startX: pt.x,
      startY: pt.y,
      origCanvas: { ...nativeBoxToCanvas(boxes[index], fit) },
    }
  }

  const onPointerDownHandle = (
    e: ReactPointerEvent,
    index: number,
    corner: 'nw' | 'ne' | 'sw' | 'se',
  ) => {
    if (!editable || !lb.ready || !fit) return
    e.stopPropagation()
    const pt = clientToCanvas(e.clientX, e.clientY)
    if (!pt) return
    onSelect(index)
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      kind: 'resize',
      index,
      corner,
      startX: pt.x,
      startY: pt.y,
      origCanvas: { ...nativeBoxToCanvas(boxes[index], fit) },
    }
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    const drag = dragRef.current
    if (!drag || !lb.ready || !fit) return
    const pt = clientToCanvas(e.clientX, e.clientY)
    if (!pt) return
    if (drag.kind === 'create') {
      drag.curX = pt.x
      drag.curY = pt.y
      const x = Math.min(drag.startX, drag.curX)
      const y = Math.min(drag.startY, drag.curY)
      setDraftCreate({
        x,
        y,
        w: Math.abs(drag.curX - drag.startX),
        h: Math.abs(drag.curY - drag.startY),
      })
      return
    }
    const dx = pt.x - drag.startX
    const dy = pt.y - drag.startY
    const nextCanvas = canvasBoxes.map((b) => ({ x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 }))
    if (drag.kind === 'move') {
      const o = drag.origCanvas
      nextCanvas[drag.index] = clampCanvasBox(
        { x1: o.x1 + dx, y1: o.y1 + dy, x2: o.x2 + dx, y2: o.y2 + dy },
        lb.videoW,
        lb.videoH,
      )
    } else {
      const o = drag.origCanvas
      let { x1, y1, x2, y2 } = o
      if (drag.corner.includes('w')) x1 = o.x1 + dx
      if (drag.corner.includes('e')) x2 = o.x2 + dx
      if (drag.corner.includes('n')) y1 = o.y1 + dy
      if (drag.corner.includes('s')) y2 = o.y2 + dy
      nextCanvas[drag.index] = clampCanvasBox({ x1, y1, x2, y2 }, lb.videoW, lb.videoH)
    }
    emitNativeBoxes(nextCanvas, boxes)
  }

  const onPointerUp = () => {
    const drag = dragRef.current
    dragRef.current = null
    if (drag?.kind === 'create' && lb.ready && fit) {
      const x1 = Math.min(drag.startX, drag.curX)
      const y1 = Math.min(drag.startY, drag.curY)
      const x2 = Math.max(drag.startX, drag.curX)
      const y2 = Math.max(drag.startY, drag.curY)
      setDraftCreate(null)
      if (x2 - x1 >= 4 && y2 - y1 >= 4) {
        const canvas = clampCanvasBox({ x1, y1, x2, y2 }, lb.videoW, lb.videoH)
        const native = canvasBoxToNative(canvas, fit)
        const box: EditableBox = { ...native, element: defaultElement }
        const next = [...boxes, box]
        onBoxesChange(next)
        onSelect(next.length - 1)
      }
    }
  }

  if (!lb.ready || !fit) {
    return (
      <div className="bbox-overlay" data-testid="bbox-overlay" data-ready="0" aria-hidden />
    )
  }

  return (
    <svg
      className={createMode ? 'bbox-overlay bbox-overlay--create' : 'bbox-overlay'}
      data-testid="bbox-overlay"
      data-ready="1"
      data-editable={editable ? '1' : '0'}
      data-create-mode={createMode ? '1' : '0'}
      data-native-w={imageWidth ?? ''}
      data-native-h={imageHeight ?? ''}
      viewBox={`0 0 ${lb.clientW} ${lb.clientH}`}
      preserveAspectRatio="none"
      onPointerDown={onPointerDownBg}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
    >
      {canvasBoxes.map((box, index) => {
        const d = canvasToClient(box, lb)
        const selected = selectedIndex === index
        const label = box.display_label || box.element
        return (
          <g key={index} data-testid={`bbox-overlay-box-${index}`}>
            <rect
              x={d.x}
              y={d.y}
              width={d.w}
              height={d.h}
              className={
                selected ? 'bbox-overlay__rect bbox-overlay__rect--selected' : 'bbox-overlay__rect'
              }
              onPointerDown={(e) => onPointerDownBox(e, index)}
            />
            <text x={d.x + 2} y={Math.max(12, d.y - 4)} className="bbox-overlay__label">
              {label}
            </text>
            {editable && selected
              ? (['nw', 'ne', 'sw', 'se'] as const).map((corner) => {
                  const hx = corner.includes('w') ? d.x : d.x + d.w
                  const hy = corner.includes('n') ? d.y : d.y + d.h
                  return (
                    <rect
                      key={corner}
                      x={hx - 4}
                      y={hy - 4}
                      width={8}
                      height={8}
                      className="bbox-overlay__handle"
                      data-testid={`bbox-overlay-handle-${corner}`}
                      onPointerDown={(e) => onPointerDownHandle(e, index, corner)}
                    />
                  )
                })
              : null}
          </g>
        )
      })}
      {draftCreate
        ? (() => {
            const d = canvasToClient(
              {
                x1: draftCreate.x,
                y1: draftCreate.y,
                x2: draftCreate.x + draftCreate.w,
                y2: draftCreate.y + draftCreate.h,
              },
              lb,
            )
            return (
              <rect
                x={d.x}
                y={d.y}
                width={d.w}
                height={d.h}
                className="bbox-overlay__rect bbox-overlay__rect--draft"
              />
            )
          })()
        : null}
    </svg>
  )
}
