import { PauseCircleOutlined, PlayCircleOutlined, RedoOutlined, SoundOutlined } from '@ant-design/icons'
import { Alert, Button, Col, Empty, Row, Space, Spin, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { AudioNvhBootstrap, AudioNvhChannel } from '../api/types'
import { getAccessToken } from '../auth/tokenStore'
import { useTimelineKeyboard } from '../hooks/useTimelineKeyboard'
import { replayFromStart, togglePlayWithReplay, advancePlayhead } from '../utils/playback'
import { resolveMediaUrl } from '../utils/mediaUrl'
import { ClipSyncedAudio } from './ClipSyncedAudio'

type WaveformPayload = { fs_display?: number; samples: number[] }
type SplPoint = { t_s: number; spl_db: number }

type Props = {
  clipId: string
  runId: string
  previewContext?: 'browse' | 'review'
  testId?: string
  onReady?: (boot: AudioNvhBootstrap) => void
  /** When set, render only boot.channels[channelIndex]. */
  channelIndex?: number
  channelName?: string
  /** Controlled playhead (seconds). Uncontrolled when omitted. */
  cursorS?: number
  onCursorChange?: (t: number) => void
  enableAudio?: boolean
}

function formatSec(t: number): string {
  if (!Number.isFinite(t) || t < 0) return '0.0s'
  const m = Math.floor(t / 60)
  const s = t - m * 60
  return m > 0 ? `${m}:${s.toFixed(1).padStart(4, '0')}` : `${s.toFixed(1)}s`
}

async function fetchJsonAuth(url: string): Promise<unknown> {
  const resolved = resolveMediaUrl(url)
  const headers: Record<string, string> = {}
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(resolved, { credentials: 'include', headers })
  if (!res.ok) throw new Error(`load failed ${res.status}`)
  const text = await res.text()
  if (url.includes('.jsonl')) {
    return text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => JSON.parse(l) as SplPoint)
  }
  return JSON.parse(text) as unknown
}

function WaveformCanvas({
  samples,
  durationS,
  cursorS,
  onSeek,
}: {
  samples: number[]
  durationS: number
  cursorS: number
  onSeek: (t: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || samples.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#0b1f2a'
    ctx.fillRect(0, 0, w, h)
    const peak = Math.max(...samples.map((x) => Math.abs(x)), 1e-9)
    const cursorX = (cursorS / Math.max(durationS, 1e-6)) * w
    const barW = w / samples.length
    samples.forEach((v, i) => {
      const a = Math.abs(v) / peak
      const bh = Math.max(1, a * (h * 0.85))
      const x = i * barW
      ctx.fillStyle = x < cursorX ? '#3aa6a0' : '#2a4a55'
      ctx.fillRect(x, (h - bh) / 2, Math.max(1, barW - 0.5), bh)
    })
    ctx.strokeStyle = '#f0c14a'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(cursorX, 0)
    ctx.lineTo(cursorX, h)
    ctx.stroke()
  }, [samples, durationS, cursorS])

  return (
    <canvas
      ref={canvasRef}
      width={720}
      height={56}
      data-testid="audio-nvh-waveform"
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const ratio = (e.clientX - rect.left) / rect.width
        onSeek(ratio * durationS)
      }}
      style={{ width: '100%', height: 56, cursor: 'pointer', borderRadius: 4, display: 'block' }}
    />
  )
}

function SplStrip({
  points,
  durationS,
  cursorS,
  onSeek,
}: {
  points: SplPoint[]
  durationS: number
  cursorS: number
  onSeek: (t: number) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || points.length === 0) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#101820'
    ctx.fillRect(0, 0, w, h)
    const vals = points.map((p) => p.spl_db)
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const span = Math.max(hi - lo, 1)
    ctx.strokeStyle = '#7ec8e3'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    points.forEach((p, i) => {
      const x = (p.t_s / Math.max(durationS, 1e-6)) * w
      const y = h - ((p.spl_db - lo) / span) * (h - 4) - 2
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()
    const cursorX = (cursorS / Math.max(durationS, 1e-6)) * w
    ctx.strokeStyle = '#f0c14a'
    ctx.beginPath()
    ctx.moveTo(cursorX, 0)
    ctx.lineTo(cursorX, h)
    ctx.stroke()
  }, [points, durationS, cursorS])

  return (
    <canvas
      ref={canvasRef}
      width={720}
      height={40}
      data-testid="audio-nvh-spl"
      onClick={(e) => {
        const rect = e.currentTarget.getBoundingClientRect()
        const ratio = (e.clientX - rect.left) / rect.width
        onSeek(ratio * durationS)
      }}
      style={{ width: '100%', height: 40, cursor: 'pointer', borderRadius: 4, display: 'block' }}
    />
  )
}

