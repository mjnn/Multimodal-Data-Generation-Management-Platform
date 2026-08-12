import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type DataSourceMode } from '../api'

type DataSourceContextValue = {
  /** true = 本地 SQLite + 磁盘；false = 在线 OSS + MC */
  localMode: boolean
  dataSource: DataSourceMode
  /** HMI_TEST_MODE：显示本地/云端切换与重置测试数据 */
  testMode: boolean
  loading: boolean
  switching: boolean
  setLocalMode: (enabled: boolean) => Promise<void>
  dataRevision: number
  bumpDataRevision: () => void
}

const DataSourceContext = createContext<DataSourceContextValue | null>(null)

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const [dataSource, setDataSourceState] = useState<DataSourceMode>('cloud')
  const [testMode, setTestMode] = useState(false)
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [dataRevision, setDataRevision] = useState(0)

  useEffect(() => {
    let cancelled = false
    void Promise.all([api.getDataSource(), api.health().catch(() => null)])
      .then(([r, health]) => {
        if (cancelled) return
        setDataSourceState(r.data_source)
        // Prefer explicit data-source field; fall back to /health for older/newer mix
        const flag =
          typeof r.test_mode === 'boolean'
            ? r.test_mode
            : Boolean(health && typeof health.test_mode === 'boolean' ? health.test_mode : false)
        setTestMode(flag)
      })
      .catch(() => {
        if (!cancelled) {
          setDataSourceState('cloud')
          setTestMode(false)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [dataRevision])

  const bumpDataRevision = useCallback(() => {
    setDataRevision((v) => v + 1)
  }, [])

  const setLocalMode = useCallback(
    async (enabled: boolean) => {
      if (!testMode && enabled) {
        return
      }
      const next: DataSourceMode = enabled ? 'local' : 'cloud'
      if (next === dataSource) return
      setSwitching(true)
      try {
        const r = await api.setDataSource(next)
        setDataSourceState(r.data_source)
        setTestMode(Boolean(r.test_mode))
        setDataRevision((v) => v + 1)
        window.location.reload()
      } finally {
        setSwitching(false)
      }
    },
    [dataSource, testMode],
  )

  const value = useMemo(
    () => ({
      localMode: dataSource === 'local',
      dataSource,
      testMode,
      loading,
      switching,
      setLocalMode,
      dataRevision,
      bumpDataRevision,
    }),
    [dataSource, testMode, loading, switching, setLocalMode, dataRevision, bumpDataRevision],
  )

  return <DataSourceContext.Provider value={value}>{children}</DataSourceContext.Provider>
}

export function useDataSourceMode(): DataSourceContextValue {
  const ctx = useContext(DataSourceContext)
  if (!ctx) {
    throw new Error('useDataSourceMode must be used within DataSourceProvider')
  }
  return ctx
}
