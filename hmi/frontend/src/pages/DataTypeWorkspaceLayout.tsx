import { useEffect, useState } from 'react'
import { Link, Outlet, useParams } from 'react-router-dom'
import { Alert, Spin, Typography } from 'antd'
import { api } from '../api'
import type { DataTypeRecipe } from '../api/types'
import { DataTypeWorkspaceProvider } from '../context/DataTypeWorkspaceContext'
import { hydrateOverview, overviewCustomized } from '../utils/overviewLayout'

function workspaceBanner(recipe: DataTypeRecipe): string {
  const ov = hydrateOverview(recipe)
  const custom = overviewCustomized(ov) ? ' · 自定义展示页排版' : ''
  return `标签树 ${recipe.taxonomy_id} · 视图 ${recipe.overview_view}${custom}`
}

export function DataTypeWorkspaceLayout() {
  const { dataTypeId } = useParams()
  const [recipe, setRecipe] = useState<DataTypeRecipe | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!dataTypeId) return
    let cancelled = false
    setError(null)
    void (async () => {
      try {
        const rec = await api.getDataType(dataTypeId)
        if (!cancelled) setRecipe(rec)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '无法加载数据类型')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [dataTypeId])

  if (error) {
    return <Alert type="error" message={error} />
  }
  if (!recipe) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin />
      </div>
    )
  }

  return (
    <DataTypeWorkspaceProvider recipe={recipe}>
      <Alert
        data-testid="data-type-workspace-banner"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={
          <span>
            当前工作区：<Typography.Text strong>{recipe.title}</Typography.Text>
            {' · '}
            <Link to="/">切换数据类型</Link>
          </span>
        }
        description={workspaceBanner(recipe)}
      />
      <Outlet />
    </DataTypeWorkspaceProvider>
  )
}
