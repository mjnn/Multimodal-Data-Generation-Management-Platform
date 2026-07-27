import dayjs from 'dayjs'

/** Rosbag record_time_ns looks like Unix epoch ns (roughly year 2001+). */
const EPOCH_NS_MIN = 1e17

export function formatTimestampNs(ns: number, startNs = 0): string {
  const relSec = (ns - startNs) / 1e9
  const m = Math.floor(relSec / 60)
  const s = relSec % 60
  return `${m}:${s.toFixed(2).padStart(5, '0')}`
}

export function formatRecordTimeNs(ns: number): string {
  return dayjs(ns / 1e6).format('YYYY-MM-DD HH:mm:ss')
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
