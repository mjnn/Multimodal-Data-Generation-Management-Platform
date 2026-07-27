import { PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons'

import { Alert, Button, Space, Statistic, Typography, message } from 'antd'

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



  return (

    <div data-testid="review-confidence-tasks-page">

      <Alert

        type="info"

        showIcon

        icon={<InfoCircleOutlined />}

        message="开放队列 · 无需管理员派发"

        description="系统汇总所有 Clip 中尚未完成字段校核的标签，按「空值优先、置信度从低到高」排序，校核员可直接进入工作台逐条处理。"

        style={{ marginBottom: 16 }}

      />



      <ContentCard title="置信度优先校核">

        <Space direction="vertical" size={20} style={{ width: '100%' }}>

          <Space size={48} wrap>

            <Statistic title="待校核条目" value={pending} loading={loading} />

            <Statistic title="队列类型" value="开放领取" />

          </Space>



          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>

            优先级：AI 输出为空 → 置信度 &lt; {Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% 或缺失

            → 其余按置信度升序；完成校核后条目自动从队列移除，无需领取或提交任务包。

          </Typography.Paragraph>



          <Button

            type="primary"

            size="large"

            icon={<PlayCircleOutlined />}

            disabled={pending === 0 && !loading}

            onClick={() => navigate('/review/workbench?mode=confidence')}

          >

            开始校核

          </Button>

        </Space>

      </ContentCard>

    </div>

  )

}



/** @deprecated route alias — use ReviewConfidenceTasksPage */

export const ReviewDisputeTasksPage = ReviewConfidenceTasksPage

