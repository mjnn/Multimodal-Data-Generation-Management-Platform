/** Source kinds are lake file suffixes (.bag, .mp4, .wav), not generic video/audio. */

export const VIDEO_EXTS = ['.mp4', '.webm', '.mov', '.mkv', '.avi'] as const
export const AUDIO_EXTS = ['.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac', '.dat'] as const
export const TEXT_EXTS = ['.txt', '.json', '.md', '.csv'] as const
export const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.bmp'] as const
export const BAG_EXTS = ['.bag'] as const

export const SOURCE_KINDS = new Set<string>([
  ...VIDEO_EXTS,
  ...AUDIO_EXTS,
  ...TEXT_EXTS,
  ...IMAGE_EXTS,
  ...BAG_EXTS,
])

const LEGACY: Record<string, string> = {
  rosbag: '.bag',
  bag: '.bag',
  video: '.mp4',
  audio: '.wav',
  image: '.jpg',
  text: '.txt',
}

export const PARSE_BAG_MODALITIES = ['frames', '.wav', '.json'] as const
export type ParseBagModality = (typeof PARSE_BAG_MODALITIES)[number]

const PARSE_BAG_ALIASES: Record<string, ParseBagModality> = {
  video: 'frames',
  '.mp4': 'frames',
  mp4: 'frames',
  audio: '.wav',
  text: '.json',
  frames: 'frames',
  '.wav': '.wav',
  '.json': '.json',
}

export function normalizeSourceKind(raw: string | null | undefined): string | null {
  let k = String(raw || '').trim().toLowerCase()
  if (!k) return null
  if (LEGACY[k]) return LEGACY[k]
  if (!k.startsWith('.')) k = `.${k}`
  return SOURCE_KINDS.has(k) ? k : null
}

export function kindFromFilename(filename: string): string | null {
  const name = filename.replace(/\\/g, '/').split('/').pop() || ''
  const dot = name.lastIndexOf('.')
  if (dot < 0) return null
  const suffix = name.slice(dot).toLowerCase()
  return SOURCE_KINDS.has(suffix) ? suffix : null
}

export function normalizeParseBagModality(raw: string | null | undefined): ParseBagModality | null {
  const k = String(raw || '').trim().toLowerCase()
  if (!k) return null
  if (PARSE_BAG_ALIASES[k]) return PARSE_BAG_ALIASES[k]
  if ((PARSE_BAG_MODALITIES as readonly string[]).includes(k)) return k as ParseBagModality
  const withDot = k.startsWith('.') ? k : `.${k}`
  return (PARSE_BAG_MODALITIES as readonly string[]).includes(withDot)
    ? (withDot as ParseBagModality)
    : null
}

export function sourceKindOptions(catalogKinds?: string[]): Array<{ value: string; label: string }> {
  const values = catalogKinds?.length ? catalogKinds : [...SOURCE_KINDS]
  return [...values].sort().map((v) => ({ value: v, label: v }))
}
