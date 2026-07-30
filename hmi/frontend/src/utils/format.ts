import dayjs, { type Dayjs } from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'

dayjs.extend(utc)
dayjs.extend(timezone)

/** All HMI wall-clock display uses China Standard Time (UTC+8). */
export const DISPLAY_TIMEZONE = 'Asia/Shanghai'

/** Rosbag record_time_ns looks like Unix epoch ns (roughly year 2001+). */
const EPOCH_NS_MIN = 1e17

function parseApiDateTime(value: string | number): Dayjs | null {
  if (typeof value === 'number') {
    const ms = value < 1e12 ? value * 1000 : value
    const d = dayjs.utc(ms)
    return d.isValid() ? d.tz(DISPLAY_TIMEZONE) : null
  }
  const s = String(value).trim()
  if (!s) return null
  if (/^\d+$/.test(s)) {
    const n = Number(s)
    const ms = n < 1e12 ? n * 1000 : n
    const d = dayjs.utc(ms)
    return d.isValid() ? d.tz(DISPLAY_TIMEZONE) : null
  }
  if (/Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s)) {
    const d = dayjs(s).tz(DISPLAY_TIMEZONE)
    return d.isValid() ? d : null
  }
  const normalized = s.includes('T') ? s : s.replace(' ', 'T')
  const asUtc = dayjs.utc(normalized)
  if (asUtc.isValid()) {
    return asUtc.tz(DISPLAY_TIMEZONE)
  }
  const fallback = dayjs(s).tz(DISPLAY_TIMEZONE)
  return fallback.isValid() ? fallback : null
}

export function formatRelativeOffsetNs(ns: number, startNs = 0): string {
  const relSec = (ns - startNs) / 1e9
  const m = Math.floor(relSec / 60)
  const s = relSec % 60
  return `${m}:${s.toFixed(2).padStart(5, '0')}`
}

/** Wall-clock from record_time_ns when available; otherwise in-clip offset. */
export function formatTimestampNs(ns: number, startNs = 0): string {
  if (ns >= EPOCH_NS_MIN || startNs >= EPOCH_NS_MIN) {
    return formatRecordTimeNs(ns)
  }
  return formatRelativeOffsetNs(ns, startNs)
}

export function formatRecordTimeNs(ns: number): string {
  return dayjs.utc(ns / 1e6).tz(DISPLAY_TIMEZONE).format('YYYY-MM-DD HH:mm:ss')
}

export function formatDateTime(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  const d = parseApiDateTime(value)
  if (!d?.isValid()) return String(value)
  return d.format('YYYY-MM-DD HH:mm:ss')
}

export function formatCollectionPeriod(
  startNs: number,
  endNs: number,
  durationSec?: number,
): string {
  if (startNs >= EPOCH_NS_MIN && endNs > startNs) {
    return `${formatRecordTimeNs(startNs)} — ${formatRecordTimeNs(endNs)}`
  }
  if (durationSec != null && durationSec > 0) {
    return `时长 ${durationSec.toFixed(1)}s（演示数据，无绝对采集时间）`
  }
  return '—'
}
