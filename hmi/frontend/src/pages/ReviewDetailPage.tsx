import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckOutlined,
  ExportOutlined,
  SaveOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import {
  Button,
  Col,
  Descriptions,
  Form,
  Modal,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  Alert,
  message,
} from 'antd'
import type { AxiosError } from 'axios'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { ClipLabelReview, ReviewStatus, ReviewTaskCandidate, TaxonomyNodeDetail } from '../api/types'
import { ClipTimelinePanel } from '../components/ClipTimelinePanel'
import { ReviewTaxonomyForm } from '../components/ReviewTaxonomyForm'
import { BackLink, ContentCard, PageHeader, PageStack } from '../components/ui'
import { lowConfidenceLabelIdsFromHints } from '../utils/reviewConfidence'

const STATUS_LABEL: Record<ReviewStatus, string> = {
  pending_review: '待校核',
  reviewed: '已校核',
}

function apiErrorMessage(e: unknown, fallback: string): string {
  const detail = (e as AxiosError<{ detail?: { message?: string } }>)?.response?.data?.detail
    ?.message
  return detail ?? fallback
}

function parseTaskFilters(raw: string | null): Record<string, string | boolean> {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as Record<string, string | boolean>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function parseAnchorTimestampNs(summary: Record<string, unknown> | null): number | undefined {
  const raw = summary?.anchor_timestamp_ns
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim()) {
    const n = Number(raw)
    if (Number.isFinite(n)) return n
  }
  return undefined
}

