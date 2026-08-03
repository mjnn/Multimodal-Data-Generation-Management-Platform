import { RightOutlined } from '@ant-design/icons'
import { Space, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { TaxonomyLineageNode } from '../api/types'

const STATUS_COLOR: Record<string, string> = {
  draft: 'processing',
  published: 'success',
  archived: 'default',
}

interface TaxonomyLineageBarProps {
  versionId: string | null
  title?: string
}

export function TaxonomyLineageBar({ versionId, title = '版本血缘' }: TaxonomyLineageBarProps) {
  const [chain, setChain] = useState<TaxonomyLineageNode[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (vid: string) => {
    setLoading(true)
    try {
      const res = await api.getTaxonomyLineage(vid)
      setChain(res.lineage_chain)
    } catch {
      message.error('加载版本血缘失败')
      setChain([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (versionId) void load(versionId)
    else setChain([])
  }, [versionId, load])

  if (!versionId) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无已发布版本
      </Typography.Text>
    )
  }

  return (
    <div data-testid="taxonomy-lineage-bar">
      <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
        {title}
      </Typography.Text>
      {loading ? (
        <Typography.Text type="secondary">加载中…</Typography.Text>
      ) : chain.length === 0 ? (
        <Typography.Text type="secondary">无克隆链记录</Typography.Text>
      ) : (
        <Space wrap size={[4, 8]} align="center">
          {chain.map((node, idx) => (
            <Space key={node.id} size={4} align="center">
              {idx > 0 ? <RightOutlined style={{ fontSize: 10, color: '#999' }} /> : null}
              <Link to={`/taxonomy/${encodeURIComponent(node.id)}`}>
                <Tag color={STATUS_COLOR[node.status] ?? 'default'}>{node.version_code}</Tag>
              </Link>
            </Space>
          ))}
        </Space>
      )}
    </div>
  )
}
