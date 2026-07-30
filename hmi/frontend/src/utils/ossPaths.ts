/** OSS key prefix for clip run artifacts (matches backend safe_clip_dir). */
export function clipRunOssPrefix(clipId: string, runId: string): string {
  const safe = clipId.replace(/:/g, '__')
  return `clips/${safe}/runs/${runId}/`
}

export function ossManageHref(prefix: string): string {
  const q = prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''
  return `/oss${q}`
}
