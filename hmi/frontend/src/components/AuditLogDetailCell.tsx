import { Typography } from 'antd'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { AuditLogEntry } from '../api/types'
import { withFromAudit } from './ui'
import { formatAuditAction } from '../utils/auditActionLabels'
import { formatAugmentationMode, formatProposalStatus, formatProposalType } from '../utils/uiLabels'

const REVIEW_STATUS_LABELS: Record<string, string> = {
  pending_review: '待校核',
  reviewed: '已校核',
}

const FIELD_REVIEW_ACTION_LABELS: Record<string, string> = {
  correct: '确认',
  edit: '修改',
  doubt: '存疑',
  skip: '跳过',
}

function detailStr(detail: Record<string, unknown> | null | undefined, key: string): string | undefined {
  if (!detail) return undefined
  const v = detail[key]
  if (v == null || v === '') return undefined
  return String(v)
}

function actorLabel(row: AuditLogEntry): string {
  return row.actor_username || row.actor_id?.slice(0, 8) || '系统'
}

function clipPath(clipId: string): string {
  return `/clips/${encodeURIComponent(clipId)}`
}

function workbenchPath(clipId: string, runId: string): string {
  const qs = new URLSearchParams({ clip_id: clipId, run_id: runId })
  return `/review/workbench?${qs.toString()}`
}

function datasetPath(id: string): string {
  return `/datasets/${encodeURIComponent(id)}`
}

function EntityLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={withFromAudit(to)} style={{ fontSize: 12 }}>
      {children}
    </Link>
  )
}

function buildLinks(row: AuditLogEntry, detail: Record<string, unknown>): ReactNode[] {
  const links: ReactNode[] = []
  const clipId = detailStr(detail, 'clip_id')
  const runId = detailStr(detail, 'run_id')
  const parentId = detailStr(detail, 'parent_snapshot_id')

  if (row.resource_type === 'dataset_snapshot') {
    const name = detailStr(detail, 'name')
    links.push(
      <EntityLink key="dataset" to={datasetPath(row.resource_id)}>
        {name ? `数据集「${name}」` : '数据集'}
      </EntityLink>,
    )
  }

  if (parentId) {
    links.push(
      <EntityLink key="parent-dataset" to={datasetPath(parentId)}>
        父数据集
      </EntityLink>,
    )
  }

  if (clipId) {
    links.push(
      <EntityLink key="clip" to={clipPath(clipId)}>
        Clip
      </EntityLink>,
    )
    if (runId) {
      links.push(
        <EntityLink key="workbench" to={workbenchPath(clipId, runId)}>
          校核工作台
        </EntityLink>,
      )
    }
  }

  if (row.resource_type === 'taxonomy_proposal') {
    links.push(
      <EntityLink key="proposal" to="/taxonomy?tab=proposals">
        标签提案
      </EntityLink>,
    )
  }

  if (row.resource_type === 'review_assignment_batch') {
    links.push(
      <EntityLink key="batch" to="/review/assignments">
        派发批次
      </EntityLink>,
    )
  }

  if (row.resource_type === 'aug_recipe') {
    links.push(
      <EntityLink key="datasets" to="/datasets">
        数据集与扩增配方
      </EntityLink>,
    )
  }

  return links
}

