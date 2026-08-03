/** Display labels for audit_log.action (API values stay English). */

const AUDIT_ACTION_LABELS: Record<string, string> = {
  'dataset.create': '创建数据集',
  'dataset.delete': '删除数据集',
  'dataset.derive': '派生数据集',
  'clip.review': '校核保存',
  'clip.reopen': '重新打开校核',
  'clip.label_field_review': '字段校核',
  'aug_recipe.create': '创建扩增配方',
  'aug_recipe.publish': '发布扩增配方',
  'taxonomy.proposal.create': '创建标签提案',
  'taxonomy.proposal.update': '更新标签提案',
  'review.assignment.create': '创建校核派发',
  'review.assignment.close': '关闭校核派发',
  'review.assignment.claim': '领取校核任务',
  'review.assignment.claim_low_confidence': '领取低置信度任务',
}

export function formatAuditAction(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

export const AUDIT_ACTION_FILTER_OPTIONS = Object.entries(AUDIT_ACTION_LABELS).map(
  ([value, label]) => ({ value, label }),
)
