import { Button, Drawer, List, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { SimilarItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canBrowseTaxonomy } from '../auth/roles'
import { resolveMediaUrl } from '../utils/mediaUrl'

interface Props {
  open: boolean
  compositeId: string | null
  onClose: () => void
}

export function SimilarDrawer({ open, compositeId, onClose }: Props) {
  const [items, setItems] = useState<SimilarItem[]>([])
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { user } = useAuth()
  const canPropose = canBrowseTaxonomy(user?.roles)

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
            onClick={() => {
              const clipIds = [...new Set(items.map((i) => i.clip_id))]
              sessionStorage.setItem(
                'taxonomy_proposal_evidence_draft',
                [
                  `相似簇证据（锚点 ${compositeId?.slice(0, 24) ?? ''}…）`,
                  `相关 clip：${clipIds.slice(0, 12).join(', ')}${clipIds.length > 12 ? '…' : ''}`,
                  '请基于已发布标签树编辑提案树，并补充业务说明。',
                ].join('\n'),
              )
              message.info('已带入相似簇证据草稿，请在提案页完善并提交')
              navigate('/taxonomy?tab=proposals')
              onClose()
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
