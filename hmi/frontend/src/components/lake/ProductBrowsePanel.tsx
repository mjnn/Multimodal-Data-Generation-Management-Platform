import { Button, Space, Table, Tag, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import type { PlatformProductRecord } from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { ContentCard } from '../ui'
import { apiErrorMessage } from '../../utils/apiError'

function shortId(id: string | null | undefined, keep = 10): string {
  const v = String(id || '')
  if (!v) return '—'
  return v.length > keep + 2 ? `${v.slice(0, keep)}…` : v
}

function EllipsisCell({ text, type }: { text: string; type?: 'secondary' }) {
  return (
    <Typography.Text type={type} ellipsis={{ tooltip: text }} style={{ maxWidth: '100%' }}>
      {text}
    </Typography.Text>
  )
}

export function ProductBrowsePanel() {
  const { dataRevision } = useDataSourceMode()
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
  }, [load, dataRevision])

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
            className="lake-products-table"
            size="small"
            rowKey="cache_key"
            loading={loading}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            dataSource={items}
            tableLayout="fixed"
            scroll={{ x: 1080 }}
            columns={[
              {
                title: '产物',
                width: 220,
                ellipsis: true,
                render: (_: unknown, row: PlatformProductRecord) => {
                  const path = row.artifact_path || row.product_type || shortId(row.cache_key)
                  return (
                    <Space direction="vertical" size={0} style={{ maxWidth: '100%' }}>
                      <EllipsisCell text={path} />
                      {row.skipped ? <Tag>缓存命中</Tag> : null}
                    </Space>
                  )
                },
              },
              {
                title: '步骤',
                width: 140,
                ellipsis: true,
                render: (_: unknown, row: PlatformProductRecord) => (
                  <Space direction="vertical" size={0} style={{ maxWidth: '100%' }}>
                    <EllipsisCell text={row.op_title || row.op_id} />
                    <EllipsisCell text={row.op_id} type="secondary" />
                  </Space>
                ),
              },
              {
                title: '管线运行',
                width: 180,
                ellipsis: true,
                render: (_: unknown, row: PlatformProductRecord) =>
                  row.run_id ? (
                    <Space direction="vertical" size={0} style={{ maxWidth: '100%' }}>
                      <Typography.Text copyable={{ text: row.run_id }} ellipsis={{ tooltip: row.run_id }}>
                        {shortId(row.run_id, 12)}
                      </Typography.Text>
                      <EllipsisCell
                        text={`${row.data_type_title || row.data_type_id || '未知类型'}${
                          row.run_status ? ` · ${row.run_status}` : ''
                        }`}
                        type="secondary"
                      />
                    </Space>
                  ) : (
                    <Typography.Text type="secondary">未关联运行</Typography.Text>
                  ),
              },
              {
                title: '数据源',
                width: 160,
                ellipsis: true,
                render: (_: unknown, row: PlatformProductRecord) =>
                  row.sources?.length ? (
                    <EllipsisCell text={row.sources.map((src) => src.filename || shortId(src.source_id)).join('、')} />
                  ) : (
                    <Typography.Text type="secondary">未知</Typography.Text>
                  ),
              },
              {
                title: '产物血缘',
                width: 280,
                ellipsis: true,
                render: (_: unknown, row: PlatformProductRecord) => (
                  <Typography.Text
                    ellipsis={{ tooltip: row.lineage }}
                    style={{ maxWidth: '100%' }}
                    data-testid={`lake-product-lineage-${row.cache_key}`}
                  >
                    {row.lineage}
                  </Typography.Text>
                ),
              },
              {
                title: '时间',
                dataIndex: 'created_at',
                width: 168,
                ellipsis: true,
                render: (v: string | null | undefined) => v || '—',
              },
            ]}
          />
        )}
      </div>
    </ContentCard>
  )
}
