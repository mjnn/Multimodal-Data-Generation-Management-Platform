import { AuditOutlined } from '@ant-design/icons'
import { Form, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { AuditLogEntry } from '../api/types'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { AuditLogDetailCell } from '../components/AuditLogDetailCell'
import { AUDIT_ACTION_FILTER_OPTIONS, formatAuditAction } from '../utils/auditActionLabels'
import {
  AUDIT_RESOURCE_TYPE_FILTER_OPTIONS,
  formatAuditResourceType,
} from '../utils/uiLabels'

type AuditPageCacheEntry = {
  items: AuditLogEntry[]
  total: number
}

function auditCacheKey(action: string, resourceType: string, page: number, pageSize: number): string {
  return `${action}\0${resourceType}\0${page}\0${pageSize}`
}

export function AdminAuditPage() {
  const [items, setItems] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(30)
  const [action, setAction] = useState('')
  const [resourceType, setResourceType] = useState('')
  const cacheRef = useRef(new Map<string, AuditPageCacheEntry>())

  const actionOptions = useMemo(
    () =>
      AUDIT_ACTION_FILTER_OPTIONS.map((opt) => ({
        value: opt.value,
        label: `${opt.label} (${opt.value})`,
      })),
    [],
  )

  const resourceTypeOptions = useMemo(
    () =>
      AUDIT_RESOURCE_TYPE_FILTER_OPTIONS.map((opt) => ({
        value: opt.value,
        label: `${opt.label} (${opt.value})`,
      })),
    [],
  )

  const load = useCallback(async () => {
    const key = auditCacheKey(action, resourceType, page, pageSize)
    const cached = cacheRef.current.get(key)
    if (cached) {
      setItems(cached.items)
      setTotal(cached.total)
      return
    }

    setLoading(true)
    try {
      const res = await api.listAuditLogs({
        action: action || undefined,
        resource_type: resourceType || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      cacheRef.current.set(key, { items: res.items, total: res.total })
      setItems(res.items)
      setTotal(res.total)
    } catch {
      message.error('加载审计日志失败')
    } finally {
      setLoading(false)
    }
  }, [action, resourceType, page, pageSize])

  useEffect(() => {
    void load()
  }, [load])

  const onTableChange = (pagination: TablePaginationConfig) => {
    if (pagination.pageSize != null && pagination.pageSize !== pageSize) {
      setPageSize(pagination.pageSize)
      setPage(1)
      return
    }
    if (pagination.current != null && pagination.current !== page) {
      setPage(pagination.current)
    }
  }

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
      width: 200,
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
      key: 'detail',
      width: 480,
      render: (_, row) => <AuditLogDetailCell row={row} />,
    },
  ]

  const tableScrollX = columns.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 160), 0)

  return (
    <PageStack data-testid="admin-audit-page">
      <PageHeader
        title="审计日志"
        description="校核、数据集、标签树、扩增配方等写操作记录（管理员只读）。"
        icon={<AuditOutlined />}
      />

      <ContentCard title="筛选">
        <Form layout="inline" style={{ marginBottom: 16, rowGap: 12 }}>
          <Form.Item label="操作">
            <Select
              allowClear
              showSearch
              placeholder="搜索或选择操作类型"
              aria-label="审计操作筛选"
              value={action || undefined}
              options={actionOptions}
              optionFilterProp="label"
              style={{ width: 280 }}
              onChange={(v) => {
                setPage(1)
                setAction(v ?? '')
              }}
            />
          </Form.Item>
          <Form.Item label="资源类型">
            <Select
              allowClear
              showSearch
              placeholder="搜索或选择资源类型"
              aria-label="审计资源类型筛选"
              value={resourceType || undefined}
              options={resourceTypeOptions}
              optionFilterProp="label"
              style={{ width: 280 }}
              onChange={(v) => {
                setPage(1)
                setResourceType(v ?? '')
              }}
            />
          </Form.Item>
          <Form.Item>
            <Typography.Text type="secondary">共 {total.toLocaleString()} 条</Typography.Text>
          </Form.Item>
        </Form>

        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          scroll={{ x: tableScrollX }}
          onChange={onTableChange}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '30', '50'],
            showTotal: (n) => `共 ${n.toLocaleString()} 条`,
          }}
        />
      </ContentCard>
    </PageStack>
  )
}
