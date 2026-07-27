import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { getAccessToken, setAccessToken } from '../auth/tokenStore'
import type { LoginResponse } from '../auth/types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

let unauthorizedHandler: (() => void) | null = null
let refreshPromise: Promise<string | null> | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

export const http = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 90_000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = http
      .post<LoginResponse>('/auth/refresh')
      .then((res) => {
        setAccessToken(res.data.access_token)
        return res.data.access_token
      })
      .catch(() => {
        setAccessToken(null)
        unauthorizedHandler?.()
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    const config = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    const path = config?.url ?? ''

    if (
      status === 401 &&
      config &&
      !config._retry &&
      !path.includes('/auth/login') &&
      !path.includes('/auth/refresh')
    ) {
      config._retry = true
      const token = await refreshAccessToken()
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
        return http.request(config)
      }
    }

    if (status === 401 && !path.includes('/auth/login') && !path.includes('/auth/refresh')) {
      setAccessToken(null)
      unauthorizedHandler?.()
    }

    throw error
  },
)

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers = init?.headers as Record<string, string> | undefined
  const body = init?.body

  const res = await http.request<T>({
    url: path,
    method,
    headers,
    data:
      body && typeof body === 'string' && headers?.['Content-Type'] !== 'multipart/form-data'
        ? JSON.parse(body)
        : body,
  })
  return res.data
}
