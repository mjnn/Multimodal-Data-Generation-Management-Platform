import { FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'

import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
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

import type { DatasetSnapshot, DatasetStatus, DatasetPoolClipItem, TaxonomyNodeDetail, DatasetExportRecommendation, TaxonomyVersionDistribution, TaxonomyVersion } from '../api/types'

import { DatasetLabelFilterForm, type LabelFilters } from '../components/DatasetLabelFilterForm'
import { TaxonomyContextBar } from '../components/TaxonomyContextBar'

import { useAuth } from '../auth/AuthContext'

import { canManageDatasets } from '../auth/roles'

import { ContentCard, FilterBar, PageHeader, PageStack } from '../components/ui'

import { useDebouncedValue } from '../hooks/useDebouncedValue'

import { useListQueryState } from '../hooks/useListQueryState'

import { buildFilterJson, cleanLabelFilters } from '../utils/datasetFilter'
import { formatTaxonomyVersionLabel } from '../utils/taxonomyDisplay'

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

  const [previewReadyCount, setPreviewReadyCount] = useState<number | null>(null)
  const [previewExceedsLimit, setPreviewExceedsLimit] = useState(false)
  const [previewTaxonomyWarning, setPreviewTaxonomyWarning] = useState<string | null>(null)
  const [exportRecommendation, setExportRecommendation] = useState<DatasetExportRecommendation | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [taxonomyVersionDistribution, setTaxonomyVersionDistribution] = useState<
    TaxonomyVersionDistribution[] | null
  >(null)
  const [taxonomyVersions, setTaxonomyVersions] = useState<TaxonomyVersion[]>([])
  const [poolModalOpen, setPoolModalOpen] = useState(false)

  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])

  const [labelFilters, setLabelFilters] = useState<LabelFilters>({})

  const [form] = Form.useForm()

  const pageSize = 20



  const debouncedLabelFilters = useDebouncedValue(labelFilters, 300)

  const exportPreset = Form.useWatch('export_preset', form) as 'minimal' | 'full' | undefined
  const balanceByLabel = Form.useWatch('balance_by_label', form) as string | undefined
  const minPerClass = Form.useWatch('min_per_class', form) as number | undefined
  const maxPerClass = Form.useWatch('max_per_class', form) as number | undefined
  const sampleSize = Form.useWatch('sample_size', form) as number | null | undefined
  const includeParquet = Form.useWatch('include_parquet', form) as boolean | undefined
  const previewName = Form.useWatch('name', form) as string | undefined
  const taxonomyLock = Form.useWatch('taxonomy_lock', form) as string | undefined

  const previewFilterExtra = useMemo(
    () => ({
      export_preset: exportPreset ?? 'minimal',
      include_parquet: Boolean(includeParquet),
      ...(taxonomyLock && taxonomyLock !== 'default'
        ? { taxonomy_version_id: taxonomyLock }
        : {}),
      ...(balanceByLabel?.trim() ? { balance_by_label: balanceByLabel.trim() } : {}),
      ...(minPerClass != null && minPerClass > 0
        ? { min_per_class: minPerClass, oversample_policy: 'duplicate_to_min' as const }
        : {}),
      ...(maxPerClass != null && maxPerClass > 0 ? { max_per_class: maxPerClass } : {}),
    }),
    [exportPreset, balanceByLabel, minPerClass, maxPerClass, includeParquet, taxonomyLock],
  )

  const balanceDimensionOptions = useMemo(
    () =>
      taxonomyNodes
        .filter((n) => n.is_active !== false)
        .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
        .map((node) => ({
          value: node.label_id,
          label: `${node.name} (${node.label_id})`,
        })),
    [taxonomyNodes],
  )



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
    void api.listTaxonomyVersions().then(setTaxonomyVersions).catch(() => setTaxonomyVersions([]))

  }, [createOpen, loadTaxonomy])



  useEffect(() => {

    if (!createOpen) return

    setPreviewLoading(true)

    void api
      .previewDataset({
        name: previewName?.trim() || 'preview',
        filter_json: buildFilterJson(debouncedLabelFilters, sampleSize, previewFilterExtra),
        export_preset: exportPreset ?? 'minimal',
      })
      .then((res) => {
        setPreviewError(null)
        setPreviewPool(res.pool_count)
        setPreviewCount(res.candidate_count)
        setPreviewReadyCount(res.dataset_ready_count ?? null)
        setPreviewExceedsLimit(Boolean(res.exceeds_clip_limit))
        setPreviewTaxonomyWarning(res.taxonomy_version_warning ?? null)
        setExportRecommendation(res.export_recommendation ?? null)
        setTaxonomyVersionDistribution(res.taxonomy_version_distribution ?? null)
        setPoolItems(res.pool_items ?? [])
        setPoolItemsTruncated(Boolean(res.pool_items_truncated))
      })
      .catch((err: unknown) => {
        setPreviewError(apiErrorMessage(err, '预览失败'))
        setPreviewPool(null)
        setPreviewCount(null)
        setPreviewReadyCount(null)
        setPreviewExceedsLimit(false)
        setPreviewTaxonomyWarning(null)
        setExportRecommendation(null)
        setTaxonomyVersionDistribution(null)
        setPoolItems([])
        setPoolItemsTruncated(false)
      })
      .finally(() => setPreviewLoading(false))
  }, [createOpen, debouncedLabelFilters, sampleSize, previewFilterExtra, exportPreset, previewName, taxonomyLock])

  const applyExportRecommendation = () => {
    if (!exportRecommendation) return
    const patch: Record<string, unknown> = {
      export_preset: exportRecommendation.suggested_export_preset,
      include_parquet: exportRecommendation.suggested_include_parquet,
    }
    if (exportRecommendation.suggested_sample_size != null) {
      patch.sample_size = exportRecommendation.suggested_sample_size
    }
    form.setFieldsValue(patch)
    message.success('已应用导出建议')
  }



  const openCreate = () => {

    form.resetFields()

    form.setFieldsValue({ sample_size: undefined, export_preset: 'minimal', include_parquet: false, taxonomy_lock: 'default' })

    setLabelFilters({})

    setPreviewPool(null)

    setPreviewCount(null)
    setPreviewTaxonomyWarning(null)
    setExportRecommendation(null)
    setPreviewError(null)

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
        filter_json: buildFilterJson(labelFilters, sample, previewFilterExtra),
        export_preset: (values.export_preset as 'minimal' | 'full') ?? 'minimal',
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

        styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto', paddingTop: 8 } }}

      >

        <TaxonomyContextBar
          mixedHint={
            taxonomyVersionDistribution != null && taxonomyVersionDistribution.length > 1
          }
        />

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

          <div
            data-testid="dataset-preview-panel"
            style={{
              marginBottom: 16,
              padding: '12px 16px',
              borderRadius: 8,
              border: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
              background: 'var(--ant-color-fill-quaternary, #fafafa)',
            }}
          >
            <Typography.Text strong>符合筛选条件的 Clip</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
              候选池：有 AI 标签与向量、且匹配下方标签条件的 clip（本地模式含校核中及尚未入库的 clip）。
              「可导出」指全部字段校核完成、可正式纳入数据集的数量。
            </Typography.Paragraph>
            <Space wrap align="center">
              <Typography.Text>
                {previewLoading
                  ? '计算中…'
                  : previewPool != null
                    ? `候选 ${previewPool} 条`
                    : previewError
                      ? '—'
                      : '等待预览…'}
              </Typography.Text>
              {previewReadyCount != null && !previewLoading ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  可导出（已全部校核）{previewReadyCount} 条
                </Typography.Text>
              ) : null}
              {sampleSize != null && sampleSize > 0 && previewCount != null && !previewLoading ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  随机取样后约 {previewCount} 条
                </Typography.Text>
              ) : null}
              <Button
                type="link"
                size="small"
                disabled={previewLoading || previewPool == null || previewPool === 0}
                onClick={() => setPoolModalOpen(true)}
              >
                查看列表
              </Button>
            </Space>
            {!previewLoading && previewPool === 0 ? (
              <Typography.Paragraph type="warning" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                当前无匹配 clip：请调整标签条件，或确认 clip 已完成校核与向量导出。
              </Typography.Paragraph>
            ) : null}
            {previewTaxonomyWarning ? (
              <Alert type="warning" showIcon style={{ marginTop: 8 }} message={previewTaxonomyWarning} />
            ) : null}
            {taxonomyVersionDistribution && taxonomyVersionDistribution.length > 0 ? (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
                标签树版本分布：
                {taxonomyVersionDistribution.map((d) => (
                  <Tag key={d.taxonomy_version_id ?? 'mixed'} style={{ marginInlineStart: 4 }}>
                    {d.taxonomy_version_code ?? '未知'} · {d.clip_count}
                  </Tag>
                ))}
              </Typography.Paragraph>
            ) : null}
            {previewExceedsLimit ? (
              <Typography.Paragraph type="warning" style={{ marginTop: 8, marginBottom: 0 }}>
                匹配 clip 超过 10,000 条上限，请缩小标签条件或启用随机取样后分批创建。
              </Typography.Paragraph>
            ) : null}
            {previewError ? (
              <Alert type="error" showIcon style={{ marginTop: 8 }} message="预览失败" description={previewError} />
            ) : null}
            {previewLoading ? (
              <Alert type="info" showIcon style={{ marginTop: 8 }} message="正在计算导出建议…" />
            ) : exportRecommendation ? (
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 8 }}
                message="导出建议"
                data-testid="export-recommendation"
                description={
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      约 {exportRecommendation.stats.clip_count} clip ·{' '}
                      {exportRecommendation.stats.line_count} 行 ·{' '}
                      {exportRecommendation.stats.label_column_count} 个标签列
                      {exportRecommendation.estimates.jsonl_mb_estimated != null
                        ? ` · JSONL ≈ ${exportRecommendation.estimates.jsonl_mb_estimated} MB`
                        : ''}
                    </Typography.Text>
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {exportRecommendation.reasons.map((r) => (
                        <li key={r}>
                          <Typography.Text style={{ fontSize: 12 }}>{r}</Typography.Text>
                        </li>
                      ))}
                    </ul>
                    <Space wrap>
                      <Typography.Text style={{ fontSize: 12 }}>
                        建议：{exportRecommendation.suggested_export_preset === 'full' ? '完整包' : '精简'}
                        {exportRecommendation.suggested_include_parquet ? ' + Parquet' : ''}
                        {exportRecommendation.suggested_sample_size
                          ? ` · 取样 ${exportRecommendation.suggested_sample_size}`
                          : ''}
                      </Typography.Text>
                      <Button type="link" size="small" onClick={applyExportRecommendation}>
                        采用建议
                      </Button>
                    </Space>
                  </Space>
                }
              />
            ) : null}
          </div>

          <Form.Item
            name="taxonomy_lock"
            label="标签树契约"
            initialValue="default"
            extra="默认纳入各 clip 校核时的标签树版本（R10）；锁定后仅匹配指定版本。"
          >
            <Select
              options={[
                { value: 'default', label: '默认（各 clip 校核版本）' },
                ...taxonomyVersions.map((v) => ({
                  value: v.id,
                  label: `锁定：${formatTaxonomyVersionLabel(v)}`,
                })),
              ]}
            />
          </Form.Item>

          <Form.Item
            name="export_preset"
            label="导出预设"
            initialValue="minimal"
            extra="精简：仅特征+标签+元数据；完整：另含解析原始数据（体积更大）。"
          >
            <Select
              options={[
                { value: 'minimal', label: '精简（推荐）' },
                { value: 'full', label: '完整（含 parsed 媒体）' },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="include_parquet"
            valuePropName="checked"
            initialValue={false}
            extra="额外生成 Parquet（特征向量列 + 扁平标签列），便于 pandas/Spark 读取；JSONL 仍保留。"
          >
            <Checkbox>同时导出 Parquet</Checkbox>
          </Form.Item>

          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            类别平衡（可选 · M8）
          </Typography.Text>
          <Form.Item
            name="balance_by_label"
            label="平衡维度"
            extra="从已发布标签树选择标签；按该标签取值分组后做过采样/欠采样。"
          >
            <Select
              allowClear
              showSearch
              placeholder="选择标签，例如 day_period"
              optionFilterProp="label"
              disabled={balanceDimensionOptions.length === 0}
              notFoundContent={
                balanceDimensionOptions.length === 0 ? '暂无已发布标签树' : '无匹配标签'
              }
              options={balanceDimensionOptions}
            />
          </Form.Item>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="min_per_class" label="每类最少行数" style={{ flex: 1 }}>
              <InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="过采样" />
            </Form.Item>
            <Form.Item name="max_per_class" label="每类最多行数" style={{ flex: 1 }}>
              <InputNumber min={1} max={10000} style={{ width: '100%' }} placeholder="欠采样" />
            </Form.Item>
          </Space>

          <Typography.Text strong style={{ display: 'block', marginBottom: 8, marginTop: 8 }}>
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
              title: 'Clip ID',
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


