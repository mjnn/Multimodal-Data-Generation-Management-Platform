import { Button, Drawer, List, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { SimilarItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canManageDatasets } from '../auth/roles'
import { resolveMediaUrl } from '../utils/mediaUrl'

interface Props {
  open: boolean
  compositeId: string | null
  onClose: () => void
}

export function SimilarDrawer({ open, compositeId, onClose }: Props) {
  const [items, setItems] = useState<SimilarItem[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const navigate = useNavigate()
  const { user } = useAuth()
  const canPropose = canManageDatasets(user?.roles)

  useEffect(() => {
    if (!open || !compositeId) return
    setLoading(true)
    api
      .findSimilar(compositeId)
      .then(setItems)
      .finally(() => setLoading(false))
  }, [open, compositeId])

  return (
    <Drawer
      title="相似时刻（向量检索 Mock）"
      open={open}
      onClose={onClose}
      width={420}
      extra={
        canPropose && items.length > 0 ? (
          <Button
            type="link"
            loading={creating}
            onClick={() => {
              setCreating(true)
              void api
                .createTaxonomyProposal({
                  title: `相似簇提案 · ${compositeId?.slice(0, 16) ?? 'clip'}`,
                  proposal_type: 'scene_cluster',
                  evidence: {
                    source: 'similar',
                    anchor_composite_id: compositeId,
                    clip_ids: [...new Set(items.map((i) => i.clip_id))],
                  },
                })
                .then(() => message.success('已创建标签树提案'))
                .catch(() => message.error('创建提案失败'))
                .finally(() => setCreating(false))
            }}
          >
            建议补充标签树
          </Button>
        ) : null
      }
    >
      <List
        loading={loading}
        dataSource={items}
        renderItem={(item, i) => (
          <List.Item
            style={{ cursor: 'pointer' }}
            onClick={() => {
              navigate(`/clips/${encodeURIComponent(item.clip_id)}?t=${item.timestamp_ns}`)
              onClose()
            }}
          >
            <List.Item.Meta
              avatar={
                <img src={resolveMediaUrl(item.preview_url)} alt="" style={{ width: 72, height: 48, objectFit: 'cover' }} />
              }
              title={
                <Space>
                  <Tag color={item.score > 0.9 ? 'green' : item.score > 0.8 ? 'orange' : 'red'}>
                    {(item.score * 100).toFixed(1)}%
                  </Tag>
                  <Typography.Text type="secondary">#{i + 1}</Typography.Text>
                  <Tag>{item.camera}</Tag>
                </Space>
              }
              description={
                <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ margin: 0, fontSize: 12 }}>
                  {item.label_text}
                </Typography.Paragraph>
              }
            />
          </List.Item>
        )}
      />
    </Drawer>
  )
}
