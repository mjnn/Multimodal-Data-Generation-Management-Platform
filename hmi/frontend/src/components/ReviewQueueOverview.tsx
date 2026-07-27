import { AppstoreOutlined } from '@ant-design/icons'
import { Modal, Space, Tooltip, Typography } from 'antd'
import type { ReviewV2StagedReview, ReviewV2Task } from '../api/types'
import { REVIEW_ACTION_LABEL, reviewTaskKey } from '../utils/reviewV2'

type Props = {
  open: boolean
  queue: ReviewV2Task[]
  staged: Record<string, ReviewV2StagedReview>
  currentIndex: number
  onClose: () => void
  onSelect: (index: number) => void
}

type CellStatus = 'pending' | 'confirm' | 'correct' | 'uncertain'

function cellStatus(staged: ReviewV2StagedReview | undefined): CellStatus {
  if (!staged) return 'pending'
  return staged.action
}

function cellTitle(task: ReviewV2Task, staged: ReviewV2StagedReview | undefined, index: number): string {
  const clip = task.clip_id
  const label = task.label_name || task.label_id
  const lines = [`#${index + 1} ${clip}`, label]
  if (staged) {
    lines.push(`已暂存：${REVIEW_ACTION_LABEL[staged.action]}`)
  } else {
    lines.push('未暂存')
  }
  return lines.join('\n')
}

export function ReviewQueueOverview({ open, queue, staged, currentIndex, onClose, onSelect }: Props) {
  const counts = queue.reduce(
    (acc, task) => {
      const s = staged[reviewTaskKey(task.clip_id, task.run_id, task.label_id)]
      const status = cellStatus(s)
      acc[status] += 1
      return acc
    },
    { pending: 0, confirm: 0, correct: 0, uncertain: 0 },
  )

  return (
    <Modal
      title="队列总览"
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      centered
      destroyOnClose
      className="review-queue-overview-modal"
      data-testid="review-queue-overview"
    >
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div className="review-queue-overview__legend">
          <span className="review-queue-overview__legend-item review-queue-overview__cell--pending">
            未审 {counts.pending}
          </span>
          <span className="review-queue-overview__legend-item review-queue-overview__cell--confirm">
            符合 {counts.confirm}
          </span>
          <span className="review-queue-overview__legend-item review-queue-overview__cell--correct">
            修正 {counts.correct}
          </span>
          <span className="review-queue-overview__legend-item review-queue-overview__cell--uncertain">
            不确定 {counts.uncertain}
          </span>
        </div>

        <Typography.Text type="secondary" className="review-queue-overview__hint">
          点击序号快速跳转核对；当前第 {currentIndex + 1} 题
        </Typography.Text>

        <div className="review-queue-overview__grid">
          {queue.map((task, index) => {
            const key = reviewTaskKey(task.clip_id, task.run_id, task.label_id)
            const entry = staged[key]
            const status = cellStatus(entry)
            const isCurrent = index === currentIndex
            return (
              <Tooltip key={key} title={<pre className="review-queue-overview__tooltip">{cellTitle(task, entry, index)}</pre>}>
                <button
                  type="button"
                  className={`review-queue-overview__cell review-queue-overview__cell--${status}${isCurrent ? ' review-queue-overview__cell--current' : ''}`}
                  onClick={() => {
                    onSelect(index)
                    onClose()
                  }}
                  aria-label={`第 ${index + 1} 题`}
                  aria-current={isCurrent ? 'true' : undefined}
                >
                  {index + 1}
                </button>
              </Tooltip>
            )
          })}
        </div>
      </Space>
    </Modal>
  )
}

export function ReviewQueueOverviewButton({
  disabled,
  onClick,
}: {
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="review-queue-overview-trigger"
      disabled={disabled}
      onClick={onClick}
      data-testid="review-queue-overview-trigger"
    >
      <AppstoreOutlined />
      <span>队列总览</span>
    </button>
  )
}
