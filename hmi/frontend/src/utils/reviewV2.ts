import type { ReviewV2Action, ReviewV2StagedReview, ReviewV2Task } from '../api/types'

export function formatReviewValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function comprehensiveFilterReady(
  mode: string,
  labelId: string | null,
  filterValue: string,
): boolean {
  if (mode !== 'comprehensive') return true
  return Boolean(labelId?.trim()) && filterValue.trim() !== ''
}

export function reviewTaskKey(clipId: string, runId: string, labelId: string): string {
  return `${clipId}\0${runId}\0${labelId}`
}

export function resolveStagedValue(
  action: ReviewV2Action,
  aiValue: unknown,
  inputValue?: unknown,
): unknown {
  if (action === 'confirm') return aiValue
  if (action === 'uncertain') return null
  return inputValue
}

export const REVIEW_ACTION_LABEL: Record<ReviewV2Action, string> = {
  confirm: '符合',
  correct: '修正',
  uncertain: '不确定',
}

export function taskWithPosition(task: ReviewV2Task, index: number, total: number): ReviewV2Task {
  return {
    ...task,
    position: { index: index + 1, total },
  }
}

export function buildStagedReview(
  task: ReviewV2Task,
  action: ReviewV2Action,
  inputValue?: unknown,
): ReviewV2StagedReview {
  return {
    clip_id: task.clip_id,
    run_id: task.run_id,
    label_id: task.label_id,
    action,
    ai_value: task.ai_value,
    value: resolveStagedValue(action, task.ai_value, inputValue),
    staged_at: new Date().toISOString(),
  }
}
