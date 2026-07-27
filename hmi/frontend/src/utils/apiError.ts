import type { AxiosError } from 'axios'

/** FastAPI `{ detail: { message } }` or axios fallback text. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  const ax = e as AxiosError<{ detail?: { message?: string } | Array<{ msg?: string }> }>
  const detail = ax?.response?.data?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
    return detail.message
  }
  if (Array.isArray(detail) && detail[0]?.msg) {
    return detail[0].msg
  }
  if (e instanceof Error && e.message && !e.message.startsWith('Request failed with status code')) {
    return e.message
  }
  return fallback
}
