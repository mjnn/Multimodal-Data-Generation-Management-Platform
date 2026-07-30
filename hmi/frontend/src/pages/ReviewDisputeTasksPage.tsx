import { PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Form, InputNumber, Modal, Space, Statistic, Typography, message } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { ReviewV2Stats } from '../api/types'
import { ContentCard } from '../components/ui'
import { apiErrorMessage } from '../utils/apiError'
import { LOW_CONFIDENCE_THRESHOLD } from '../utils/reviewConfidence'

export function ReviewConfidenceTasksPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<ReviewV2Stats | null>(null)
  const [loading, setLoading] = useState(false)
  const [claimOpen, setClaimOpen] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const [claimForm] = Form.useForm<{ limit: number }>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.getReviewV2Stats({ mode: 'confidence' })
      setStats(res)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '加载置信度优先队列失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const pending = stats?.pending ?? 0

  const openClaim = () => {
    claimForm.setFieldsValue({ limit: Math.min(20, Math.max(1, pending)) })
    setClaimOpen(true)
  }

  const submitClaim = async () => {
    const values = await claimForm.validateFields()
    setClaiming(true)
    try {
      const batch = await api.claimLowConfidenceReviewBatch({ limit: values.limit })
      message.success(`已领取 ${batch.item_total ?? values.limit} 条低置信度任务`)
      setClaimOpen(false)
      navigate(`/review/workbench?batch=${encodeURIComponent(batch.id)}`)
    } catch (e: unknown) {
      message.error(apiErrorMessage(e, '领取失败'))
    } finally {
      setClaiming(false)
    }
  }

  return (
    <div data-testid="review-confidence-tasks-page">
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        message="低置信度任务 · 领取后进入任务包校核"
        description="按「空值优先、置信度从低到高」从开放池领取指定条数，生成个人任务包；可在「任务领取」继续查看进度。"
        style={{ marginBottom: 16 }}
      />

      <ContentCard title="置信度优先校核">
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Space size={48} wrap>
            <Statistic title="待校核条目（开放池）" value={pending} loading={loading} />
          </Space>

          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            优先级：AI 输出为空 → 置信度 &lt; {Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% 或缺失
            → 其余按置信度升序。
          </Typography.Paragraph>

          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            disabled={pending === 0 && !loading}
            onClick={openClaim}
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
          <Form.Item
            name="limit"
            label="领取条数"
            rules={[{ required: true, message: '请输入领取条数' }]}
            extra={`当前开放池约 ${pending} 条可领`}
          >
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

/** @deprecated route alias — use ReviewConfidenceTasksPage */
export const ReviewDisputeTasksPage = ReviewConfidenceTasksPage
