import { FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'

import {

  Button,

  Form,

  Input,

  InputNumber,

  Modal,

  Space,

  Table,

  Tag,

  Typography,

  message,

} from 'antd'

import type { ColumnsType } from 'antd/es/table'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { api } from '../api'
import { apiErrorMessage } from '../utils/apiError'

import type { DatasetSnapshot, DatasetStatus, DatasetPoolClipItem, TaxonomyNodeDetail } from '../api/types'

import { DatasetLabelFilterForm, type LabelFilters } from '../components/DatasetLabelFilterForm'

import { useAuth } from '../auth/AuthContext'

import { canManageDatasets } from '../auth/roles'

import { ContentCard, FilterBar, PageHeader, PageStack } from '../components/ui'

import { useDebouncedValue } from '../hooks/useDebouncedValue'

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



function cleanLabelFilters(labelFilters: LabelFilters): LabelFilters {

  return Object.fromEntries(

    Object.entries(labelFilters).filter(([, v]) => v !== '' && v != null),

  ) as LabelFilters

}



function buildFilterJson(
  labelFilters: LabelFilters,
  sampleSize?: number | null,
): {
  review_status: 'reviewed'
  include_pending_review: boolean
  label_filters?: LabelFilters
  sample_size?: number
} {
  const cleaned = cleanLabelFilters(labelFilters)
  const filter: {
    review_status: 'reviewed'
    include_pending_review: boolean
    label_filters?: LabelFilters
    sample_size?: number
  } = {
    review_status: 'reviewed',
    include_pending_review: false,
  }

  if (Object.keys(cleaned).length > 0) {

    filter.label_filters = cleaned

  }

  if (sampleSize != null && sampleSize > 0) {

    filter.sample_size = sampleSize

  }

  return filter

}



export function DatasetListPage() {

  const navigate = useNavigate()

  const { user } = useAuth()

  const canManage = canManageDatasets(user?.roles)



  const { status, page, setStatus, setPage } = useListQueryState({ defaultStatus: 'all' })

  const statusFilter = status as StatusFilter



  const [loading, setLoading] = useState(false)

  const [items, setItems] = useState<DatasetSnapshot[]>([])

  const [total, setTotal] = useState(0)

  const [createOpen, setCreateOpen] = useState(false)

  const [creating, setCreating] = useState(false)

  const [previewPool, setPreviewPool] = useState<number | null>(null)

  const [previewCount, setPreviewCount] = useState<number | null>(null)

  const [previewLoading, setPreviewLoading] = useState(false)

  const [poolItems, setPoolItems] = useState<DatasetPoolClipItem[]>([])

  const [poolItemsTruncated, setPoolItemsTruncated] = useState(false)

  const [poolModalOpen, setPoolModalOpen] = useState(false)

  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])

  const [labelFilters, setLabelFilters] = useState<LabelFilters>({})

  const [form] = Form.useForm()

  const pageSize = 20



  const debouncedLabelFilters = useDebouncedValue(labelFilters, 300)

  const sampleSize = Form.useWatch('sample_size', form) as number | null | undefined



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



  const loadTaxonomy = useCallback(async () => {

    try {

      const versions = await api.listTaxonomyVersions()

      const published = versions.find((v) => v.status === 'published')

      if (!published) {

        setTaxonomyNodes([])

        return

      }

      const tree = await api.getTaxonomyTree(published.id)

      setTaxonomyNodes(tree.nodes)

    } catch {

      setTaxonomyNodes([])

    }

  }, [])



  useEffect(() => {

    if (!createOpen) return

    void loadTaxonomy()

  }, [createOpen, loadTaxonomy])



  useEffect(() => {

    if (!createOpen) return

    setPreviewLoading(true)

    void api

      .previewDataset({

        filter_json: buildFilterJson(debouncedLabelFilters, sampleSize),

      })

      .then((res) => {

        setPreviewPool(res.pool_count)

        setPreviewCount(res.candidate_count)

        setPoolItems(res.pool_items ?? [])

        setPoolItemsTruncated(Boolean(res.pool_items_truncated))

      })

      .catch(() => {

        setPreviewPool(null)

        setPreviewCount(null)

        setPoolItems([])

        setPoolItemsTruncated(false)

      })

      .finally(() => setPreviewLoading(false))

  }, [createOpen, debouncedLabelFilters, sampleSize])



  const openCreate = () => {

    form.resetFields()

    form.setFieldsValue({ sample_size: undefined })

    setLabelFilters({})

    setPreviewPool(null)

    setPreviewCount(null)

    setPoolItems([])

    setPoolModalOpen(false)

    setCreateOpen(true)

  }



  const submitCreate = async () => {

    const values = await form.validateFields()

    const sample = values.sample_size as number | undefined

    setCreating(true)

    try {

      const snapshot = await api.createDataset({

        name: values.name.trim(),

        description: values.description?.trim() || undefined,

        filter_json: buildFilterJson(labelFilters, sample),

      })

      message.success('数据集创建成功，正在构建')

      setCreateOpen(false)

      navigate(`/datasets/${snapshot.id}`)

    } catch (err: unknown) {

      message.error(apiErrorMessage(err, '创建失败'))

    } finally {

      setCreating(false)

    }

  }



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

      { title: 'Clip 数', dataIndex: 'clip_count', width: 100 },

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



  const activeLabelFilterCount = Object.keys(cleanLabelFilters(labelFilters)).length



  const previewHint = (() => {

    if (previewLoading) return '，正在估算匹配数量…'

    if (previewPool == null || previewCount == null) return ''

    if (sampleSize != null && sampleSize > 0 && previewPool > previewCount) {

      return `，候选池 ${previewPool} 条，随机取样 ${previewCount} 条`

    }

    return `，当前匹配约 ${previewCount} 条`

  })()



  return (

    <PageStack data-testid="dataset-list-page">

      <PageHeader

        title="数据集"

        description="从已校核 Clip 按取样条件筛选或随机抽样，构建训练数据集并导出 OSS 特征与目标。"

        icon={<FolderOpenOutlined />}

        extra={

          canManage ? (

            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>

              创建数据集

            </Button>

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



      <Modal

        title="创建数据集快照"

        open={createOpen}

        onCancel={() => setCreateOpen(false)}

        onOk={() => void submitCreate()}

        confirmLoading={creating}

        okText="创建"

        width={720}

      >

        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>

          <Form.Item

            name="name"

            label="名称"

            rules={[{ required: true, message: '请输入名称' }]}

          >

            <Input placeholder="例如 training_v1" />

          </Form.Item>

          <Form.Item name="description" label="描述">

            <Input.TextArea rows={2} placeholder="可选" />

          </Form.Item>



          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>

            取样条件 · 标签

          </Typography.Text>

          <DatasetLabelFilterForm

            nodes={taxonomyNodes}

            value={labelFilters}

            onChange={setLabelFilters}

          />



          <Form.Item

            name="sample_size"

            label="随机取样数量（可选）"

            extra="在符合标签条件的 Clip 中随机抽取指定数量；留空则纳入全部匹配 Clip。"

            style={{ marginTop: 16 }}

          >

            <InputNumber min={1} max={10000} style={{ width: '100%' }} placeholder="例如 100" />

          </Form.Item>



          <Form.Item
            label="满足条件的已校核 Clip"
            extra="按上方标签条件筛选，且已完成字段校核的 clip 数量；可点击查看列表并跳转详情。"
          >
            <Space wrap>
              <Typography.Text>
                {previewLoading ? '计算中…' : previewPool != null ? `${previewPool} 条` : '—'}
              </Typography.Text>
              <Button
                type="link"
                size="small"
                disabled={previewLoading || !previewPool}
                onClick={() => setPoolModalOpen(true)}
              >
                查看列表
              </Button>
              {sampleSize != null && sampleSize > 0 && previewCount != null ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  随机取样后约 {previewCount} 条
                </Typography.Text>
              ) : null}
            </Space>
          </Form.Item>



          <Typography.Paragraph type="secondary" style={{ marginTop: 0, marginBottom: 0 }}>

            默认仅纳入已校核 clip

            {previewHint}

            {activeLabelFilterCount > 0 ? `（${activeLabelFilterCount} 个标签条件）` : ''}

          </Typography.Paragraph>

        </Form>

      </Modal>



      <Modal
        title="已校核匹配 Clip"
        open={poolModalOpen}
        onCancel={() => setPoolModalOpen(false)}
        footer={null}
        width={720}
      >
        {poolItemsTruncated ? (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            列表最多展示 {poolItems.length} 条，共 {previewPool ?? poolItems.length} 条匹配。
          </Typography.Paragraph>
        ) : null}
        <Table
          rowKey={(r) => `${r.clip_id}:${r.run_id}`}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true }}
          dataSource={poolItems}
          columns={[
            {
              title: 'Clip',
              dataIndex: 'clip_dir_name',
              ellipsis: true,
              render: (name: string, row) => (
                <Typography.Text className="mono" style={{ fontSize: 12 }}>
                  {name || row.clip_id.slice(0, 24)}
                </Typography.Text>
              ),
            },
            {
              title: 'clip_id',
              dataIndex: 'clip_id',
              ellipsis: true,
              render: (v: string) => (
                <Typography.Text code style={{ fontSize: 11 }}>
                  {v.slice(0, 20)}…
                </Typography.Text>
              ),
            },
            {
              title: '操作',
              key: 'action',
              width: 88,
              render: (_, row) => (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    setPoolModalOpen(false)
                    setCreateOpen(false)
                    navigate(
                      `/clips/${encodeURIComponent(row.clip_id)}?run_id=${encodeURIComponent(row.run_id)}`,
                    )
                  }}
                >
                  详情
                </Button>
              ),
            },
          ]}
        />
      </Modal>

    </PageStack>

  )

}


