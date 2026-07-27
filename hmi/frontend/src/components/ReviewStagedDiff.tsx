import { Space, Tag, Typography } from 'antd'
import type { ReviewV2StagedReview } from '../api/types'
import { REVIEW_ACTION_LABEL, formatReviewValue } from '../utils/reviewV2'

type Props = {
  staged: ReviewV2StagedReview
}

export function ReviewStagedDiff({ staged }: Props) {
  const changed =
    formatReviewValue(staged.ai_value) !== formatReviewValue(staged.value) ||
    staged.action === 'uncertain'

  return (
    <div className="review-staged-diff" data-testid="review-staged-diff">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space size={6} wrap>
          <Tag color="blue">已暂存</Tag>
          <Tag color="processing">{REVIEW_ACTION_LABEL[staged.action]}</Tag>
        </Space>
        <div className="review-staged-diff__row">
          <div className="review-staged-diff__col">
            <Typography.Text type="secondary" className="review-staged-diff__label">
              校核前
            </Typography.Text>
            <span className="review-task-ai-value mono review-staged-diff__value">{formatReviewValue(staged.ai_value)}</span>
          </div>
          <Typography.Text type="secondary" className="review-staged-diff__arrow">
            →
          </Typography.Text>
          <div className="review-staged-diff__col">
            <Typography.Text type="secondary" className="review-staged-diff__label">
              校核后
            </Typography.Text>
            <span
              className={`review-task-ai-value mono review-staged-diff__value${
                staged.action === 'uncertain' ? ' review-task-ai-value--empty' : ''
              }${changed ? ' review-staged-diff__value--changed' : ''}`}
            >
              {formatReviewValue(staged.value)}
            </span>
          </div>
        </div>
      </Space>
    </div>
  )
}
