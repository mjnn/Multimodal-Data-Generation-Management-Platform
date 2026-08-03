import { ApartmentOutlined } from '@ant-design/icons'
import { Alert, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { TaxonomyContext } from '../api/types'

type TaxonomyContextBarProps = {
  /** Clip/review bound taxonomy version code (optional). */
  pageVersionCode?: string | null
  pageVersionId?: string | null
  mixedHint?: boolean
}

export function TaxonomyContextBar({
  pageVersionCode,
  pageVersionId,
  mixedHint,
}: TaxonomyContextBarProps) {
  const [ctx, setCtx] = useState<TaxonomyContext | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    void api
      .getTaxonomyContext()
      .then(setCtx)
      .catch(() => setCtx(null))
      .finally(() => setLoading(false))
  }, [])

  if (loading && !ctx) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        加载标签树契约…
      </Typography.Text>
    )
  }

  const publishedCode = ctx?.published_taxonomy_version_code ?? '—'
  const publishedId = ctx?.published_taxonomy_version_id
  const behind = (ctx?.clips_on_non_published_taxonomy ?? 0) > 0
  const pageMismatch =
    pageVersionId && publishedId && pageVersionId !== publishedId

  return (
    <div
      data-testid="taxonomy-context-bar"
      style={{
        marginBottom: 12,
        padding: '8px 12px',
        borderRadius: 8,
        border: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
        background: 'var(--ant-color-fill-quaternary, #fafafa)',
      }}
    >
      <Space wrap size="middle">
        <ApartmentOutlined />
        <Typography.Text style={{ fontSize: 13 }}>
          已发布:{' '}
          <Typography.Text strong>{publishedCode}</Typography.Text>
          {ctx?.published_node_count != null ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {' '}
              · {ctx.published_node_count} 节点
            </Typography.Text>
          ) : null}
        </Typography.Text>
        {pageVersionCode ? (
          <Typography.Text style={{ fontSize: 13 }}>
            本页契约: <Tag color={pageMismatch ? 'warning' : 'default'}>{pageVersionCode}</Tag>
          </Typography.Text>
        ) : null}
        {mixedHint ? <Tag color="orange">混合标签树版本</Tag> : null}
        {behind ? (
          <Typography.Text type="warning" style={{ fontSize: 12 }}>
            {ctx?.clips_on_non_published_taxonomy} clip 非已发布契约
          </Typography.Text>
        ) : null}
        {ctx?.open_proposal_count ? (
          <Link to="/taxonomy?tab=proposals">
            {ctx.open_proposal_count} 条开放提案
          </Link>
        ) : null}
        <Link to="/taxonomy?tab=insights">标签覆盖率 →</Link>
      </Space>
      {pageMismatch ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8, marginBottom: 0 }}
          message={`本页契约 (${pageVersionCode}) 与当前已发布 (${publishedCode}) 不一致`}
        />
      ) : null}
    </div>
  )
}
