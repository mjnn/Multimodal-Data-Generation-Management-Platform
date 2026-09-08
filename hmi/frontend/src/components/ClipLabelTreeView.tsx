import { CheckCircleOutlined, ClockCircleOutlined, EditOutlined } from '@ant-design/icons'
import { Button, Collapse, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import type { AiLabelHint, ClipLabelReview, TaxonomyNodeDetail } from '../api/types'
import { AiLabelHintReference } from './AiLabelHintReference'
import { LabelQuickReviewModal } from './LabelQuickReviewModal'
import { clipLabelsFlat, formatLabelValue } from '../utils/labelDisplay'

function isQuickReviewableLabel(labelId: string): boolean {
  if (labelId.startsWith('nvh.') && !labelId.startsWith('nvh.sem.')) return false
  return true
}

function inferLevelFromLabelId(labelId: string): { levelCode: string; levelName: string; name: string } {
  const parts = labelId.split('.')
  if (parts.length >= 2) {
    const levelCode = `${parts[0]}.${parts[1]}`
    return {
      levelCode,
      levelName: levelCode,
      name: parts.slice(2).join('.') || labelId,
    }
  }
  return { levelCode: 'other', levelName: '其他', name: labelId }
}

function syntheticNodesFromFlat(flat: Record<string, unknown>): TaxonomyNodeDetail[] {
  return Object.keys(flat).map((labelId, idx) => {
    const { levelCode, levelName, name } = inferLevelFromLabelId(labelId)
    return {
      id: labelId,
      taxonomy_version_id: '',
      parent_id: null,
      level_code: levelCode,
      level_name: levelName,
      label_id: labelId,
      name,
      definition: null,
      dtype: null,
      value_schema: null,
      sort_order: idx,
      is_active: true,
    }
  })
}

function effectiveTaxonomyNodes(
  taxonomyNodes: TaxonomyNodeDetail[],
  flat: Record<string, unknown>,
): TaxonomyNodeDetail[] {
  const activeNodes = taxonomyNodes.filter((node) => node.is_active !== false)
  if (activeNodes.length) return taxonomyNodes
  const flatKeys = Object.keys(flat)
  if (!flatKeys.length) return taxonomyNodes
  return syntheticNodesFromFlat(flat)
}

type LevelGroup = {
  key: string
  title: string
  nodes: TaxonomyNodeDetail[]
  totalCount: number
  reviewedCount: number
}

function groupActiveNodes(
  taxonomyNodes: TaxonomyNodeDetail[],
  reviewedSet: Set<string>,
): LevelGroup[] {
  const groups = new Map<string, LevelGroup>()
  for (const node of taxonomyNodes) {
    if (node.is_active === false) continue
    const levelCode = node.level_code || 'other'
    if (!groups.has(levelCode)) {
      groups.set(levelCode, {
        key: levelCode,
        title: node.level_name || levelCode,
        nodes: [],
        totalCount: 0,
        reviewedCount: 0,
      })
    }
    groups.get(levelCode)!.nodes.push(node)
  }

  for (const group of groups.values()) {
    group.nodes.sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
    group.totalCount = group.nodes.length
    group.reviewedCount = group.nodes.filter((node) => reviewedSet.has(node.label_id)).length
  }

  return [...groups.values()]
    .filter((group) => group.nodes.length > 0)
    .sort((a, b) => a.key.localeCompare(b.key))
}

type ClipLabelTreeViewProps = {
  taxonomyNodes: TaxonomyNodeDetail[]
  labelsJson: Record<string, unknown>
  fieldReviewedLabelIds?: string[]
  aiLabelHints?: Record<string, AiLabelHint>
  canQuickReview?: boolean
  clipId?: string
  runId?: string
  onReviewSaved?: (review: ClipLabelReview) => void
}

export function ClipLabelTreeView({
  taxonomyNodes,
  labelsJson,
  fieldReviewedLabelIds = [],
  aiLabelHints = {},
  canQuickReview = false,
  clipId,
  runId,
  onReviewSaved,
}: ClipLabelTreeViewProps) {
  const [activeLabelId, setActiveLabelId] = useState<string | null>(null)
  const [activeLabelName, setActiveLabelName] = useState('')
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([])
  const flat = useMemo(() => clipLabelsFlat(labelsJson), [labelsJson])
  const reviewedSet = useMemo(() => new Set(fieldReviewedLabelIds), [fieldReviewedLabelIds])
  const resolvedTaxonomyNodes = useMemo(
    () => effectiveTaxonomyNodes(taxonomyNodes, flat),
    [taxonomyNodes, flat],
  )
  const groups = useMemo(
    () => groupActiveNodes(resolvedTaxonomyNodes, reviewedSet),
    [resolvedTaxonomyNodes, reviewedSet],
  )
  const allGroupKeys = groups.map((g) => g.key)
  const activeGroupKeys = expandedGroupKeys.length > 0 ? expandedGroupKeys : allGroupKeys

  if (!groups.length) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无结构化标签
      </Typography.Text>
    )
  }

  const renderRow = (labelId: string, name: string, taxonomyNode: TaxonomyNodeDetail) => {
    const reviewed = reviewedSet.has(labelId)
    const hint = aiLabelHints[labelId]
    return (
      <div
        key={labelId}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 12,
          padding: '8px 0',
          borderBottom: '1px solid var(--color-hairline)',
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <Typography.Text strong style={{ fontSize: 13 }}>
            {name}
          </Typography.Text>
          <Typography.Text type="secondary" className="mono" style={{ fontSize: 11, display: 'block' }}>
            {labelId}
          </Typography.Text>
          <Typography.Text
            data-testid={`label-tree-value-${labelId}`}
            style={{ fontSize: 13, display: 'block', marginTop: 4, wordBreak: 'break-word' }}
          >
            {formatLabelValue(flat[labelId], taxonomyNode)}
          </Typography.Text>
          <div style={{ marginTop: 6 }}>
            <AiLabelHintReference confidence={hint?.confidence} evidence={hint?.evidence} />
          </div>
        </div>
        <Space direction="vertical" size={6} align="end" style={{ flexShrink: 0 }}>
          <Tag
            icon={reviewed ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
            color={reviewed ? 'success' : 'default'}
            style={{ margin: 0 }}
          >
            {reviewed ? '已校核' : '待校核'}
          </Tag>
          {canQuickReview && clipId && runId && isQuickReviewableLabel(labelId) ? (
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              data-testid={`quick-review-${labelId}`}
              style={{ paddingInline: 0, height: 'auto' }}
              onClick={() => {
                setActiveLabelId(labelId)
                setActiveLabelName(name)
              }}
            >
              快速校核
            </Button>
          ) : null}
        </Space>
      </div>
    )
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Collapse
        size="small"
        activeKey={activeGroupKeys}
        onChange={(keys) => {
          setExpandedGroupKeys(Array.isArray(keys) ? keys : keys ? [keys] : [])
        }}
        items={groups.map((group) => ({
          key: group.key,
          label: (
            <Space size={8} wrap>
              <Typography.Text strong>{group.title}</Typography.Text>
              <Tag
                color={group.reviewedCount >= group.totalCount ? 'success' : 'default'}
                style={{ margin: 0, fontWeight: 400 }}
              >
                校核 {group.reviewedCount}/{group.totalCount}
              </Tag>
            </Space>
          ),
          children: (
            <div>
              {group.nodes.length > 0 ? (
                group.nodes.map((n) => renderRow(n.label_id, n.name, n))
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  本类标签均为空值，请通过校核任务或快速校核处理
                </Typography.Text>
              )}
            </div>
          ),
        }))}
      />
      {canQuickReview && clipId && runId && activeLabelId ? (
        <LabelQuickReviewModal
          open
          clipId={clipId}
          runId={runId}
          labelId={activeLabelId}
          labelName={activeLabelName}
          onClose={() => setActiveLabelId(null)}
          onSaved={onReviewSaved}
        />
      ) : null}
    </Space>
  )
}
