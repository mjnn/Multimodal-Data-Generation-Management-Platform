/** User-facing Chinese labels for API enums and technical keys. */

export const AUDIT_RESOURCE_TYPE_LABELS: Record<string, string> = {
  dataset_snapshot: '数据集快照',
  clip_label_review: 'Clip 校核',
  clip_label_field_review: '字段校核',
  aug_recipe: '扩增配方',
  taxonomy_proposal: '标签提案',
  review_assignment_batch: '校核派发批次',
  label_taxonomy_version: '标签树版本',
}

export function formatAuditResourceType(type: string): string {
  return AUDIT_RESOURCE_TYPE_LABELS[type] ?? type
}

export const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  merged: '已合并',
  rejected: '已拒绝',
}

export function formatProposalStatus(status: string): string {
  return PROPOSAL_STATUS_LABELS[status] ?? status
}

export const PROPOSAL_TYPE_LABELS: Record<string, string> = {
  scene_cluster: '相似簇',
  new_node: '新建节点',
  extend_enum: '扩展枚举',
  deprecate_node: '废弃节点',
  other: '其他',
}

export function formatProposalType(type: string): string {
  return PROPOSAL_TYPE_LABELS[type] ?? type
}

export const TAXONOMY_DTYPE_LABELS: Record<string, string> = {
  enum: '枚举',
  bool: '布尔',
  string: '字符串',
}

export function formatTaxonomyDtype(dtype: string | null | undefined): string {
  if (!dtype) return '—'
  return TAXONOMY_DTYPE_LABELS[dtype] ?? dtype
}

export const TAXONOMY_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  dtype: '数据类型',
  value_schema: '取值结构',
  is_active: '启用',
}

export function formatTaxonomyField(field: string): string {
  return TAXONOMY_FIELD_LABELS[field] ?? field
}

export const DATASET_SKIP_REASON_LABELS: Record<string, string> = {
  missing_labels: '缺少标签',
  no_clip_embedding: '缺少 clip 向量',
  taxonomy_mismatch: '标签树不匹配',
  field_review_incomplete: '字段校核未完成',
  unknown: '未知原因',
}

export function formatDatasetSkipReason(reason: string): string {
  return DATASET_SKIP_REASON_LABELS[reason] ?? reason
}

export const AUGMENTATION_MODE_LABELS: Record<string, string> = {
  none: '无扩增',
  oversample_only: '仅过采样',
  recipe_attached: '附带扩增配方',
}

export function formatAugmentationMode(mode: string | null | undefined): string {
  if (!mode) return '—'
  return AUGMENTATION_MODE_LABELS[mode] ?? mode
}

export const CLIP_RUN_STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
}

export function formatClipRunStatus(status: string): string {
  return CLIP_RUN_STATUS_LABELS[status] ?? status
}

export const SYNC_STATUS_LABELS: Record<string, string> = {
  success: '成功',
  failed: '失败',
  running: '进行中',
  idle: '空闲',
}

export function formatSyncStatus(status: string): string {
  return SYNC_STATUS_LABELS[status] ?? status
}

const API_MESSAGE_ZH: Array<[RegExp, string | ((m: RegExpMatchArray) => string)]> = [
  [/^invalid username or password$/i, '用户名或密码错误'],
  [/^registration is disabled$/i, '注册已关闭'],
  [/^user not found or inactive$/i, '用户不存在或已禁用'],
  [/^current password is incorrect$/i, '当前密码不正确'],
  [/^password is incorrect$/i, '密码不正确'],
  [/^invalid or expired token$/i, '登录已失效，请重新登录'],
  [/^admin role required$/i, '需要管理员权限'],
  [/^include_pending_review requires admin role$/i, '包含待校核 clip 需要管理员权限'],
  [/^dataset snapshot not found$/i, '数据集快照不存在'],
  [/^derive requires ready parent \(current: (.+)\)$/i, '派生要求父快照为就绪（当前：$1）'],
  [/^build already running:?/i, '构建正在进行中'],
  [/^no clip rows assembled/i, '未组装到任何 clip 行'],
  [/^clip count (\d+) exceeds limit (\d+)$/i, 'clip 数量 $1 超出上限 $2'],
  [/^review updated_at conflict$/i, '校核记录已被他人修改，请刷新后重试'],
  [/^Only \.bag files are accepted$/i, '仅支持 .bag 文件'],
  [/^retry only allowed for failed or cancelled runs$/i, '仅失败或已中止的运行可重试'],
  [/^rosbag file missing on disk; re-upload$/i, '本地 bag 文件缺失，请重新上传'],
]

export function localizeApiMessage(message: string): string {
  const trimmed = message.trim()
  for (const [pattern, replacement] of API_MESSAGE_ZH) {
    if (typeof replacement === 'string') {
      if (pattern.test(trimmed)) return replacement
    } else {
      const match = trimmed.match(pattern)
      if (match) return replacement(match)
    }
  }
  return trimmed
}
