import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Col, Row, Spin, Typography, message } from 'antd'
import { api } from '../api'
import type { DataTypeRecipe } from '../api/types'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { rememberDataTypeId } from '../context/DataTypeWorkspaceContext'

export function DataTypeHomePage() {
  const navigate = useNavigate()
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
      <PageHeader title="选择数据类型" />
      <ContentCard>
        <Typography.Paragraph type="secondary">
          先进入一个数据类型工作区。总览、检索和校核都只在该类型内，不会和其他类型的标签混在一起。
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
                  extra={dt.status === 'published' ? '已发布' : dt.status}
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
