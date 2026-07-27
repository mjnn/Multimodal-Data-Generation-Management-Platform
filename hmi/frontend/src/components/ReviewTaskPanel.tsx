import { Space, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'
import type { ReviewV2StagedReview, ReviewV2Task } from '../api/types'
import { ReviewStagedDiff } from './ReviewStagedDiff'
import { AiLabelHintReference } from './AiLabelHintReference'
import { ContentCard } from './ui'
import { formatReviewValue } from '../utils/reviewV2'

type Props = {
  task: ReviewV2Task
  staged: ReviewV2StagedReview | null
  actions: ReactNode
}

export function ReviewTaskPanel({ task, staged, actions }: Props) {
  const { label_name, label_id, ai_value, human_doubtful, ai_confidence, ai_evidence, low_confidence } =
    task

  return (
    <ContentCard title="标签校核" className="review-task-panel">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {task.position.total > 0 ? (
          <Typography.Text type="secondary">
            队列 {task.position.index} / {task.position.total}
            {staged ? ' · 本条已暂存' : ''}
          </Typography.Text>
        ) : null}

        <div className="review-task-label-panel__heading">
          <Typography.Text strong className="review-task-label-panel__title">
            当前标签：{label_name}
          </Typography.Text>
          <Typography.Text type="secondary" className="mono review-task-label-panel__id">
            {label_id}
          </Typography.Text>
        </div>

        {staged ? (
          <ReviewStagedDiff staged={staged} />
        ) : (
          <div className="review-task-label-panel">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <div className="review-task-label-panel__value-row">
                <Typography.Text type="secondary" className="review-task-label-panel__value-label">
                  AI 值（校核前）
                </Typography.Text>
                <span
                  className={`review-task-ai-value mono${
                    ai_value === null || ai_value === undefined || ai_value === ''
                      ? ' review-task-ai-value--empty'
                      : ''
                  }`}
                >
                  {formatReviewValue(ai_value)}
                </span>
              </div>
              <AiLabelHintReference confidence={ai_confidence} evidence={ai_evidence} />
              <Space size={6} wrap>
                {task.priority_bucket === 0 ? <Tag color="red">空值优先</Tag> : null}
                {low_confidence ? <Tag color="orange">低置信度</Tag> : null}
                {human_doubtful ? <Tag color="purple">人工存疑</Tag> : null}
              </Space>
            </Space>
          </div>
        )}

        <div className="review-task-panel__actions">{actions}</div>
      </Space>
    </ContentCard>
  )
}
