import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  CheckOutlined,
  EditOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'
import { Alert, Button, Input, InputNumber, Popover, Select, Space, Tooltip } from 'antd'
import { useMemo, useState } from 'react'
import type { ReviewV2Action, ReviewV2Task } from '../api/types'
import { inspectEnumReviewValue, isNestedEnumSchema } from '../utils/enumTree'
import { EnumCascadeSelect } from './EnumCascadeSelect'

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
  const values = schema?.values
  if (!values?.length) return []
  return values
    .filter((v) => typeof v === 'string' || typeof v === 'number')
    .map(String)
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
  const [correctValue, setCorrectValue] = useState<unknown>('')

  const disabled = !task || loading || committing
  const nested = Boolean(task && isNestedEnumSchema(task.value_schema, task.dtype))
  const aiInspect = useMemo(
    () => (task ? inspectEnumReviewValue(task.value_schema, task.ai_value, task.dtype) : null),
    [task],
  )
  const confirmBlocked = Boolean(nested && aiInspect && !aiInspect.complete)
  const enumValues = useMemo(() => (task && !nested ? enumOptions(task) : []), [nested, task])
  const isEnum = enumValues.length > 0
  const isBoolean = task?.dtype === 'boolean'
  const correctInspect = useMemo(
    () =>
      task && nested ? inspectEnumReviewValue(task.value_schema, correctValue, task.dtype) : null,
    [correctValue, nested, task],
  )
  const correctReady = nested
    ? Boolean(correctInspect?.complete)
    : correctValue !== '' || isBoolean

  const resetCorrect = () => {
    setCorrectValue('')
    setCorrectOpen(false)
  }

  const submitCorrect = () => {
    if (!correctReady) return
    onCorrect(correctValue)
    resetCorrect()
  }

  const correctEditor = task ? (
    <Space direction="vertical" size={8} style={{ width: 260 }}>
      {nested ? (
        <EnumCascadeSelect
          schema={task.value_schema}
          dtype={task.dtype}
          value={correctValue === '' ? task.ai_value : correctValue}
          onChange={setCorrectValue}
        />
      ) : isEnum ? (
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
      <Button type="primary" block onClick={submitCorrect} disabled={!correctReady}>
        暂存修正
      </Button>
    </Space>
  ) : null

  return (
    <Space direction="vertical" size={12} style={{ width: vertical ? '100%' : undefined }}>
      {confirmBlocked ? (
        <Alert
          type="warning"
          showIcon
          data-testid="review-enum-incomplete-hint"
          message={aiInspect?.message ?? '嵌套枚举未完成'}
          description="父级与每一级子值都必须有取值后才能点「符合」。请用「修正」补全路径，或标「不确定」。"
        />
      ) : null}
      <Space
        direction={vertical ? 'vertical' : 'horizontal'}
        size={vertical ? 8 : 12}
        wrap={!vertical}
        style={vertical ? { width: '100%' } : undefined}
        data-testid="review-action-bar"
      >
        <Tooltip title={confirmBlocked ? aiInspect?.message : undefined}>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            disabled={disabled || confirmBlocked}
            onClick={onConfirm}
            block={vertical}
            data-testid="review-action-confirm"
          >
            符合
          </Button>
        </Tooltip>
        <Popover
          open={correctOpen}
          onOpenChange={(open) => {
            setCorrectOpen(open)
            if (open && task) setCorrectValue(task.ai_value ?? '')
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
