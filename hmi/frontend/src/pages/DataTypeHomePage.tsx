/**
 * 数据类型首页 `/`：列出已发布配方卡片，进入 `/w/:id` 工作区。
 * admin 可新建/编辑。这是平台内核 UI 入口，不再是旧的 Clip 总览。
 */
import { EditOutlined, PlusOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Col, Row, Space, Spin, Typography, message } from 'antd'
import { api } from '../api'
import type { DataTypeRecipe } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canManageDataTypes } from '../auth/roles'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { rememberDataTypeId } from '../context/DataTypeWorkspaceContext'

export function DataTypeHomePage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canEdit = canManageDataTypes(user?.roles)
  const [items, setItems] = useState<DataTypeRecipe[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await api.listDataTypes()
        if (!cancelled) setItems(res.items ?? [])
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '加载数据类型失败'
        message.error(msg)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <PageStack data-testid="data-type-home">
      <PageHeader
        title="选择数据类型"
        extra={
          canEdit ? (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              data-testid="dtype-new-btn"
              onClick={() => void navigate('/data-types/new')}
            >
              新建数据类型
            </Button>
          ) : null
        }
      />
      <ContentCard>
        <Typography.Paragraph type="secondary">
          先进入一个数据类型工作区。总览、检索和校核都只在该类型内，不会和其他类型的标签混在一起。
          {canEdit ? ' 管理员可新建配方：在数据源卡里加源，再用 SDK 组件编排管线。' : ''}
        </Typography.Paragraph>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin />
          </div>
        ) : (
          <Row gutter={[16, 16]} data-testid="data-type-cards">
            {items.map((dt) => (
              <Col xs={24} md={12} key={dt.id}>
                <Card
                  hoverable
                  data-testid={`data-type-card-${dt.id}`}
                  title={dt.title}
                  extra={
                    <Space size={8} onClick={(e) => e.stopPropagation()}>
                      <Typography.Text type="secondary">
                        {dt.status === 'published' ? '已发布' : dt.status}
                      </Typography.Text>
                      {canEdit ? (
                        <Button
                          size="small"
                          icon={<EditOutlined />}
                          data-testid={`dtype-edit-${dt.id}`}
                          onClick={() => void navigate(`/data-types/${encodeURIComponent(dt.id)}/edit`)}
                        >
                          编辑
                        </Button>
                      ) : null}
                    </Space>
                  }
                  onClick={() => {
                    rememberDataTypeId(dt.id)
                    void navigate(`/w/${dt.id}`)
                  }}
                >
                  <Typography.Paragraph>{dt.purpose}</Typography.Paragraph>
                  <Typography.Text type="secondary">负责人：{dt.owner}</Typography.Text>
                  <br />
                  <Typography.Text type="secondary">标签树：{dt.taxonomy_id}</Typography.Text>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </ContentCard>
    </PageStack>
  )
}
