import { useEffect } from 'react'
import { nextSnapPoint, type SnapPoint } from '../utils/timeline'

interface Options {
  enabled: boolean
  cursorNs: number
  startNs: number
  endNs: number
  snapPoints: SnapPoint[]
  onCursorChange: (ns: number) => void
  playing: boolean
  onPlayingChange: (v: boolean) => void
}

export function useTimelineKeyboard({
  enabled,
  cursorNs,
  startNs,
  endNs,
  snapPoints,
  onCursorChange,
  playing,
  onPlayingChange,
}: Options) {
  useEffect(() => {
    if (!enabled) return

    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return

      if (e.code === 'Space') {
        e.preventDefault()
        onPlayingChange(!playing)
        return
      }

      const stepNs = e.shiftKey ? 0 : 100_000_000
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        if (e.shiftKey) {
          const prev = nextSnapPoint(snapPoints, cursorNs, -1)
          if (prev != null) onCursorChange(prev)
        } else {
          onCursorChange(Math.max(startNs, cursorNs - stepNs))
        }
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        if (e.shiftKey) {
          const next = nextSnapPoint(snapPoints, cursorNs, 1)
          if (next != null) onCursorChange(next)
        } else {
          onCursorChange(Math.min(endNs, cursorNs + stepNs))
        }
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    enabled,
    cursorNs,
    startNs,
    endNs,
    snapPoints,
    onCursorChange,
    playing,
    onPlayingChange,
  ])
}
