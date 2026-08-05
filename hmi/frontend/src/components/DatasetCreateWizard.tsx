import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { apiErrorMessage } from '../utils/apiError'
import type {
  DatasetExportRecommendation,
  DatasetPoolClipItem,
  DatasetSnapshot,
  LabelDistributionConfig,
  TaxonomyNodeDetail,
  TaxonomyVersion,
  TaxonomyVersionDistribution,
} from '../api/types'
import {
  DatasetLabelDistributionForm,
  validateLabelDistribution,
} from './DatasetLabelDistributionForm'
import { TaxonomyContextBar } from './TaxonomyContextBar'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { buildFilterJson } from '../utils/datasetFilter'
import { formatTaxonomyVersionLabel } from '../utils/taxonomyDisplay'

const WIZARD_STEPS = [
  { title: '基本信息' },
  { title: '标签值分布' },
  { title: '取样与平衡' },
  { title: '导出配置' },
  { title: '确认创建' },
]

type Props = {
  open: boolean
  onClose: () => void
  onCreated: (snapshot: DatasetSnapshot) => void
}

export function DatasetCreateWizard({ open, onClose, onCreated }: Props) {
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
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
  const [labelDistribution, setLabelDistribution] = useState<LabelDistributionConfig | null>(null)

  const [form] = Form.useForm()

  const debouncedLabelDistribution = useDebouncedValue(labelDistribution, 300)
  const exportPreset = Form.useWatch('export_preset', form) as 'minimal' | 'full' | undefined
  const balanceByLabel = Form.useWatch('balance_by_label', form) as string | undefined
  const minPerClass = Form.useWatch('min_per_class', form) as number | undefined
  const maxPerClass = Form.useWatch('max_per_class', form) as number | undefined
  const sampleSize = Form.useWatch('sample_size', form) as number | null | undefined
  const includeParquet = Form.useWatch('include_parquet', form) as boolean | undefined
  const previewName = Form.useWatch('name', form) as string | undefined
  const taxonomyLock = Form.useWatch('taxonomy_lock', form) as string | undefined
  const description = Form.useWatch('description', form) as string | undefined

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

  const distributionSummary = useMemo(() => {
    if (!labelDistribution?.label_id) return '未配置（纳入全部校核 clip）'
    const node = taxonomyNodes.find((n) => n.label_id === labelDistribution.label_id)
    const name = node ? `${node.name} (${node.label_id})` : labelDistribution.label_id
    if (labelDistribution.kind === 'enum') {
      const parts = Object.entries(labelDistribution.weights)
        .filter(([, w]) => w != null && w > 0)
        .map(([k, w]) => `${k} ${w}%`)
      return parts.length > 0 ? `${name}：${parts.join('、')}` : `${name}：各枚举值随机分配`
    }
    const parts = labelDistribution.buckets
      .filter((b) => b.weight != null && b.weight > 0)
      .map((b) =>
        b.match === 'exact'
          ? `"${b.value}" ${b.weight}%`
          : `[${b.min || '…'}, ${b.max || '…'}] ${b.weight}%`,
      )
    return parts.length > 0 ? `${name}：${parts.join('；')}` : `${name}：未配置取值`
  }, [labelDistribution, taxonomyNodes])

  useEffect(() => {
    if (!open) return
    setStep(0)
    form.resetFields()
    form.setFieldsValue({
      sample_size: undefined,
      export_preset: 'minimal',
      include_parquet: false,
      taxonomy_lock: 'default',
    })
    setLabelDistribution(null)
    setPreviewPool(null)
    setPreviewCount(null)
    setPreviewTaxonomyWarning(null)
    setExportRecommendation(null)
    setPreviewError(null)
    setPoolItems([])
    setPoolModalOpen(false)
  }, [open, form])

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
    if (!open) return
    void loadTaxonomy()
    void api.listTaxonomyVersions().then(setTaxonomyVersions).catch(() => setTaxonomyVersions([]))
  }, [open, loadTaxonomy])

  useEffect(() => {
    if (!open || step < 1) return
    setPreviewLoading(true)
    void api
      .previewDataset({
        name: previewName?.trim() || 'preview',
        filter_json: buildFilterJson(debouncedLabelDistribution, sampleSize, previewFilterExtra),
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
  }, [
    open,
    step,
    debouncedLabelDistribution,
    sampleSize,
    previewFilterExtra,
    exportPreset,
    previewName,
    taxonomyLock,
  ])

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

  const goNext = async () => {
    if (step === 0) {
      try {
        await form.validateFields(['name'])
      } catch {
        return
      }
    }
    if (step === 1) {
      const err = validateLabelDistribution(labelDistribution)
      if (err) {
        message.warning(err)
        return
      }
    }
    if (step === 1 && previewPool === 0 && !previewLoading) {
      message.warning('当前候选池为空，建议调整标签值分布或确认 clip 已校核')
    }
    setStep((s) => Math.min(s + 1, WIZARD_STEPS.length - 1))
  }

  const goPrev = () => setStep((s) => Math.max(s - 1, 0))

  const submitCreate = async () => {
    const values = await form.validateFields()
    const sample = values.sample_size as number | undefined
    if (previewExceedsLimit) {
      message.error('匹配 clip 超过上限，请缩小条件或启用随机取样')
      return
    }
    setCreating(true)
    try {
      const snapshot = await api.createDataset({
        name: values.name.trim(),
        description: values.description?.trim() || undefined,
        filter_json: buildFilterJson(labelDistribution, sample, previewFilterExtra),
        export_preset: (values.export_preset as 'minimal' | 'full') ?? 'minimal',
      })
      message.success('数据集创建成功，正在构建')
      onClose()
      onCreated(snapshot)
    } catch (err: unknown) {
      message.error(apiErrorMessage(err, '创建失败'))
    } finally {
      setCreating(false)
    }
  }

  const taxonomyLockLabel = useMemo(() => {
    if (!taxonomyLock || taxonomyLock === 'default') return '默认（各 clip 校核版本）'
    const v = taxonomyVersions.find((item) => item.id === taxonomyLock)
    return v ? `锁定：${formatTaxonomyVersionLabel(v)}` : taxonomyLock
  }, [taxonomyLock, taxonomyVersions])

  const balanceLabel = useMemo(() => {
    if (!balanceByLabel?.trim()) return '—'
    const node = taxonomyNodes.find((n) => n.label_id === balanceByLabel)
    return node ? `${node.name} (${node.label_id})` : balanceByLabel
  }, [balanceByLabel, taxonomyNodes])

  const previewPanel = (
    <div
      data-testid="dataset-preview-panel"
      style={{
        marginTop: 16,
        padding: '12px 16px',
        borderRadius: 8,
        border: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
        background: 'var(--ant-color-fill-quaternary, #fafafa)',
      }}
    >
      <Typography.Text strong>Clip 预览</Typography.Text>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
        候选池为已校核 clip；配置标签值分布与取样数量后，「约 N 条」为按占比抽样后的估算。
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
          匹配 clip 超过 10,000 条上限，请缩小标签条件或启用随机取样。
        </Typography.Paragraph>
      ) : null}
      {previewError ? (
        <Alert type="error" showIcon style={{ marginTop: 8 }} message="预览失败" description={previewError} />
      ) : null}
      {previewLoading ? (
        <Alert type="info" showIcon style={{ marginTop: 8 }} message="正在计算导出建议…" />
      ) : exportRecommendation && step >= 3 ? (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 8 }}
          message="导出建议"
          data-testid="export-recommendation"
          description={
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                约 {exportRecommendation.stats.clip_count} clip · {exportRecommendation.stats.line_count} 行 ·{' '}
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
  )

  const stepContent = (() => {
    switch (step) {
      case 0:
        return (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              先为数据集快照取一个名称，便于后续在列表中识别。
            </Typography.Paragraph>
            <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="例如 training_v1" autoFocus />
            </Form.Item>
            <Form.Item name="description" label="描述">
              <Input.TextArea rows={3} placeholder="可选：用途、来源、备注…" />
            </Form.Item>
          </>
        )
      case 1:
        return (
          <>
            <TaxonomyContextBar
              mixedHint={
                taxonomyVersionDistribution != null && taxonomyVersionDistribution.length > 1
              }
            />
            <Form.Item
              name="taxonomy_lock"
              label="标签树契约"
              initialValue="default"
              extra="默认纳入各 clip 校核时的标签树版本；锁定后仅匹配指定版本。"
              style={{ marginTop: 16 }}
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
            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
              标签值分布
            </Typography.Text>
            <DatasetLabelDistributionForm
              nodes={taxonomyNodes}
              value={labelDistribution}
              onChange={setLabelDistribution}
            />
            {previewPanel}
          </>
        )
      case 2:
        return (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              可选：在符合筛选条件的 clip 中随机抽样，或按某一标签维度做类别平衡。
            </Typography.Paragraph>
            <Form.Item
              name="sample_size"
              label="随机取样数量（可选）"
              extra="留空则纳入全部匹配 clip。"
            >
              <InputNumber min={1} max={10000} style={{ width: '100%' }} placeholder="例如 100" />
            </Form.Item>
            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
              类别平衡（可选）
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
            {previewPanel}
          </>
        )
      case 3:
        return (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              选择导出格式与体积；系统会根据当前 clip 规模给出建议。
            </Typography.Paragraph>
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
              extra="额外生成 Parquet，便于 pandas/Spark 读取；JSONL 仍保留。"
            >
              <Checkbox>同时导出 Parquet</Checkbox>
            </Form.Item>
            {previewPanel}
          </>
        )
      case 4:
        return (
          <>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
              请确认以下配置，点击「创建」后将开始构建数据集快照。
            </Typography.Paragraph>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="名称">{previewName?.trim() || '—'}</Descriptions.Item>
              <Descriptions.Item label="描述">{description?.trim() || '—'}</Descriptions.Item>
              <Descriptions.Item label="标签树契约">{taxonomyLockLabel}</Descriptions.Item>
              <Descriptions.Item label="标签值分布">{distributionSummary}</Descriptions.Item>
              <Descriptions.Item label="随机取样">
                {sampleSize != null && sampleSize > 0 ? `${sampleSize} 条` : '全部匹配 clip'}
              </Descriptions.Item>
              <Descriptions.Item label="类别平衡">{balanceLabel}</Descriptions.Item>
              <Descriptions.Item label="导出预设">
                {exportPreset === 'full' ? '完整' : '精简'}
                {includeParquet ? ' + Parquet' : ''}
              </Descriptions.Item>
            </Descriptions>
            {previewPanel}
          </>
        )
      default:
        return null
    }
  })()

  return (
    <>
      <Modal
        title="创建数据集快照"
        open={open}
        onCancel={onClose}
        width={760}
        destroyOnClose
        footer={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Button onClick={onClose}>取消</Button>
            <Space>
              {step > 0 ? <Button onClick={goPrev}>上一步</Button> : null}
              {step < WIZARD_STEPS.length - 1 ? (
                <Button type="primary" onClick={() => void goNext()}>
                  下一步
                </Button>
              ) : (
                <Button type="primary" loading={creating} onClick={() => void submitCreate()}>
                  创建
                </Button>
              )}
            </Space>
          </div>
        }
        styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto', paddingTop: 8 } }}
      >
        <Steps
          current={step}
          size="small"
          items={WIZARD_STEPS}
          style={{ marginBottom: 24 }}
          onChange={(next) => {
            if (next < step) setStep(next)
          }}
        />
        <Form form={form} layout="vertical" preserve>
          {stepContent}
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
                    onClose()
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
    </>
  )
}
