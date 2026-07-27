/** React Router basename derived from Vite `base` (e.g. `/tools/rosbag-labels/`). */
export function routerBasename(): string | undefined {
  const trimmed = (import.meta.env.BASE_URL ?? '/').replace(/\/$/, '')
  return trimmed || undefined
}
