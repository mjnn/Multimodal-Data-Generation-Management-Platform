import { useCallback, useEffect, useMemo, useRef, type MutableRefObject } from 'react'
import { resolveMediaUrl } from '../utils/mediaUrl'

const CAMERA_SLOTS = ['camera0', 'camera1', 'camera2', 'camera3'] as const

export type ClipPreviewCamera = {
  camera: string
  url: string
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
}: ClipPreviewVideoProps) {
  const durationSec = Math.max(0.001, (endNs - startNs) / 1e9)
  const multiRefs = useRef<(HTMLVideoElement | null)[]>([])
  const singleRef = useRef<HTMLVideoElement>(null)
  const singleScrubbingRef = useRef(false)

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
      <div
        className={gridClass}
        aria-label={`${cameras?.length ?? 0} 路摄像头同步预览 ${fps}fps`}
      >
        {activeSlots.map((slot) => {
          const cam = cameraBySlot.get(slot)!
          const index = CAMERA_SLOTS.indexOf(slot)
          return (
            <div key={slot} className="clip-camera-tile">
              <div className="clip-camera-tile__label">{slot}</div>
              <div className="clip-camera-tile__media">
                <video
                  {...bindVideo(index)}
                  src={resolveMediaUrl(cam.url)}
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
    )
  }

  return (
    <div className="clip-camera-tile__media">
      <video
        ref={singleRef}
        src={resolveMediaUrl(gridUrl)}
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
        aria-label={`预览 ${fps}fps`}
      />
    </div>
  )
}
