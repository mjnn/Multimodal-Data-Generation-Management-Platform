import { FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'

import { Button, Space, Table, Tag, message } from 'antd'

import type { ColumnsType } from 'antd/es/table'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { api } from '../api'

import type { DatasetSnapshot, DatasetStatus } from '../api/types'

import { DatasetCreateWizard } from '../components/DatasetCreateWizard'

import { useAuth } from '../auth/AuthContext'

import { canManageDatasets } from '../auth/roles'

import { ContentCard, FilterBar, FromAuditBackLink, PageHeader, PageStack, useFromAudit } from '../components/ui'

import { useListQueryState } from '../hooks/useListQueryState'

const STATUS_COLOR: Record<DatasetStatus, string> = {
  building: 'processing',
  ready: 'success',
  failed: 'error',
  archived: 'default',
}

const STATUS_LABEL: Record<DatasetStatus, string> = {
  building: '构建中',
  ready: '就绪',
  failed: '失败',
  archived: '已删除',
}

type StatusFilter = 'all' | DatasetStatus

export function DatasetListPage() {
  const navigate = useNavigate()

  const { user } = useAuth()

  const canManage = canManageDatasets(user?.roles)

  const fromAudit = useFromAudit()

  const { status, page, setStatus, setPage } = useListQueryState({ defaultStatus: 'all' })

  const statusFilter = status as StatusFilter

  const [loading, setLoading] = useState(false)

  const [items, setItems] = useState<DatasetSnapshot[]>([])

  const [total, setTotal] = useState(0)

  const [createOpen, setCreateOpen] = useState(false)

  const pageSize = 20

  const loadList = useCallback(async () => {
    setLoading(true)

    try {
      const res = await api.listDatasets({
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })

      setItems(res.items)

      setTotal(res.total)
    } catch {
      message.error('加载数据集列表失败')
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter])

  useEffect(() => {
    void loadList()
  }, [loadList])

  const openDetail = useCallback(
    (id: string) => {
      navigate(`/datasets/${id}`)
    },
    [navigate],
  )

  const columns: ColumnsType<DatasetSnapshot> = useMemo(
    () => [
      { title: '名称', dataIndex: 'name' },
      {
        title: '状态',
        dataIndex: 'status',
        render: (v: DatasetStatus) => <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag>,
      },
      { title: 'Clip 数', dataIndex: 'clip_count', width: 90 },
      {
        title: '导出行数',
        dataIndex: 'line_count',
        width: 90,
        render: (v: number | null | undefined, row) => v ?? row.clip_count,
      },
      {
        title: '预设',
        dataIndex: 'export_preset',
        width: 88,
        render: (v: string | null | undefined) => (v === 'full' ? '完整' : '精简'),
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        width: 220,
        render: (v: string) => api.formatDateTime(v),
      },
      {
        title: '操作',
        key: 'action',
        width: 100,
        render: (_, row) => (
          <Button type="link" onClick={() => openDetail(row.id)}>
            详情
          </Button>
        ),
      },
    ],
    [openDetail],
  )

  return (
    <PageStack data-testid="dataset-list-page">
      <PageHeader
        title="数据集"
        description="从已校核 Clip 按取样条件筛选或随机抽样，构建训练数据集并导出 OSS 特征与目标。"
        icon={<FolderOpenOutlined />}
        extra={
          fromAudit || canManage ? (
            <Space wrap>
              <FromAuditBackLink />
              {canManage ? (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                  创建数据集
                </Button>
              ) : null}
            </Space>
          ) : undefined
        }
      />

      <ContentCard
        title="快照列表"
        noPadding
        toolbar={
          <FilterBar
            aria-label="数据集状态筛选"
            value={statusFilter}
            total={total}
            onChange={setStatus}
            options={[
              { value: 'all', label: '全部' },
              { value: 'building', label: '构建中' },
              { value: 'ready', label: '就绪' },
              { value: 'failed', label: '失败' },
            ]}
          />
        }
      >
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          rowClassName={() => 'clickable-row'}
          onRow={(row) => ({
            onClick: () => openDetail(row.id),
          })}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: false,
            onChange: setPage,
          }}
        />
      </ContentCard>

      <DatasetCreateWizard
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(snapshot) => navigate(`/datasets/${snapshot.id}`)}
      />
    </PageStack>
  )
}
