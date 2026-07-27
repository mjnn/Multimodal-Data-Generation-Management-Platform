/** Resolve backend media paths under SPA subpath (e.g. /tools/rosbag-labels/api). */
export function resolveMediaUrl(url: string | undefined | null): string {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '') || '/api'
  if (url.startsWith('/api/') && apiBase !== '/api') {
    return `${apiBase}${url.slice(4)}`
  }
  return url
}
