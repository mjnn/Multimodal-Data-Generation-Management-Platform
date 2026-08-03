import type { AxiosError } from 'axios'
import { localizeApiMessage } from './uiLabels'

/** FastAPI `{ detail: { message } }` or axios fallback text. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  const ax = e as AxiosError<{ detail?: { message?: string } | Array<{ msg?: string }> }>
  const detail = ax?.response?.data?.detail
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
    return localizeApiMessage(detail.message)
  }
  if (Array.isArray(detail) && detail[0]?.msg) {
    return localizeApiMessage(detail[0].msg)
  }
  if (e instanceof Error && e.message && !e.message.startsWith('Request failed with status code')) {
    return localizeApiMessage(e.message)
  }
  return fallback
}
