import type { AxiosError } from 'axios'
import { localizeApiMessage } from './uiLabels'

/** FastAPI `{ detail: string | { message } }` or axios fallback text. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  const ax = e as AxiosError<{ detail?: string | { message?: string; code?: string } | Array<{ msg?: string }> }>
  const status = ax?.response?.status
  if (status === 413) {
    return '上传体积超过服务器限制（请缩小批次或联系管理员提高 Nginx client_max_body_size）'
  }
  const detail = ax?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return localizeApiMessage(detail)
  }
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
    return localizeApiMessage(detail.message)
  }
  if (Array.isArray(detail) && detail[0]?.msg) {
    return localizeApiMessage(detail[0].msg)
  }
  // axios 在连接被 413/重置掐断时常只报 Network Error
  if (ax?.message === 'Network Error') {
    return '网络错误：上传可能超时或超过 Nginx 体积限制，请缩小批次后重试'
  }
  if (e instanceof Error && e.message && !e.message.startsWith('Request failed with status code')) {
    return localizeApiMessage(e.message)
  }
  return fallback
}
