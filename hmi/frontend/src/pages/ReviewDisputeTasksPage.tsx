import { PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Form, InputNumber, Modal, Select, Space, Statistic, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { DataTypeRecipe, ReviewTarget, ReviewV2Stats } from '../api/types'
import { ContentCard } from '../components/ui'
import { apiErrorMessage } from '../utils/apiError'
import { LOW_CONFIDENCE_THRESHOLD } from '../utils/reviewConfidence'

export function ReviewConfidenceTasksPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<ReviewV2Stats | null>(null)
  const [dataTypes, setDataTypes] = useState<DataTypeRecipe[]>([])
  const [dataTypeId, setDataTypeId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [claimOpen, setClaimOpen] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const [claimForm] = Form.useForm<{ limit: number; review_targets: ReviewTarget[] }>()
  const selectedType = dataTypes.find((dt) => dt.id === dataTypeId)

  useEffect(() => {
    void api
      .listDataTypes()
      .then((res) => setDataTypes((res.items || []).filter((item) => item.status === 'published')))
      .catch(() => setDataTypes([]))
  }, [])

  const load = useCallback(async () => {
    const dtId = String(dataTypeId || '').trim()
    if (!dtId) {
      setStats(null)
      return
    }
    setLoading(true)
    setStats(null)
    try {
      const res = await api.getReviewV2Stats({ mode: 'confidence', dataTypeId: dtId })
      setStats(res)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载置信度优先队列失败'))
    } finally {
      setLoading(false)
    }
  }, [dataTypeId])

  useEffect(() => {
    void load()
  }, [load])

  const pending = stats?.low_confidence_pending ?? stats?.pending ?? 0

  const openClaim = () => {
    if (!dataTypeId) {
      message.warning('请先选择数据类型')
      return
    }
    claimForm.setFieldsValue({
      limit: Math.min(20, Math.max(1, pending)),
      review_targets: ['labels'],
    })
    setClaimOpen(true)
  }

  const submitClaim = async () => {
    const dtId = String(dataTypeId || '').trim()
    if (!dtId) {
      message.warning('请先选择数据类型')
      return
    }
    const values = await claimForm.validateFields()
    setClaiming(true)
    try {
      const batch = await api.claimLowConfidenceReviewBatch({
        limit: values.limit,
        review_targets: values.review_targets?.length ? values.review_targets : ['labels'],
        data_type_id: dtId,
      })
      message.success(`已领取 ${batch.item_total ?? values.limit} 条低置信度任务`)
      setClaimOpen(false)
      navigate(`/review/workbench?batch=${encodeURIComponent(batch.id)}`)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '领取失败'))
    } finally {
      setClaiming(false)
    }
  }

  const boundTreeHint = selectedType
    ? `绑定标签树：${selectedType.taxonomy_id}${selectedType.taxonomy_version_code ? ` · ${selectedType.taxonomy_version_code}` : ''}`
    : undefined

  return (
    <div data-testid="review-confidence-tasks-page">
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="低置信度任务 · 领取后进入任务包校核"
        description="先选数据类型；仅领取该类型绑定标签树上 AI 为空或置信度低于 75% 的条目。"
        style={{ marginBottom: 16 }}
      />

      <ContentCard title="置信度优先校核">
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>校核任务数据类型</Typography.Text>
            <Select
              allowClear
              placeholder="选择 published 数据类型"
              style={{ width: '100%', maxWidth: 480, marginTop: 8 }}
              value={dataTypeId}
              options={dataTypes.map((item) => ({
                value: item.id,
                label: `${item.title}（${item.id}）`,
              }))}
              onChange={(v) => setDataTypeId(v)}
              data-testid="review-confidence-data-type-select"
            />
            {boundTreeHint ? (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {boundTreeHint}
              </Typography.Paragraph>
            ) : (
              <Typography.Paragraph
                type="secondary"
                style={{ marginTop: 8, marginBottom: 0 }}
                data-testid="review-confidence-pick-type-first"
              >
                请先选择数据类型，可领取数量按该类型绑定的标签树统计
              </Typography.Paragraph>
            )}
          </div>

          <Statistic
            title="可领取（空值 / 低置信度）"
            value={dataTypeId ? pending : '—'}
            loading={Boolean(dataTypeId) && loading}
          />

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            领取范围：当前类型标签树上 AI 输出为空，或置信度 &lt; {Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% 或缺失。
            置信度 ≥ {Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% 的条目不会进入任务包。
          </Typography.Paragraph>

          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            disabled={!dataTypeId || (pending === 0 && !loading)}
            onClick={openClaim}
            data-testid="review-confidence-claim-open"
          >
            领取低置信度校核任务
          </Button>
        </Space>
      </ContentCard>

      <Modal
        title="领取低置信度校核任务"
        open={claimOpen}
        onCancel={() => setClaimOpen(false)}
        onOk={() => void submitClaim()}
        confirmLoading={claiming}
        destroyOnHidden
      >
        <Form form={claimForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="数据类型">
            <Typography.Text>
              {selectedType ? `${selectedType.title}（${selectedType.id}）` : dataTypeId}
            </Typography.Text>
            {boundTreeHint ? (
              <Typography.Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
                {boundTreeHint}
              </Typography.Paragraph>
            ) : null}
          </Form.Item>
          <Form.Item
            name="limit"
            label="领取条数"
            rules={[{ required: true, message: '请输入领取条数' }]}
            extra={`当前可领取约 ${pending} 条`}
          >
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="review_targets"
            label="校核目标"
            rules={[{ required: true, message: '请选择校核目标' }]}
            extra="可多选：标签字段 / 识别框按帧"
          >
            <Select
              mode="multiple"
              allowClear={false}
              options={[
                { value: 'labels', label: '标签' },
                { value: 'bboxes', label: '识别框' },
              ]}
              data-testid="claim-review-targets"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

/** @deprecated route alias — use ReviewConfidenceTasksPage */
export const ReviewDisputeTasksPage = ReviewConfidenceTasksPage
