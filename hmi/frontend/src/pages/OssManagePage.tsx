import { Navigate, useSearchParams } from 'react-router-dom'

/** Legacy `/oss` → 数据源 · OSS 浏览 */
export function OssManagePage() {
  const [searchParams] = useSearchParams()
  const next = new URLSearchParams()
  next.set('tab', 'oss')
  const prefix = searchParams.get('prefix')
  if (prefix) next.set('prefix', prefix)
  return <Navigate to={`/lake?${next.toString()}`} replace />
}
