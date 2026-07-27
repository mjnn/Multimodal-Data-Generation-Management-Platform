import { App } from 'antd'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { fetchJson, http, setUnauthorizedHandler } from '../api/http'
import { getAccessToken, setAccessToken } from './tokenStore'
import type { AuthUser, LoginResponse } from './types'

type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<AuthUser | null>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const goLogin = useCallback(() => {
    const from = `${location.pathname}${location.search}`
    if (from === '/login' || from.startsWith('/login?')) return
    navigate('/login', { replace: true, state: { from } })
  }, [navigate, location.pathname, location.search])

  const refreshMe = useCallback(async (): Promise<AuthUser | null> => {
    try {
      const res = await fetchJson<{ user: AuthUser }>('/auth/me')
      setUser(res.user)
      return res.user
    } catch {
      setUser(null)
      return null
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(goLogin)
    return () => setUnauthorizedHandler(null)
  }, [goLogin])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (getAccessToken()) {
          const me = await refreshMe()
          if (me) return
        }
        const res = await http.post<LoginResponse>('/auth/refresh')
        if (cancelled) return
        setAccessToken(res.data.access_token)
        await refreshMe()
      } catch {
        if (!cancelled) {
          setAccessToken(null)
          setUser(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshMe])

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await http.post<LoginResponse>('/auth/login', { username, password })
      setAccessToken(res.data.access_token)
      setUser(res.data.user)
      message.success(`欢迎，${res.data.user.display_name}`)
    },
    [message],
  )

  const logout = useCallback(async () => {
    try {
      await http.post('/auth/logout')
    } catch {
      /* ignore */
    }
    setAccessToken(null)
    setUser(null)
    navigate('/login', { replace: true })
  }, [navigate])

  const value = useMemo(
    () => ({ user, loading, login, logout, refreshMe }),
    [user, loading, login, logout, refreshMe],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
