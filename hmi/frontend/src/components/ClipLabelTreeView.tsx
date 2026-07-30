import { CheckCircleOutlined, ClockCircleOutlined, EditOutlined } from '@ant-design/icons'
import { Button, Collapse, Space, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import type { AiLabelHint, ClipLabelReview, TaxonomyNodeDetail } from '../api/types'
import { AiLabelHintReference } from './AiLabelHintReference'
import { LabelQuickReviewModal } from './LabelQuickReviewModal'
import { clipLabelsFlat, formatLabelValue } from '../utils/labelDisplay'

function hasClipLabelValue(flat: Record<string, unknown>, labelId: string): boolean {
  if (!(labelId in flat)) return false
  const v = flat[labelId]
  if (v === null || v === undefined) return false
  if (typeof v === 'string' && v.trim() === '') return false
  return true
}

type LevelGroup = {
  key: string
  title: string
  nodes: TaxonomyNodeDetail[]
}

function groupActiveNodes(nodes: TaxonomyNodeDetail[]): LevelGroup[] {
  const groups = new Map<string, LevelGroup>()
  for (const node of nodes) {
    if (node.is_active === false) continue
    const levelCode = node.level_code || 'other'
    if (!groups.has(levelCode)) {
      groups.set(levelCode, {
        key: levelCode,
        title: node.level_name || levelCode,
        nodes: [],
      })
    }
    groups.get(levelCode)!.nodes.push(node)
  }
  for (const group of groups.values()) {
    group.nodes.sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
  }
  return [...groups.values()].sort((a, b) => a.key.localeCompare(b.key))
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
  const groups = useMemo(() => {
    const active = groupActiveNodes(taxonomyNodes)
    return active
      .map((group) => ({
        ...group,
        nodes: group.nodes.filter((node) => hasClipLabelValue(flat, node.label_id)),
      }))
      .filter((group) => group.nodes.length > 0)
  }, [taxonomyNodes, flat])

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
          <Typography.Text style={{ fontSize: 13, display: 'block', marginTop: 4, wordBreak: 'break-word' }}>
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
          {canQuickReview && clipId && runId ? (
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
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
        activeKey={expandedGroupKeys}
        onChange={(keys) => {
          setExpandedGroupKeys(Array.isArray(keys) ? keys : keys ? [keys] : [])
        }}
        items={groups.map((group) => ({
          key: group.key,
          label: (
            <Typography.Text strong>
              {group.title}{' '}
              <Typography.Text type="secondary" style={{ fontWeight: 400, fontSize: 12 }}>
                ({group.nodes.length})
              </Typography.Text>
            </Typography.Text>
          ),
          children: (
            <div>
              {group.nodes.map((n) => renderRow(n.label_id, n.name, n))}
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