export function ReviewDetailPage() {
  const { clipId: clipIdParam } = useParams<{ clipId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const clipId = clipIdParam ? decodeURIComponent(clipIdParam) : ''
  const runId = searchParams.get('run_id') ?? undefined
  const taskFilters = useMemo(
    () => parseTaskFilters(searchParams.get('task_filters')),
    [searchParams],
  )
  const taskScope = (searchParams.get('task_scope') ?? 'unreviewed') as
    | 'all'
    | 'pending_review'
    | 'reviewed'
    | 'unreviewed'
  const hasTask = Object.keys(taskFilters).length > 0

  const [form] = Form.useForm<Record<string, unknown>>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [review, setReview] = useState<ClipLabelReview | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [taskItems, setTaskItems] = useState<ReviewTaskCandidate[]>([])

  const taskIndex = useMemo(() => {
    if (!hasTask || !clipId) return -1
    return taskItems.findIndex((item) => item.clip_id === clipId && item.run_id === review?.run_id)
  }, [clipId, hasTask, review?.run_id, taskItems])

  const taskLabelIds = useMemo(() => Object.keys(taskFilters), [taskFilters])
  const nodeById = useMemo(
    () => new Map(taxonomyNodes.map((node) => [node.label_id, node])),
    [taxonomyNodes],
  )
  const taskSummary = useMemo(() => {
    if (!hasTask) return null
    const parts = taskLabelIds.map((labelId) => {
      const node = nodeById.get(labelId)
      const value = taskFilters[labelId]
      const valueText = typeof value === 'boolean' ? (value ? '是' : '否') : String(value)
      return `${node?.name ?? labelId} = ${valueText}`
    })
    return parts.join(' · ')
  }, [hasTask, nodeById, taskFilters, taskLabelIds])
  const visibleLowConfidenceLabelIds = useMemo(() => {
    if (!review) return []
    const hints = review.ai_label_hints ?? {}
    const all = lowConfidenceLabelIdsFromHints(hints, review.labels_json ?? {})
    if (!hasTask) return all
    const allowed = new Set(taskLabelIds)
    return all.filter((id) => allowed.has(id))
  }, [hasTask, review, taskLabelIds])

  const anchorTimestampNs = useMemo(
    () => parseAnchorTimestampNs(review?.ai_source_summary_json ?? null),
    [review?.ai_source_summary_json],
  )

  const explorerHref = useMemo(() => {
    if (!clipId || !review?.run_id) return '#'
    const params = new URLSearchParams({ run_id: review.run_id })
    if (anchorTimestampNs != null) params.set('t', String(anchorTimestampNs))
    return `/clips/${encodeURIComponent(clipId)}?${params.toString()}`
  }, [anchorTimestampNs, clipId, review?.run_id])

  const loadTaxonomy = useCallback(async (versionId: string | null) => {
    try {
      if (versionId) {
        const tree = await api.getTaxonomyTree(versionId)
        setTaxonomyNodes(tree.nodes)
        return
      }
      const versions = await api.listTaxonomyVersions()
      const published = versions.find((v) => v.status === 'published')
      if (published) {
        const tree = await api.getTaxonomyTree(published.id)
        setTaxonomyNodes(tree.nodes)
      }
    } catch {
      setTaxonomyNodes([])
    }
  }, [])

  const loadTaskItems = useCallback(async () => {
    if (!hasTask) {
      setTaskItems([])
      return
    }
    try {
      const res = await api.getReviewCandidates({
        labelFilters: taskFilters,
        reviewScope: taskScope,
        limit: 500,
        offset: 0,
      })
      setTaskItems(res.items)
    } catch {
      setTaskItems([])
    }
  }, [hasTask, taskFilters, taskScope])

  const loadReview = useCallback(async () => {
    if (!clipId) return
    setLoading(true)
    try {
      let detail: ClipLabelReview
      try {
        detail = await api.getReviewDetail(clipId, runId)
      } catch (e) {
        const status = (e as AxiosError)?.response?.status
        if (status === 404) {
          try {
            detail = await api.ensureReview(clipId, runId)
          } catch (ensureErr) {
            const ensureMsg = apiErrorMessage(ensureErr, '')
            if (ensureMsg.includes('already exists')) {
              detail = await api.getReviewDetail(clipId, runId)
            } else {
              throw ensureErr
            }
          }
        } else {
          throw e
        }
      }
      setReview(detail)
      form.setFieldsValue(detail.labels_json ?? {})
      await loadTaxonomy(detail.taxonomy_version_id)
    } catch (e) {
      message.error(apiErrorMessage(e, '加载校核详情失败'))
      navigate('/review')
    } finally {
      setLoading(false)
    }
  }, [clipId, form, loadTaxonomy, navigate, runId])

  useEffect(() => {
    void loadReview()
  }, [loadReview])

  useEffect(() => {
    void loadTaskItems()
  }, [loadTaskItems])

  const buildTaskHref = (target: ReviewTaskCandidate) => {
    const params = new URLSearchParams()
    params.set('run_id', target.run_id)
    params.set('task_filters', JSON.stringify(taskFilters))
    if (taskScope !== 'unreviewed') params.set('task_scope', taskScope)
    return `/review/${encodeURIComponent(target.clip_id)}?${params.toString()}`
  }

  const goSibling = (delta: number) => {
    if (taskIndex < 0) return
    const next = taskItems[taskIndex + delta]
    if (next) navigate(buildTaskHref(next))
  }

  const persist = async (reviewStatus: ReviewStatus) => {
    if (!review) return false
    setSaving(true)
    try {
      const edited = form.getFieldsValue(true) as Record<string, unknown>
      const labels_json = hasTask
        ? { ...(review.labels_json ?? {}), ...edited }
        : edited
      const updated = await api.saveReview(review.clip_id, {
        labels_json,
        review_status: reviewStatus,
        updated_at: review.updated_at,
        run_id: review.run_id,
      })
      setReview(updated)
      form.setFieldsValue(updated.labels_json ?? {})
      message.success(reviewStatus === 'reviewed' ? '已确认校核' : '草稿已保存')
      return true
    } catch (e) {
      const status = (e as AxiosError)?.response?.status
      if (status === 409) {
        Modal.warning({
          title: '版本冲突',
          content: '记录已被他人修改，请刷新后重试。',
          onOk: () => void loadReview(),
        })
      } else {
        message.error(apiErrorMessage(e, '保存失败'))
      }
      return false
    } finally {
      setSaving(false)
    }
  }

  const confirmAndNext = async () => {
    const ok = await persist('reviewed')
    if (!ok) return
    if (taskIndex >= 0 && taskIndex < taskItems.length - 1) {
      goSibling(1)
    } else {
      message.success('当前任务已全部校核完成')
      navigate('/review')
    }
  }

  const handleReopen = async () => {
    if (!review) return
    setSaving(true)
    try {
      const updated = await api.reopenReview(review.clip_id, { run_id: review.run_id })
      setReview(updated)
      message.success('已重新打开校核')
    } catch (e) {
      message.error(apiErrorMessage(e, '重新打开失败'))
    } finally {
      setSaving(false)
    }
  }

  if (loading || !review) {
    return (
      <div data-testid="review-detail-page" style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" tip="加载校核任务…" />
      </div>
    )
  }

  const summary = review.ai_source_summary_json ?? {}
  const taskProgress =
    hasTask && taskIndex >= 0 ? `${taskIndex + 1} / ${taskItems.length}` : null

  return (
    <PageStack data-testid="review-detail-page" className="review-detail-page">
      <PageHeader
        title="Clip 校核"
        description={
          hasTask
            ? '在当前标签任务中核对整段 Clip 是否符合 AI 标签；误标请修正后校核。'
            : '按标签树修正 AI 标签并标记校核状态。'
        }
        extra={
          <Space wrap>
            <BackLink fallback="/review" label="返回任务" />
            {taskProgress ? (
              <Tag color="blue">任务进度 {taskProgress}</Tag>
            ) : null}
            <Link to={explorerHref}>
              <Button icon={<ExportOutlined />}>完整时间轴</Button>
            </Link>
            <Tag color={review.review_status === 'reviewed' ? 'success' : 'orange'}>
              {STATUS_LABEL[review.review_status]}
            </Tag>
          </Space>
        }
      />

      <Row gutter={16} align="top" className="review-detail-layout">
        <Col xs={24} xl={10} className="review-detail-layout__main">
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <ContentCard title={hasTask ? '任务标签校核' : '校核标签'}>
              {hasTask && taskSummary ? (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`当前任务：${taskSummary}`}
                  description="仅展示本任务相关标签；确认该维度是否正确即可，其他标签保持不变。"
                />
              ) : null}
              {summary.gate_passed === false ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="多模型一致率未达阈值"
                  description="请结合置信度与证据逐字段校核；空值字段需人工填写。"
                />
              ) : null}
              {visibleLowConfidenceLabelIds.length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`${visibleLowConfidenceLabelIds.length} 个标签置信度偏低或缺失，建议重点校核`}
                />
              ) : null}
              <ReviewTaxonomyForm
                form={form}
                nodes={taxonomyNodes}
                focusLabelIds={hasTask ? taskLabelIds : undefined}
                aiLabelHints={review.ai_label_hints ?? {}}
              />
              <Space style={{ marginTop: 16 }} wrap>
                {hasTask && taskIndex > 0 ? (
                  <Button icon={<ArrowLeftOutlined />} onClick={() => goSibling(-1)}>
                    上一条
                  </Button>
                ) : null}
                <Button
                  type="primary"
                  icon={<CheckOutlined />}
                  loading={saving}
                  onClick={() => void confirmAndNext()}
                >
                  确认无误
                </Button>
                <Button
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={() => void persist('pending_review')}
                >
                  保存修正
                </Button>
                <Button loading={saving} onClick={() => void persist('reviewed')}>
                  修正并校核
                </Button>
                {hasTask && taskIndex >= 0 && taskIndex < taskItems.length - 1 ? (
                  <Button icon={<ArrowRightOutlined />} onClick={() => goSibling(1)}>
                    下一条
                  </Button>
                ) : null}
                {review.review_status === 'reviewed' && (
                  <Button loading={saving} onClick={() => void handleReopen()}>
                    重新打开
                  </Button>
                )}
              </Space>
            </ContentCard>

            <ContentCard title="AI 标签摘要（只读）">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="Clip ID">{review.clip_id}</Descriptions.Item>
                <Descriptions.Item label="Run ID">{review.run_id}</Descriptions.Item>
                <Descriptions.Item label="标签预览">
                  {String(summary.label_preview ?? review.label_preview ?? '—')}
                </Descriptions.Item>
                <Descriptions.Item label="粒度">
                  {summary.source === 'fact_clip_label' || summary.aggregation === 'clip_native'
                    ? 'Clip 级'
                    : '兼容聚合'}
                </Descriptions.Item>
                <Descriptions.Item label="更新时间">{review.updated_at}</Descriptions.Item>
              </Descriptions>
            </ContentCard>
          </Space>
        </Col>

        <Col xs={24} xl={14} className="review-detail-layout__media">
          <div className="review-detail-layout__sticky">
            <ContentCard
              title={
                <Space>
                  <VideoCameraOutlined />
                  整段 Clip 预览
                </Space>
              }
              extra="对照整段音视频判断标签是否正确"
            >
              {review.run_id ? (
                <ClipTimelinePanel
                  clipId={review.clip_id}
                  runId={review.run_id}
                  initialTimestampNs={anchorTimestampNs}
                />
              ) : (
                <Typography.Text type="secondary">缺少 run_id，无法加载预览</Typography.Text>
              )}
            </ContentCard>
          </div>
        </Col>
      </Row>
    </PageStack>
  )
}
