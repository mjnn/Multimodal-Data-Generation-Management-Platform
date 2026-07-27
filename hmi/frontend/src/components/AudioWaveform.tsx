import { PauseCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Space, Typography } from 'antd'
import { useEffect, useMemo, useRef } from 'react'
import { api } from '../api'

interface Props {
  startNs: number
  endNs: number
  cursorNs: number
  playing: boolean
  onCursorChange: (ns: number) => void
  onPlayingChange: (v: boolean) => void
  /** When true, playback position is driven by external video (no interval advance). */
  externalPlayback?: boolean
  /** When set, playback advances along these timestamps (legacy frame mode). */
  snapTimestampsNs?: number[]
}

function mockAmplitudes(count: number, seed: number): number[] {
  const out: number[] = []
  for (let i = 0; i < count; i++) {
    const x = Math.sin((i + seed) * 0.31) * 0.5 + Math.sin((i + seed) * 0.07) * 0.3
    out.push(Math.abs(x) + 0.08)
  }
  return out
}

export function AudioWaveform({
  startNs,
  endNs,
  cursorNs,
  playing,
  onCursorChange,
  onPlayingChange,
  externalPlayback = false,
  snapTimestampsNs,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const amps = useMemo(() => mockAmplitudes(240, startNs), [startNs])
  const duration = endNs - startNs

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)
    const barW = w / amps.length
    const cursorX = ((cursorNs - startNs) / duration) * w

    amps.forEach((a, i) => {
      const bh = a * (h * 0.8)
      const x = i * barW
      ctx.fillStyle = x < cursorX ? '#1677ff' : '#d9d9d9'
      ctx.fillRect(x + 1, (h - bh) / 2, Math.max(1, barW - 2), bh)
    })
    ctx.strokeStyle = '#722ed1'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(cursorX, 0)
    ctx.lineTo(cursorX, h)
    ctx.stroke()
  }, [amps, cursorNs, startNs, duration])

  useEffect(() => {
    if (!playing || externalPlayback) return
    const snaps = (snapTimestampsNs ?? [])
      .filter((t) => t >= startNs && t <= endNs)
      .sort((a, b) => a - b)
    if (snaps.length >= 2) {
      const spanMs = ((endNs - startNs) / 1_000_000) | 0
      const intervalMs = Math.min(66, Math.max(33, Math.round(spanMs / snaps.length)))
      const t = setInterval(() => {
        const next = snaps.find((s) => s > cursorNs)
        if (next == null) {
          onPlayingChange(false)
          return
        }
        onCursorChange(next)
      }, intervalMs)
      return () => clearInterval(t)
    }
    const t = setInterval(() => {
      const next = cursorNs + 100_000_000
      if (next >= endNs) {
        onPlayingChange(false)
        return
      }
      onCursorChange(next)
    }, 100)
    return () => clearInterval(t)
  }, [playing, externalPlayback, cursorNs, endNs, onCursorChange, onPlayingChange, snapTimestampsNs, startNs])

  const onClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    onCursorChange(startNs + ratio * duration)
  }

  return (
    <div>
      <Space style={{ marginBottom: 8 }}>
        <Button
          type="text"
          icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
          onClick={() => onPlayingChange(!playing)}
        >
          {playing ? '暂停' : '播放'}
        </Button>
        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
          空格键播放/暂停 · 点击波形跳转{externalPlayback ? ' · 同步播放 Clip 音频' : ''}
        </Typography.Text>
      </Space>
      <canvas
        ref={canvasRef}
        width={560}
        height={64}
        onClick={onClick}
        style={{ width: '100%', height: 64, cursor: 'pointer', borderRadius: 4 }}
      />
      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
        {api.formatTimestampNs(cursorNs, startNs)} / {api.formatTimestampNs(endNs, startNs)}
      </Typography.Text>
    </div>
  )
}
