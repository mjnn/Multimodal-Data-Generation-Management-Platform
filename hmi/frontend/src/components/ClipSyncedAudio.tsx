import { useEffect, useRef } from 'react'
import { resolveMediaUrl } from '../utils/mediaUrl'

type ClipSyncedAudioProps = {
  audioUrl: string
  startNs: number
  endNs: number
  cursorNs: number
  playing: boolean
  /** Elapsed seconds in the audio file (startNs maps to 0). */
  onClock?: (elapsedSec: number) => void
  onEnded?: () => void
}

export function ClipSyncedAudio({
  audioUrl,
  startNs,
  endNs,
  cursorNs,
  playing,
  onClock,
  onEnded,
}: ClipSyncedAudioProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const scrubbingRef = useRef(false)
  const durationSec = Math.max(0.001, (endNs - startNs) / 1e9)

  useEffect(() => {
    const a = audioRef.current
    if (!a || scrubbingRef.current) return
    const t = Math.min(durationSec, Math.max(0, (cursorNs - startNs) / 1e9))
    if (Math.abs(a.currentTime - t) > 0.08) {
      a.currentTime = t
    }
  }, [cursorNs, startNs, durationSec])

  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    if (playing) {
      void a.play().catch(() => {
        /* autoplay policy or missing file */
      })
    } else {
      a.pause()
    }
  }, [playing])

  return (
    <audio
      ref={audioRef}
      src={resolveMediaUrl(audioUrl)}
      preload="auto"
      className="clip-synced-audio"
      aria-hidden
      onSeeking={() => {
        scrubbingRef.current = true
      }}
      onSeeked={() => {
        scrubbingRef.current = false
      }}
      onTimeUpdate={(e) => {
        if (!playing) return
        const elapsed = Math.min(durationSec, Math.max(0, e.currentTarget.currentTime))
        onClock?.(elapsed)
      }}
      onEnded={() => {
        onClock?.(durationSec)
        onEnded?.()
      }}
    />
  )
}
