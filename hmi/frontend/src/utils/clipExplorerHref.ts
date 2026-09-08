/** Clip 详情不在 `/w/:dataTypeId` 下；入口必须自带 run 与数据类型，否则会落到 remembered OMS 树。 */

export type ClipExplorerHrefOpts = {
  runId?: string | null
  dataTypeId?: string | null
  t?: string | number | null
}

export function buildClipExplorerHref(clipId: string, opts?: ClipExplorerHrefOpts): string {
  const params = new URLSearchParams()
  const runId = String(opts?.runId || '').trim()
  const dataTypeId = String(opts?.dataTypeId || '').trim()
  if (runId) params.set('run_id', runId)
  if (dataTypeId) params.set('data_type_id', dataTypeId)
  if (opts?.t != null && String(opts.t).trim() !== '') params.set('t', String(opts.t))
  const q = params.toString()
  return `/clips/${encodeURIComponent(clipId)}${q ? `?${q}` : ''}`
}
