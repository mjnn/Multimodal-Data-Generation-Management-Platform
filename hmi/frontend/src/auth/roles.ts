import type { AppRole } from './types'

export const STANDARD_ROLES: AppRole[] = [
  'admin',
  'reviewer',
  'dataset_manager',
  'model_trainer',
  'pipeline_manager',
]

export const ALL_ROLES: AppRole[] = [...STANDARD_ROLES, 'anonymous']

export const ROLE_LABELS: Record<AppRole, string> = {
  admin: '管理员',
  reviewer: '标注校核员',
  dataset_manager: '数据集管理员',
  model_trainer: '模型训练员',
  pipeline_manager: '管线管理员',
  anonymous: '匿名用户',
}

export function hasAnyRole(userRoles: string[] | undefined, allowed: AppRole[]): boolean {
  if (!userRoles?.length) return false
  return allowed.some((r) => userRoles.includes(r))
}

export function canAccessOss(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'dataset_manager'])
}

export function canAccessPipeline(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'dataset_manager', 'pipeline_manager'])
}

export function canManageUsers(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin'])
}

export function canManageTaxonomy(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin'])
}

export function canAccessReview(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'reviewer'])
}

export function canAccessDatasets(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'dataset_manager', 'model_trainer'])
}

export function canManageDatasets(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'dataset_manager'])
}

export function canManageReviewAssignments(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin'])
}

/** Clip 详情「快速校核」仅管理员可用（数据总览进入的浏览路径）。 */
export function canQuickReviewClip(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin'])
}

export function canBrowseClips(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, STANDARD_ROLES)
}

export function isAnonymousOnly(userRoles: string[] | undefined): boolean {
  const roles = userRoles ?? []
  if (!roles.length) return true
  return roles.every((r) => r === 'anonymous')
}

export function canSwitchDataSource(userRoles: string[] | undefined): boolean {
  return canBrowseClips(userRoles)
}

export function canBrowseData(userRoles: string[] | undefined): boolean {
  return canBrowseClips(userRoles)
}
