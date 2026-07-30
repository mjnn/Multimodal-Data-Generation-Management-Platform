import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { linearTheme } from '../theme/linearTheme'
import { lightTheme } from '../theme/lightTheme'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'hmi-theme-mode'

type ThemeContextValue = {
  mode: ThemeMode
  toggleMode: () => void
  setMode: (mode: ThemeMode) => void
  antdTheme: typeof linearTheme
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStoredMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === 'light' || raw === 'dark') return raw
  } catch {
    /* ignore */
  }
  return 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode())

  useEffect(() => {
    document.documentElement.dataset.theme = mode
    localStorage.setItem(STORAGE_KEY, mode)
  }, [mode])

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
  }, [])

  const toggleMode = useCallback(() => {
    setModeState((m) => (m === 'dark' ? 'light' : 'dark'))
  }, [])

  const antdTheme = useMemo(() => (mode === 'light' ? lightTheme : linearTheme), [mode])

  const value = useMemo(
    () => ({ mode, toggleMode, setMode, antdTheme }),
    [antdTheme, mode, setMode, toggleMode],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useThemeMode(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useThemeMode must be used within ThemeProvider')
  return ctx
}
