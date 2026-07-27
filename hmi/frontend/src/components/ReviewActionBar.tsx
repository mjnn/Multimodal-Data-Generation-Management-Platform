import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  EditOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { Button, Input, InputNumber, Popover, Select, Space } from 'antd'
import { useMemo, useState } from 'react'
import type { ReviewV2Action, ReviewV2Task } from '../api/types'

type Props = {
  task: ReviewV2Task | null
  canPrev: boolean
  canNext: boolean
  loading: boolean
  committing: boolean
  allStaged: boolean
  stagedCount: number
  queueTotal: number
  vertical?: boolean
  onConfirm: () => void
  onCorrect: (value: unknown) => void
  onUncertain: () => void
  onPrev: () => void
  onNext: () => void
  onCommitQueue: () => void
}

function enumOptions(task: ReviewV2Task): string[] {
  const schema = task.value_schema as { values?: unknown[] } | null | undefined
  if (schema?.values?.length) return schema.values.map(String)
  return []
}

export function ReviewActionBar({
  task,
  canPrev,
  canNext,
  loading,
  committing,
  allStaged,
  stagedCount,
  queueTotal,
  vertical = false,
  onConfirm,
  onCorrect,
  onUncertain,
  onPrev,
  onNext,
  onCommitQueue,
}: Props) {
  const [correctOpen, setCorrectOpen] = useState(false)
  const [correctValue, setCorrectValue] = useState<string | number | boolean>('')

  const disabled = !task || loading || committing
  const enumValues = useMemo(() => (task ? enumOptions(task) : []), [task])
  const isEnum = enumValues.length > 0
  const isBoolean = task?.dtype === 'boolean'

  const resetCorrect = () => {
    setCorrectValue('')
    setCorrectOpen(false)
  }

  const submitCorrect = () => {
    if (correctValue === '' && !isBoolean) return
    onCorrect(correctValue)
    resetCorrect()
  }

  const correctEditor = task ? (
    <Space direction="vertical" size={8} style={{ width: 240 }}>
      {isEnum ? (
        <Select
          placeholder="选择正确取值"
          style={{ width: '100%' }}
          value={correctValue === '' ? undefined : String(correctValue)}
          options={enumValues.map((v) => ({ label: v, value: v }))}
          onChange={(v) => setCorrectValue(v)}
        />
      ) : isBoolean ? (
        <Select
          placeholder="选择"
          style={{ width: '100%' }}
          value={typeof correctValue === 'boolean' ? String(correctValue) : undefined}
          options={[
            { label: '是', value: 'true' },
            { label: '否', value: 'false' },
          ]}
          onChange={(v) => setCorrectValue(v === 'true')}
        />
      ) : task.dtype === 'number' || task.dtype === 'integer' ? (
        <InputNumber
          style={{ width: '100%' }}
          value={typeof correctValue === 'number' ? correctValue : undefined}
          onChange={(v) => setCorrectValue(v ?? '')}
        />
      ) : (
        <Input
          placeholder="输入正确取值"
          value={String(correctValue ?? '')}
          onChange={(e) => setCorrectValue(e.target.value)}
          onPressEnter={submitCorrect}
        />
      )}
      <Button type="primary" block onClick={submitCorrect} disabled={correctValue === '' && !isBoolean}>
        暂存修正
      </Button>
    </Space>
  ) : null

  return (
    <Space direction="vertical" size={12} style={{ width: vertical ? '100%' : undefined }}>
      <Space
        direction={vertical ? 'vertical' : 'horizontal'}
        size={vertical ? 8 : 12}
        wrap={!vertical}
        style={vertical ? { width: '100%' } : undefined}
        data-testid="review-action-bar"
      >
        <Button
          type="primary"
          icon={<CheckOutlined />}
          disabled={disabled}
          onClick={onConfirm}
          block={vertical}
          data-testid="review-action-confirm"
        >
          符合
        </Button>
        <Popover
          open={correctOpen}
          onOpenChange={(open) => {
            setCorrectOpen(open)
            if (!open) setCorrectValue('')
          }}
          trigger="click"
          content={correctEditor}
          title="修正标签值"
        >
          <Button icon={<EditOutlined />} disabled={disabled} block={vertical} data-testid="review-action-correct">
            修正
          </Button>
        </Popover>
        <Button
          icon={<QuestionCircleOutlined />}
          disabled={disabled}
          onClick={onUncertain}
          block={vertical}
          data-testid="review-action-uncertain"
        >
          不确定
        </Button>
        <Button
          icon={<ArrowLeftOutlined />}
          disabled={!canPrev || loading || committing}
          onClick={onPrev}
          block={vertical}
          data-testid="review-action-prev"
        >
          上一个
        </Button>
        <Button
          icon={<ArrowRightOutlined />}
          disabled={!canNext || loading || committing}
          onClick={onNext}
          block={vertical}
          data-testid="review-action-next"
        >
          下一个
        </Button>
      </Space>

      {stagedCount > 0 ? (
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          disabled={!allStaged || committing}
          loading={committing}
          block
          onClick={onCommitQueue}
          data-testid="review-action-commit-queue"
        >
          确认提交本队列（{stagedCount}/{queueTotal}）
        </Button>
      ) : null}
    </Space>
  )
}

export type { ReviewV2Action }
