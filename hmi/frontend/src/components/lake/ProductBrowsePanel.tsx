import { Button, Space, Table, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { PlatformProductRecord } from '../../api/types'
import { ContentCard } from '../ui'
import { apiErrorMessage } from '../../utils/apiError'

function shortId(id: string | null | undefined, keep = 10): string {
  const v = String(id || '')
  if (!v) return '—'
  return v.length > keep + 2 ? `${v.slice(0, keep)}…` : v
}

export function ProductBrowsePanel() {
  const [items, setItems] = useState<PlatformProductRecord[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.listPlatformProducts(200)
      setItems(res.items || [])
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载产物失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <ContentCard>
      <Typography.Paragraph type="secondary">
        浏览管线写出的产物。每条记录写明来自哪次管线运行的哪一步、以及原始数据源文件。
      </Typography.Paragraph>
      <div data-testid="lake-products-table">
        <Space style={{ marginBottom: 8 }}>
          <Button size="small" loading={loading} onClick={() => void load()} data-testid="lake-products-refresh">
            刷新
          </Button>
          <Typography.Text type="secondary">共 {items.length} 个产物</Typography.Text>
        </Space>
        {items.length === 0 && !loading ? (
          <Typography.Text type="secondary" data-testid="lake-products-empty">
            还没有产物。在「管线管理 → 数据选择」创建运行后，预处理步骤会写入这里。
          </Typography.Text>
        ) : (
          <Table
            size="small"
            rowKey="cache_key"
            loading={loading}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            dataSource={items}
            columns={[
              {
                title: '产物',
                width: 180,
                render: (_: unknown, row: PlatformProductRecord) => (
                  <Space direction="vertical" size={0}>
                    <Typography.Text>{row.artifact_path || row.product_type || shortId(row.cache_key)}</Typography.Text>
                    {row.skipped ? <Tag>缓存命中</Tag> : null}
                  </Space>
                ),
              },
              {
                title: '步骤',
                width: 160,
                render: (_: unknown, row: PlatformProductRecord) => (
                  <Space direction="vertical" size={0}>
                    <Typography.Text>{row.op_title || row.op_id}</Typography.Text>
                    <Typography.Text type="secondary">{row.op_id}</Typography.Text>
                  </Space>
                ),
              },
              {
                title: '管线运行',
                width: 200,
                render: (_: unknown, row: PlatformProductRecord) =>
                  row.run_id ? (
                    <Space direction="vertical" size={0}>
                      <Typography.Text copyable={{ text: row.run_id }}>{shortId(row.run_id, 12)}</Typography.Text>
                      <Typography.Text type="secondary">
                        {row.data_type_title || row.data_type_id || '未知类型'}
                        {row.run_status ? ` · ${row.run_status}` : ''}
                      </Typography.Text>
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">未关联运行</Typography.Text>
                  ),
              },
              {
                title: '数据源',
                width: 180,
                render: (_: unknown, row: PlatformProductRecord) =>
                  row.sources?.length ? (
                    <Space wrap size={[4, 4]}>
                      {row.sources.map((src) => (
                        <Tag key={src.source_id}>{src.filename || shortId(src.source_id)}</Tag>
                      ))}
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">未知</Typography.Text>
                  ),
              },
              {
                title: '产物血缘',
                render: (_: unknown, row: PlatformProductRecord) => (
                  <Typography.Paragraph
                    style={{ marginBottom: 0 }}
                    data-testid={`lake-product-lineage-${row.cache_key}`}
                  >
                    {row.lineage}
                  </Typography.Paragraph>
                ),
              },
              {
                title: '时间',
                dataIndex: 'created_at',
                width: 180,
                render: (v: string | null | undefined) => v || '—',
              },
            ]}
          />
        )}
      </div>
    </ContentCard>
  )
}
