import type { AppRole } from './types'

export const ALL_ROLES: AppRole[] = [
  'admin',
  'reviewer',
  'dataset_manager',
  'model_trainer',
]

export const ROLE_LABELS: Record<AppRole, string> = {
  admin: '管理员',
  reviewer: '标注校核员',
  dataset_manager: '数据集管理员',
  model_trainer: '模型训练员',
}

export function hasAnyRole(userRoles: string[] | undefined, allowed: AppRole[]): boolean {
  if (!userRoles?.length) return false
  return allowed.some((r) => userRoles.includes(r))
}

export function canAccessOss(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ['admin', 'dataset_manager'])
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

export function canBrowseData(userRoles: string[] | undefined): boolean {
  return hasAnyRole(userRoles, ALL_ROLES)
}
