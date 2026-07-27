import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

import { clearOverviewSnapshot } from '../utils/overviewCache'

const STORAGE_KEY = 'hmi-demo-mode'

type DemoModeContextValue = {
  demoMode: boolean
  setDemoMode: (enabled: boolean) => void
  demoDataVersion: number
  bumpDemoDataVersion: () => void
}

const DemoModeContext = createContext<DemoModeContextValue | null>(null)

function readStoredDemoMode(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

function persistDemoMode(enabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0')
  } catch {
    // ignore quota / private mode
  }
}

export function DemoModeProvider({ children }: { children: ReactNode }) {
  const [demoMode, setDemoModeState] = useState(readStoredDemoMode)
  const [demoDataVersion, setDemoDataVersion] = useState(0)

  const setDemoMode = useCallback((enabled: boolean) => {
    setDemoModeState(enabled)
    persistDemoMode(enabled)
  }, [])

  const bumpDemoDataVersion = useCallback(() => {
    clearOverviewSnapshot()
    setDemoDataVersion((v) => v + 1)
  }, [])

  const value = useMemo(
    () => ({ demoMode, setDemoMode, demoDataVersion, bumpDemoDataVersion }),
    [demoMode, setDemoMode, demoDataVersion, bumpDemoDataVersion],
  )

  return <DemoModeContext.Provider value={value}>{children}</DemoModeContext.Provider>
}

export function useDemoMode(): DemoModeContextValue {
  const ctx = useContext(DemoModeContext)
  if (!ctx) {
    throw new Error('useDemoMode must be used within DemoModeProvider')
  }
  return ctx
}
