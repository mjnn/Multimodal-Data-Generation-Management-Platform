import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type DataSourceMode } from '../api'

type DataSourceContextValue = {
  /** true = 本地 SQLite + 磁盘；false = 在线 OSS + MC */
  localMode: boolean
  dataSource: DataSourceMode
  loading: boolean
  switching: boolean
  setLocalMode: (enabled: boolean) => Promise<void>
  dataRevision: number
  bumpDataRevision: () => void
}

const DataSourceContext = createContext<DataSourceContextValue | null>(null)

export function DataSourceProvider({ children }: { children: ReactNode }) {
  const [dataSource, setDataSourceState] = useState<DataSourceMode>('local')
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [dataRevision, setDataRevision] = useState(0)

  useEffect(() => {
    let cancelled = false
    void api
      .getDataSource()
      .then((r) => {
        if (!cancelled) setDataSourceState(r.data_source)
      })
      .catch(() => {
        if (!cancelled) setDataSourceState('local')
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

  const setLocalMode = useCallback(async (enabled: boolean) => {
    const next: DataSourceMode = enabled ? 'local' : 'cloud'
    if (next === dataSource) return
    setSwitching(true)
    try {
      const r = await api.setDataSource(next)
      setDataSourceState(r.data_source)
      setDataRevision((v) => v + 1)
      window.location.reload()
    } finally {
      setSwitching(false)
    }
  }, [dataSource])

  const value = useMemo(
    () => ({
      localMode: dataSource === 'local',
      dataSource,
      loading,
      switching,
      setLocalMode,
      dataRevision,
      bumpDataRevision,
    }),
    [dataSource, loading, switching, setLocalMode, dataRevision, bumpDataRevision],
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
