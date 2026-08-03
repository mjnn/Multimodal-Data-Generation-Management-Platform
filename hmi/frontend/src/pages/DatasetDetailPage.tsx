import {
  CloudDownloadOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  LinkOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import type { DatasetSnapshot, DatasetStatus, TaxonomyNodeDetail } from '../api/types'
import { DatasetLabelFilterForm, type LabelFilters } from '../components/DatasetLabelFilterForm'
import { DatasetTaxonomyCropForm } from '../components/DatasetTaxonomyCropForm'
import { DatasetLineageBar } from '../components/DatasetLineageBar'
import { useAuth } from '../auth/AuthContext'
import { canManageDatasets } from '../auth/roles'
import { ContentCard, PageHeader, PageStack, BackLink } from '../components/ui'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { buildDeriveFilterJson } from '../utils/datasetFilter'
import { expandTaxonomyCropLabelIds } from '../utils/taxonomyCrop'
import { formatAugmentationMode, formatDatasetSkipReason } from '../utils/uiLabels'

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

const SCHEMA_DOC = 'https://github.com/mjnn/rosbag_to_labels_pipline/blob/main/docs/dataset-delivery-schema.md'

function formatFilterJson(filter: DatasetSnapshot['filter_json']): string {
  const parts: string[] = ['仅已校核 clip']
  if (filter.export_preset === 'full') parts.push('完整包')
  if (filter.include_parquet) parts.push('含 Parquet')
  if (filter.sample_size) parts.push(`随机取样 ${filter.sample_size} 条`)
  if (filter.balance_by_label) parts.push(`平衡维度 ${filter.balance_by_label}`)
  if (filter.min_per_class) parts.push(`每类最少 ${filter.min_per_class}`)
  if (filter.max_per_class) parts.push(`每类最多 ${filter.max_per_class}`)
  if (filter.label_filters && Object.keys(filter.label_filters).length > 0) {
    const labels = Object.entries(filter.label_filters)
      .map(([k, v]) => `${k}=${String(v)}`)
      .join('；')
    parts.push(`按标签筛选: ${labels}`)
  }
  if (filter.export_label_ids?.length) {
    parts.push(`导出标签 ${filter.export_label_ids.length} 项`)
  }
  if (filter.clip_ids?.length) parts.push(`指定 clip ${filter.clip_ids.length} 条`)
  return parts.join(' · ')
}

const POLL_MS = 2500

export function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManage = canManageDatasets(user?.roles)

  const [snapshot, setSnapshot] = useState<DatasetSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [deriveOpen, setDeriveOpen] = useState(false)
  const [deriving, setDeriving] = useState(false)
  const [deriveForm] = Form.useForm()
  const [deriveLabelFilters, setDeriveLabelFilters] = useState<LabelFilters>({})
  const [deriveTaxonomyCropIds, setDeriveTaxonomyCropIds] = useState<string[]>([])
  const [deriveTaxonomyNodes, setDeriveTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [derivePreviewLoading, setDerivePreviewLoading] = useState(false)
  const [derivePreviewError, setDerivePreviewError] = useState<string | null>(null)
  const [derivePreviewPool, setDerivePreviewPool] = useState<number | null>(null)
  const [derivePreviewLines, setDerivePreviewLines] = useState<number | null>(null)
  const [deriveDistBefore, setDeriveDistBefore] = useState<Record<string, number> | null>(null)
  const [deriveDistAfter, setDeriveDistAfter] = useState<Record<string, number> | null>(null)
  const pollRef = useRef<number | null>(null)

  const deriveBalanceByLabel = Form.useWatch('balance_by_label', deriveForm) as string | undefined
  const deriveMinPerClass = Form.useWatch('min_per_class', deriveForm) as number | undefined
  const deriveMaxPerClass = Form.useWatch('max_per_class', deriveForm) as number | undefined
  const deriveOversamplePolicy = Form.useWatch('oversample_policy', deriveForm) as string | undefined
  const deriveOversampleMax = Form.useWatch('oversample_max_multiplier', deriveForm) as number | undefined
  const debouncedDeriveLabelFilters = useDebouncedValue(deriveLabelFilters, 400)
  const debouncedDeriveTaxonomyCropIds = useDebouncedValue(deriveTaxonomyCropIds, 400)

  const deriveExportLabelIds = useMemo(() => {
    if (!debouncedDeriveTaxonomyCropIds.length) return null
    const expanded = expandTaxonomyCropLabelIds(deriveTaxonomyNodes, debouncedDeriveTaxonomyCropIds)
    return expanded.length ? expanded : null
  }, [deriveTaxonomyNodes, debouncedDeriveTaxonomyCropIds])

  const deriveBalanceOptions = useMemo(
    () =>
      deriveTaxonomyNodes
        .filter((n) => n.is_active !== false && n.dtype === 'enum')
        .map((n) => ({
          value: n.label_id,
          label: `${n.name ?? n.label_id} (${n.label_id})`,
        })),
    [deriveTaxonomyNodes],
  )

  const openDeriveModal = useCallback(async () => {
    if (!snapshot) return
    const f = snapshot.filter_json
    deriveForm.setFieldsValue({
      name: `${snapshot.name}_derived`,
      description: '',
      balance_by_label: f.balance_by_label ?? undefined,
      min_per_class: f.min_per_class ?? undefined,
      max_per_class: f.max_per_class ?? undefined,
      oversample_policy: f.oversample_policy ?? (f.min_per_class ? 'duplicate_to_min' : 'none'),
      oversample_max_multiplier: f.oversample_max_multiplier ?? 10,
    })
    setDeriveLabelFilters((f.label_filters as LabelFilters) ?? {})
    const parentDeriv = snapshot.derivation_json as { taxonomy_crop?: { selected_label_ids?: string[] } } | null
    setDeriveTaxonomyCropIds(parentDeriv?.taxonomy_crop?.selected_label_ids ?? [])
    setDerivePreviewPool(null)
    setDerivePreviewLines(null)
    setDeriveDistBefore(null)
    setDeriveDistAfter(null)
    setDerivePreviewError(null)
    setDeriveOpen(true)
    try {
      const versions = await api.listTaxonomyVersions()
      const f = snapshot.filter_json
      const parentDeriv = snapshot.derivation_json as { taxonomy_crop?: { cropped_version_id?: string } } | null
      const versionId =
        f.export_taxonomy_version_id ??
        parentDeriv?.taxonomy_crop?.cropped_version_id ??
        versions.find((v) => v.status === 'published')?.id
      if (versionId) {
        const tree = await api.getTaxonomyTree(versionId)
        setDeriveTaxonomyNodes(tree.nodes)
      } else {
        setDeriveTaxonomyNodes([])
      }
    } catch {
      setDeriveTaxonomyNodes([])
    }
  }, [snapshot, deriveForm])

  const loadSnapshot = useCallback(async (silent = false) => {
    if (!id) return null
    if (!silent) setLoading(true)
    try {
      const detail = await api.getDataset(id)
      setSnapshot(detail)
      return detail
    } catch {
      if (!silent) message.error('加载数据集详情失败')
      navigate('/datasets')
      return null
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    void loadSnapshot()
  }, [loadSnapshot])

  useEffect(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!snapshot || (snapshot.status !== 'building' && !snapshot.build_running)) return

    pollRef.current = window.setInterval(() => {
      void loadSnapshot(true)
    }, POLL_MS)

    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current)
    }
  }, [snapshot?.status, snapshot?.build_running, loadSnapshot])

  useEffect(() => {
    if (!deriveOpen || !snapshot) return
    const filterJson = buildDeriveFilterJson(snapshot.filter_json, debouncedDeriveLabelFilters, {
      balance_by_label: deriveBalanceByLabel,
      min_per_class: deriveMinPerClass,
      max_per_class: deriveMaxPerClass,
      oversample_policy: deriveOversamplePolicy,
      oversample_max_multiplier: deriveOversampleMax,
    }, deriveExportLabelIds)
    setDerivePreviewLoading(true)
    void api
      .previewDataset({
        name: 'derive-preview',
        filter_json: filterJson,
        export_preset: snapshot.export_preset ?? 'minimal',
      })
      .then((res) => {
        setDerivePreviewError(null)
        setDerivePreviewPool(res.pool_count)
        setDerivePreviewLines(res.estimated_line_count ?? res.candidate_count)
        setDeriveDistBefore(res.distribution_before ?? null)
        setDeriveDistAfter(res.distribution_after ?? null)
      })
      .catch(() => {
        setDerivePreviewError('预览失败')
        setDerivePreviewPool(null)
        setDerivePreviewLines(null)
        setDeriveDistBefore(null)
        setDeriveDistAfter(null)
      })
      .finally(() => setDerivePreviewLoading(false))
  }, [
    deriveOpen,
    snapshot,
    debouncedDeriveLabelFilters,
    debouncedDeriveTaxonomyCropIds,
    deriveExportLabelIds,
    deriveBalanceByLabel,
    deriveMinPerClass,
    deriveMaxPerClass,
    deriveOversamplePolicy,
    deriveOversampleMax,
  ])

  const openDownload = async () => {
    if (!id) return
    setDownloading(true)
    try {
      const res = await api.getDatasetDownload(id)
      window.open(res.package_url, '_blank', 'noopener,noreferrer')
      message.success(`已开始下载（${res.clip_count ?? 0} clip）`)
    } catch {
      message.error('获取下载链接失败')
    } finally {
      setDownloading(false)
    }
  }

  const handleRetry = async () => {
    if (!id) return
    setRetrying(true)
    try {
      const updated = await api.retryDataset(id)
      setSnapshot(updated)
      message.success('已重新触发构建')
    } catch {
      message.error('重试失败')
    } finally {
      setRetrying(false)
    }
  }

  const handleDelete = async () => {
    if (!id) return
    try {
      await api.deleteDataset(id)
      message.success('数据集已删除')
      navigate('/datasets')
    } catch {
      message.error('删除失败')
    }
  }

  const submitDerive = async () => {
    if (!id || !snapshot) return
    const values = await deriveForm.validateFields()
    const filterJson = buildDeriveFilterJson(snapshot.filter_json, deriveLabelFilters, {
      balance_by_label: values.balance_by_label,
      min_per_class: values.min_per_class,
      max_per_class: values.max_per_class,
      oversample_policy: values.oversample_policy,
      oversample_max_multiplier: values.oversample_max_multiplier,
    }, deriveExportLabelIds)
    setDeriving(true)
    try {
      const child = await api.deriveDataset(id, {
        name: values.name.trim(),
        description: values.description?.trim() || undefined,
        filter_json: filterJson,
        taxonomy_crop_label_ids: deriveTaxonomyCropIds.length ? deriveTaxonomyCropIds : undefined,
      })
      message.success('派生快照已创建')
      setDeriveOpen(false)
      navigate(`/datasets/${child.id}`)
    } catch {
      message.error('派生失败')
    } finally {
      setDeriving(false)
    }
  }

  if (loading || !snapshot) {
    return (
      <div data-testid="dataset-detail-page" style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    )
  }

  const building = snapshot.status === 'building' || snapshot.build_running
  const buildReport = snapshot.build_report
  const skippedByReason = buildReport?.skipped_by_reason ?? {}

  return (
    <PageStack data-testid="dataset-detail-page">
      <PageHeader
        title={snapshot.name}
        description="数据集快照详情；就绪后可下载。交付契约见 Schema 文档。"
        icon={<FolderOpenOutlined />}
        extra={
          <Space wrap>
            <BackLink fallback="/datasets" label="返回列表" />
            <Button type="link" icon={<LinkOutlined />} href={SCHEMA_DOC} target="_blank" rel="noreferrer">
              Schema 文档
            </Button>
            <Tag color={STATUS_COLOR[snapshot.status]}>{STATUS_LABEL[snapshot.status]}</Tag>
          </Space>
        }
      />

      {building && <Alert type="info" showIcon message="数据集构建中，页面将自动刷新状态…" />}

      {snapshot.status === 'failed' && snapshot.error_message && (
        <Alert type="error" showIcon message="构建失败" description={snapshot.error_message} />
      )}

      {snapshot.taxonomy_version_warning ? (
        <Alert type="warning" showIcon message="标签树版本提示" description={snapshot.taxonomy_version_warning} />
      ) : null}

      {snapshot.taxonomy_mixed_hint ? (
        <Alert type="info" showIcon message="标签树混合提示" description={snapshot.taxonomy_mixed_hint} />
      ) : null}

      <ContentCard title="派生血缘">
        <DatasetLineageBar
          snapshotId={snapshot.id}
          snapshotName={snapshot.name}
          lineage={snapshot.lineage}
        />
      </ContentCard>

      <ContentCard
        title="快照信息"
        extra={
          <Space>
            {snapshot.status === 'ready' && (
              <Button
                type="primary"
                icon={<CloudDownloadOutlined />}
                loading={downloading}
                onClick={() => void openDownload()}
              >
                下载
              </Button>
            )}
            {canManage && snapshot.status === 'ready' && (
              <Button data-testid="derive-dataset-btn" onClick={() => void openDeriveModal()}>
                派生扩展
              </Button>
            )}
            {canManage && snapshot.status === 'failed' && (
              <Button icon={<ReloadOutlined />} loading={retrying} onClick={() => void handleRetry()}>
                重试构建
              </Button>
            )}
            {canManage && snapshot.status !== 'archived' && (
              <Popconfirm title="确认删除此数据集？" onConfirm={() => void handleDelete()}>
                <Button danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="ID">{snapshot.id}</Descriptions.Item>
          {snapshot.parent_snapshot_id ? (
            <Descriptions.Item label="直接父快照">
              <Button
                type="link"
                size="small"
                onClick={() => navigate(`/datasets/${snapshot.parent_snapshot_id}`)}
              >
                {snapshot.parent_snapshot?.name ?? snapshot.parent_snapshot_id}
              </Button>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="描述">{snapshot.description ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="导出预设">
            {snapshot.export_preset === 'full' ? '完整' : '精简'}
            {snapshot.filter_json?.include_parquet || snapshot.parquet_available ? ' · Parquet' : ''}
          </Descriptions.Item>
          <Descriptions.Item label="契约版本">{snapshot.schema_version ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="物理 Clip 数">{snapshot.clip_count}</Descriptions.Item>
          <Descriptions.Item label="导出行数">{snapshot.line_count ?? snapshot.clip_count}</Descriptions.Item>
          {snapshot.augmentation_mode ? (
            <Descriptions.Item label="扩增模式">{formatAugmentationMode(snapshot.augmentation_mode)}</Descriptions.Item>
          ) : null}
          <Descriptions.Item label="取样条件">
            <Typography.Text>{formatFilterJson(snapshot.filter_json)}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{api.formatDateTime(snapshot.created_at)}</Descriptions.Item>
          <Descriptions.Item label="就绪时间">{api.formatDateTime(snapshot.ready_at)}</Descriptions.Item>
        </Descriptions>
      </ContentCard>

      {buildReport && Object.keys(skippedByReason).length > 0 ? (
        <ContentCard title="构建报告">
          <Typography.Paragraph type="secondary">跳过原因统计：</Typography.Paragraph>
          <Space wrap>
            {Object.entries(skippedByReason).map(([reason, count]) => (
              <Tag key={reason}>{formatDatasetSkipReason(reason)}: {count}</Tag>
            ))}
          </Space>
          {(buildReport.warnings?.length ?? 0) > 0 ? (
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message={buildReport.warnings?.join('；')} />
          ) : null}
        </ContentCard>
      ) : null}

      <Modal
        title="派生扩展快照"
        open={deriveOpen}
        onCancel={() => setDeriveOpen(false)}
        onOk={() => void submitDerive()}
        confirmLoading={deriving}
        width={720}
        okText="创建派生快照"
        styles={{ body: { maxHeight: 'calc(100vh - 220px)', overflowY: 'auto' } }}
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
          在当前快照取样条件上调整<strong>标签树裁剪</strong>、<strong>按标签筛选 clip</strong>与<strong>类别平衡</strong>；直接父快照保持不变，新派生集单独构建与下载。
        </Typography.Paragraph>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前快照条件"
          description={formatFilterJson(snapshot.filter_json)}
        />
        <div
          data-testid="derive-preview-panel"
          style={{
            marginBottom: 16,
            padding: '12px 16px',
            borderRadius: 8,
            border: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
            background: 'var(--ant-color-fill-quaternary, #fafafa)',
          }}
        >
          <Typography.Text strong>派生预览</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            匹配 clip 与平衡后预估导出行数（相对父集可增可减）。
          </Typography.Paragraph>
          {derivePreviewLoading ? (
            <Typography.Text type="secondary">计算中…</Typography.Text>
          ) : derivePreviewError ? (
            <Alert type="error" showIcon message={derivePreviewError} />
          ) : (
            <Space wrap>
              <Typography.Text>候选池 {derivePreviewPool ?? '—'} clip</Typography.Text>
              <Typography.Text type="secondary">预估导出行 {derivePreviewLines ?? '—'}</Typography.Text>
            </Space>
          )}
          {deriveDistBefore && deriveBalanceByLabel && Object.keys(deriveDistBefore).length > 0 ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0, fontSize: 12 }}>
              平衡前 · {deriveBalanceByLabel}：
              {Object.entries(deriveDistBefore)
                .map(([k, v]) => `${k}=${v}`)
                .join(' · ')}
            </Typography.Paragraph>
          ) : null}
          {deriveDistAfter && deriveBalanceByLabel && Object.keys(deriveDistAfter).length > 0 ? (
            <Typography.Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0, fontSize: 12 }}>
              平衡后 · {deriveBalanceByLabel}：
              {Object.entries(deriveDistAfter)
                .map(([k, v]) => `${k}=${v}`)
                .join(' · ')}
            </Typography.Paragraph>
          ) : null}
        </div>
        <Form form={deriveForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
            标签树裁剪（可选）
          </Typography.Text>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
            勾选要保留的标签节点，将克隆为新草稿 taxonomy 并仅导出对应 y 列；不修改库内已校核标签值。
          </Typography.Paragraph>
          <DatasetTaxonomyCropForm
            nodes={deriveTaxonomyNodes}
            value={deriveTaxonomyCropIds}
            onChange={setDeriveTaxonomyCropIds}
          />
          <Typography.Text strong style={{ display: 'block', marginBottom: 8, marginTop: 16 }}>
            按标签值筛选 clip（可选）
          </Typography.Text>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 0 }}>
            按已校核标签进一步收窄 clip；在父集条件上叠加，相当于对子集再筛选。
          </Typography.Paragraph>
          <DatasetLabelFilterForm
            nodes={deriveTaxonomyNodes}
            value={deriveLabelFilters}
            onChange={setDeriveLabelFilters}
          />
          <Typography.Text strong style={{ display: 'block', marginBottom: 8, marginTop: 16 }}>
            类别平衡（可选）
          </Typography.Text>
          <Form.Item
            name="balance_by_label"
            label="平衡维度"
            extra="按该标签取值分组；max 为欠采样裁剪，min 为过采样补齐。"
          >
            <Select
              allowClear
              showSearch
              placeholder="选择标签，例如 day_period"
              optionFilterProp="label"
              disabled={deriveBalanceOptions.length === 0}
              options={deriveBalanceOptions}
            />
          </Form.Item>
          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="min_per_class" label="每类最少行数" style={{ flex: 1 }}>
              <InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="过采样" />
            </Form.Item>
            <Form.Item name="max_per_class" label="每类最多行数" style={{ flex: 1 }}>
              <InputNumber min={1} max={10000} style={{ width: '100%' }} placeholder="欠采样裁剪" />
            </Form.Item>
          </Space>
          <Form.Item
            name="oversample_policy"
            label="过采样策略"
            initialValue="none"
            extra="设置「每类最少」时建议选「补齐到最少」。"
          >
            <Select
              options={[
                { value: 'none', label: '无过采样' },
                { value: 'duplicate_to_min', label: '补齐到最少（复制样本）' },
              ]}
            />
          </Form.Item>
          <Form.Item name="oversample_max_multiplier" label="单 clip 最大复制倍数" initialValue={10}>
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </PageStack>
  )
}