function buildSummary(row: AuditLogEntry, detail: Record<string, unknown>): ReactNode {
  const actor = actorLabel(row)
  const time = api.formatDateTime(row.created_at)
  const action = row.action

  switch (action) {
    case 'dataset.create': {
      const name = detailStr(detail, 'name')
      const preset = detailStr(detail, 'export_preset')
      return (
        <>
          <strong>{actor}</strong> 于 {time} 创建数据集{name ? `「${name}」` : ''}
          {preset ? `（导出预设：${preset}）` : ''}
        </>
      )
    }
    case 'dataset.delete': {
      const name = detailStr(detail, 'name')
      return (
        <>
          <strong>{actor}</strong> 于 {time} 归档数据集{name ? `「${name}」` : ''}
        </>
      )
    }
    case 'dataset.derive': {
      const name = detailStr(detail, 'name')
      return (
        <>
          <strong>{actor}</strong> 于 {time} 派生数据集{name ? `「${name}」` : ''}
        </>
      )
    }
    case 'clip.review': {
      const prev = detailStr(detail, 'previous_status')
      const next = detailStr(detail, 'review_status')
      const prevLabel = prev ? REVIEW_STATUS_LABELS[prev] ?? prev : undefined
      const nextLabel = next ? REVIEW_STATUS_LABELS[next] ?? next : undefined
      return (
        <>
          <strong>{actor}</strong> 于 {time} 保存 Clip 校核
          {prevLabel && nextLabel ? `（${prevLabel} → ${nextLabel}）` : ''}
        </>
      )
    }
    case 'clip.reopen': {
      const cleared = detail.cleared_field_reviews
      const clearedN = typeof cleared === 'number' ? cleared : undefined
      return (
        <>
          <strong>{actor}</strong> 于 {time} 重新打开 Clip 校核
          {clearedN != null ? `，清除 ${clearedN} 条字段校核` : ''}
        </>
      )
    }
    case 'clip.label_field_review': {
      const labelId = detailStr(detail, 'label_id')
      const fieldAction = detailStr(detail, 'action')
      const fieldLabel = fieldAction ? FIELD_REVIEW_ACTION_LABELS[fieldAction] ?? fieldAction : undefined
      const rolledUp = detail.rolled_up_to_reviewed === true
      return (
        <>
          <strong>{actor}</strong> 于 {time} 校核字段 {labelId ? `「${labelId}」` : ''}
          {fieldLabel ? `（${fieldLabel}）` : ''}
          {rolledUp ? '，已全部校核完成' : ''}
        </>
      )
    }
    case 'aug_recipe.create':
    case 'aug_recipe.publish': {
      const code = detailStr(detail, 'recipe_code')
      const version = detailStr(detail, 'version')
      const verb = action === 'aug_recipe.publish' ? '发布' : '创建'
      return (
        <>
          <strong>{actor}</strong> 于 {time} {verb}扩增配方
          {code ? `「${code}」` : ''}
          {version ? ` v${version}` : ''}
        </>
      )
    }
    case 'taxonomy.proposal.create': {
      const title = detailStr(detail, 'title')
      const ptype = detailStr(detail, 'proposal_type')
      return (
        <>
          <strong>{actor}</strong> 于 {time} 创建标签提案{title ? `「${title}」` : ''}
          {ptype ? `（${formatProposalType(ptype)}）` : ''}
        </>
      )
    }
    case 'taxonomy.proposal.update': {
      const status = detailStr(detail, 'status')
      return (
        <>
          <strong>{actor}</strong> 于 {time} 更新标签提案
          {status ? `为「${formatProposalStatus(status)}」` : ''}
        </>
      )
    }
    case 'review.assignment.create': {
      const name = detailStr(detail, 'name')
      const total = detail.item_total
      const totalN = typeof total === 'number' ? total : undefined
      return (
        <>
          <strong>{actor}</strong> 于 {time} 创建校核派发{name ? `「${name}」` : ''}
          {totalN != null ? `，共 ${totalN} 项` : ''}
        </>
      )
    }
    case 'review.assignment.close':
      return (
        <>
          <strong>{actor}</strong> 于 {time} 关闭校核派发批次
        </>
      )
    case 'review.assignment.claim': {
      const count = detail.count
      const n = typeof count === 'number' ? count : undefined
      return (
        <>
          <strong>{actor}</strong> 于 {time} 领取校核任务{n != null ? ` ${n} 条` : ''}
        </>
      )
    }
    case 'review.assignment.claim_low_confidence': {
      const limit = detail.limit
      const total = detail.item_total
      const limitN = typeof limit === 'number' ? limit : undefined
      const totalN = typeof total === 'number' ? total : undefined
      return (
        <>
          <strong>{actor}</strong> 于 {time} 领取低置信度校核任务
          {limitN != null ? `（上限 ${limitN}）` : ''}
          {totalN != null ? `，批次共 ${totalN} 项` : ''}
        </>
      )
    }
    default: {
      const mode = detailStr(detail, 'augmentation_mode')
      return (
        <>
          <strong>{actor}</strong> 于 {time} {formatAuditAction(action)}
          {mode ? `（${formatAugmentationMode(mode)}）` : ''}
        </>
      )
    }
  }
}

export function AuditLogDetailCell({ row }: { row: AuditLogEntry }) {
  const detail = (row.detail ?? {}) as Record<string, unknown>
  const links = buildLinks(row, detail)
  const hasDetail = row.detail && Object.keys(row.detail).length > 0

  if (!hasDetail && links.length === 0) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        <strong>{actorLabel(row)}</strong> 于 {api.formatDateTime(row.created_at)}{' '}
        {formatAuditAction(row.action)}
      </Typography.Text>
    )
  }

  return (
    <div style={{ fontSize: 12, lineHeight: 1.55, maxWidth: 480 }}>
      <Typography.Text style={{ fontSize: 12 }}>{buildSummary(row, detail)}</Typography.Text>
      {links.length > 0 ? (
        <div style={{ marginTop: 4 }}>
          {links.map((link, i) => (
            <span key={i}>
              {i > 0 ? <Typography.Text type="secondary"> · </Typography.Text> : null}
              {link}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