function ChannelSpec({
  channel,
  durationS,
  cursorS,
  onSeek,
}: {
  channel: AudioNvhChannel
  durationS: number
  cursorS: number
  onSeek: (t: number) => void
}) {
  const imgUrl = resolveMediaUrl(channel.mel_url || channel.stft_url || '')
  const cursorPct = (cursorS / Math.max(durationS, 1e-6)) * 100
  return (
    <div style={{ position: 'relative', marginBottom: 8 }} data-testid={`audio-nvh-ch-${channel.name}`}>
      <Space size={8} style={{ marginBottom: 4 }}>
        <Tag color="cyan">{channel.name}</Tag>
        {channel.leq_db != null ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Leq {channel.leq_db.toFixed(1)} dB
          </Typography.Text>
        ) : null}
      </Space>
      <div
        style={{ position: 'relative', borderRadius: 4, overflow: 'hidden', background: '#0b1f2a', cursor: 'pointer' }}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          const ratio = (e.clientX - rect.left) / rect.width
          onSeek(ratio * durationS)
        }}
      >
        {imgUrl ? (
          <img
            src={imgUrl}
            alt={`${channel.name} spectrogram`}
            style={{ width: '100%', height: 72, objectFit: 'fill', display: 'block', opacity: 0.95 }}
          />
        ) : (
          <div style={{ height: 72, display: 'grid', placeItems: 'center' }}>
            <Typography.Text type="secondary">无频谱图</Typography.Text>
          </div>
        )}
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${cursorPct}%`,
            width: 2,
            background: '#f0c14a',
            pointerEvents: 'none',
          }}
        />
      </div>
    </div>
  )
}

export function AudioNvhTimelinePanel({
  clipId,
  runId,
  testId,
  onReady,
  channelIndex,
  channelName,
  cursorS: cursorSProp,
  onCursorChange,
  enableAudio = true,
}: Props) {
  const [boot, setBoot] = useState<AudioNvhBootstrap | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [cursorSLocal, setCursorSLocal] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [wave, setWave] = useState<number[]>([])
  const [spl, setSpl] = useState<SplPoint[]>([])
  const cursorS = cursorSProp != null ? cursorSProp : cursorSLocal
  const cursorRef = useRef(cursorS)
  cursorRef.current = cursorS
  const onCursorChangeRef = useRef(onCursorChange)
  onCursorChangeRef.current = onCursorChange
  const setCursorS = useCallback((t: number | ((prev: number) => number)) => {
    const prev = cursorRef.current
    const next = typeof t === 'function' ? t(prev) : t
    cursorRef.current = next
    setCursorSLocal(next)
    onCursorChangeRef.current?.(next)
  }, [])
  const channels = boot?.channels || []
  const sliced =
    channelIndex == null
      ? channels
      : channelIndex >= 0 && channelIndex < channels.length
        ? [channels[channelIndex]]
        : []
  const activeCh = sliced[0]

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    void api
      .getAudioNvhBootstrap(clipId, runId)
      .then((payload) => {
        if (cancelled) return
        setBoot(payload)
        setCursorS(0)
        onReady?.(payload)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setBoot(null)
        setError(e instanceof Error ? e.message : '加载音频频谱失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [clipId, runId, onReady])

  useEffect(() => {
    if (!activeCh?.waveform_url) {
      setWave([])
      return
    }
    let cancelled = false
    void fetchJsonAuth(activeCh.waveform_url)
      .then((doc) => {
        if (cancelled) return
        const payload = doc as WaveformPayload
        setWave(Array.isArray(payload.samples) ? payload.samples.map(Number) : [])
      })
      .catch(() => {
        if (!cancelled) setWave([])
      })
    return () => {
      cancelled = true
    }
  }, [activeCh?.waveform_url])

  useEffect(() => {
    if (!activeCh?.spl_timeline_url) {
      setSpl([])
      return
    }
    let cancelled = false
    void fetchJsonAuth(activeCh.spl_timeline_url)
      .then((doc) => {
        if (cancelled) return
        setSpl(Array.isArray(doc) ? (doc as SplPoint[]) : [])
      })
      .catch(() => {
        if (!cancelled) setSpl([])
      })
    return () => {
      cancelled = true
    }
  }, [activeCh?.spl_timeline_url])

  const durationS = Math.max(0.001, boot?.duration_s || 0.001)
  const startNs = 0
  const endNs = Math.round(durationS * 1e9)
  const cursorNs = Math.round(cursorS * 1e9)
  const hasAudio = Boolean(enableAudio && boot?.audio_url)

  const onSeek = useCallback(
    (t: number) => {
      setCursorS(Math.min(durationS, Math.max(0, t)))
    },
    [durationS, setCursorS],
  )

  const onCursorChangeNs = useCallback(
    (ns: number) => {
      setCursorS(Math.min(durationS, Math.max(0, ns / 1e9)))
    },
    [durationS, setCursorS],
  )

  useTimelineKeyboard({
    enabled: !!boot && !loading && !error,
    cursorNs,
    startNs,
    endNs,
    snapPoints: [],
    onCursorChange: onCursorChangeNs,
    playing,
    onPlayingChange: setPlaying,
  })

  useEffect(() => {
    if (!playing || hasAudio) return
    const timer = window.setInterval(() => {
      const { nextS, ended } = advancePlayhead(cursorRef.current, durationS)
      setCursorS(nextS)
      if (ended) setPlaying(false)
    }, 100)
    return () => window.clearInterval(timer)
  }, [playing, durationS, hasAudio, setCursorS])

  const leqMean = useMemo(() => {
    if (boot?.leq_db_mean != null) return boot.leq_db_mean
    const vals = (boot?.channels || []).map((c) => c.leq_db).filter((v): v is number => v != null)
    if (!vals.length) return null
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }, [boot])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }} data-testid={testId}>
        <Spin />
      </div>
    )
  }
  if (error || !boot) {
    return (
      <Alert
        type="warning"
        showIcon
        message="暂无四通道频谱产物"
        description={error || '该 run 缺少 audio_spec/'}
        data-testid={testId}
      />
    )
  }

  return (
    <div className="audio-nvh-timeline" data-testid={testId || 'audio-nvh-timeline'} style={{ width: '100%' }}>
      <Row gutter={16}>
        <Col xs={24} lg={24}>
          <Space style={{ marginBottom: 8 }} wrap>
            <Button
              type="primary"
              icon={playing ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={() =>
                togglePlayWithReplay({
                  playing,
                  cursorNs,
                  startNs,
                  endNs,
                  onCursorChange: onCursorChangeNs,
                  onPlayingChange: setPlaying,
                })
              }
              data-testid="audio-nvh-play"
            >
              {playing ? '暂停' : '播放'}
            </Button>
            <Button
              icon={<RedoOutlined />}
              onClick={() =>
                replayFromStart({
                  startNs,
                  onCursorChange: onCursorChangeNs,
                  onPlayingChange: setPlaying,
                })
              }
              data-testid="audio-nvh-replay"
              title="从头播放"
            >
              重播
            </Button>
            <Typography.Text type="secondary" data-testid="audio-nvh-clock">
              {formatSec(cursorS)} / {formatSec(durationS)}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              空格播放/暂停（结束时再按从头）
            </Typography.Text>
            {leqMean != null ? <Tag color="blue">Leq {leqMean.toFixed(1)} dB</Tag> : null}
            <Tag icon={<SoundOutlined />}>
              {channelIndex == null
                ? `${boot.channels.length} 通道`
                : channelName || sliced[0]?.name || `ch${channelIndex + 1}`}
            </Tag>
            {boot.fs_hz ? <Tag>{boot.fs_hz} Hz</Tag> : null}
          </Space>

          {channelIndex != null && !sliced.length ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本路无频谱" />
          ) : (
            sliced.map((ch) => (
              <ChannelSpec key={ch.name} channel={ch} durationS={durationS} cursorS={cursorS} onSeek={onSeek} />
            ))
          )}

          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            SPL 曲线（{activeCh?.name || '—'}）
          </Typography.Text>
          {spl.length ? (
            <SplStrip points={spl} durationS={durationS} cursorS={cursorS} onSeek={onSeek} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无 SPL 时间线" />
          )}

          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            波形（{activeCh?.name || '—'}）
          </Typography.Text>
          {wave.length ? (
            <WaveformCanvas samples={wave} durationS={durationS} cursorS={cursorS} onSeek={onSeek} />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无波形" />
          )}

          {enableAudio && boot.audio_url ? (
            <ClipSyncedAudio
              audioUrl={boot.audio_url}
              startNs={startNs}
              endNs={endNs}
              cursorNs={cursorNs}
              playing={playing}
              onClock={(t) => setCursorS(t)}
              onEnded={() => {
                setCursorS(durationS)
                setPlaying(false)
              }}
            />
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              无 preview/audio.wav，仅时间轴 scrub（无声播放）
            </Typography.Text>
          )}
        </Col>
      </Row>
    </div>
  )
}
