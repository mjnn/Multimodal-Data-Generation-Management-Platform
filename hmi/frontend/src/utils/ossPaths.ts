/** OSS key prefix for clip run artifacts (matches backend safe_clip_dir). */
export function clipRunOssPrefix(clipId: string, runId: string): string {
  const safe = clipId.replace(/:/g, '__')
  return `clips/${safe}/runs/${runId}/`
}

export function ossManageHref(prefix: string): string {
  const q = new URLSearchParams({ tab: 'oss' })
  if (prefix) q.set('prefix', prefix)
  return `/lake?${q.toString()}`
}
