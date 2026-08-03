import { AuditOutlined } from '@ant-design/icons'
import { Form, Input, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { AuditLogEntry } from '../api/types'
import { ContentCard, FilterBar, PageHeader, PageStack } from '../components/ui'
import { AUDIT_ACTION_FILTER_OPTIONS, formatAuditAction } from '../utils/auditActionLabels'
import { formatAuditResourceType } from '../utils/uiLabels'

export function AdminAuditPage() {
  const [items, setItems] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [resourceType, setResourceType] = useState('')
  const pageSize = 30

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.listAuditLogs({
        action: action || undefined,
        resource_type: resourceType || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setItems(res.items)
      setTotal(res.total)
    } catch {
      message.error('加载审计日志失败')
    } finally {
      setLoading(false)
    }
  }, [action, resourceType, page])

  useEffect(() => {
    void load()
  }, [load])

  const columns: ColumnsType<AuditLogEntry> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 200,
      render: (v: string) => api.formatDateTime(v),
    },
    {
      title: '操作者',
      dataIndex: 'actor_username',
      width: 120,
      render: (v: string | null, row) => v || row.actor_id?.slice(0, 8) || '—',
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 160,
      render: (v: string) => <Tag>{formatAuditAction(v)}</Tag>,
    },
    {
      title: '资源',
      key: 'resource',
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {formatAuditResourceType(row.resource_type)}
          </Typography.Text>
          <Typography.Text code style={{ fontSize: 11 }}>
            {(row.resource_id || '').slice(0, 24)}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      ellipsis: true,
      render: (d: Record<string, unknown> | null) =>
        d ? (
          <Typography.Text code style={{ fontSize: 11 }}>
            {JSON.stringify(d).slice(0, 120)}
          </Typography.Text>
        ) : (
          '—'
        ),
    },
  ]

  return (
    <PageStack data-testid="admin-audit-page">
      <PageHeader
        title="审计日志"
        description="校核、数据集、标签树、扩增配方等写操作记录（管理员只读）。"
        icon={<AuditOutlined />}
      />

      <ContentCard
        title="筛选"
        toolbar={
          <FilterBar
            aria-label="审计操作筛选"
            value={action || 'all'}
            total={total}
            onChange={(v) => {
              setPage(1)
              setAction(v === 'all' ? '' : v)
            }}
            options={[
              { value: 'all', label: '全部操作' },
              ...AUDIT_ACTION_FILTER_OPTIONS,
            ]}
          />
        }
      >
        <Form layout="inline" style={{ marginBottom: 16 }}>
          <Form.Item label="资源类型">
            <Input
              placeholder="如：数据集快照"
              value={resourceType}
              onChange={(e) => {
                setPage(1)
                setResourceType(e.target.value)
              }}
              style={{ width: 200 }}
            />
          </Form.Item>
        </Form>

        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: setPage,
            showSizeChanger: false,
          }}
        />
      </ContentCard>
    </PageStack>
  )
}
