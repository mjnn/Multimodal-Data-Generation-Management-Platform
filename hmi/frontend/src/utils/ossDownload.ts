import { http } from '../api/http'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

/** Download OSS object with auth (fixes local disk + SPA subpath). */
export async function downloadOssObject(key: string, filename: string): Promise<void> {
  const path = `/oss/file?${new URLSearchParams({ key })}`
  const res = await http.get<Blob>(path, { responseType: 'blob' })
  const blob = res.data
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename || key.split('/').pop() || 'download'
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export function resolveDownloadUrl(url: string): string {
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/api/')) {
    const base = API_BASE.replace(/\/$/, '')
    const suffix = url.slice(4)
    return `${base}${suffix}`
  }
  if (url.startsWith('/')) {
    const base = API_BASE.replace(/\/api\/?$/, '').replace(/\/$/, '')
    return `${base}${url}`
  }
  return url
}
