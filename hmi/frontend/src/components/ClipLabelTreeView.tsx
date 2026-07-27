import { CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { Collapse, Space, Tag, Typography } from 'antd'
import { useMemo } from 'react'
import type { TaxonomyNodeDetail } from '../api/types'
import { clipLabelsFlat, formatLabelValue } from '../utils/labelDisplay'

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
  clipReviewed?: boolean
}

export function ClipLabelTreeView({
  taxonomyNodes,
  labelsJson,
  fieldReviewedLabelIds = [],
  clipReviewed = false,
}: ClipLabelTreeViewProps) {
  const flat = useMemo(() => clipLabelsFlat(labelsJson), [labelsJson])
  const reviewedSet = useMemo(() => new Set(fieldReviewedLabelIds), [fieldReviewedLabelIds])
  const groups = useMemo(() => groupActiveNodes(taxonomyNodes), [taxonomyNodes])

  const labelIdsInTaxonomy = useMemo(() => new Set(taxonomyNodes.map((n) => n.label_id)), [taxonomyNodes])

  const orphanEntries = useMemo(() => {
    return Object.entries(flat).filter(([id]) => !labelIdsInTaxonomy.has(id))
  }, [flat, labelIdsInTaxonomy])

  if (!groups.length && !orphanEntries.length) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无结构化标签
      </Typography.Text>
    )
  }

  const renderRow = (labelId: string, name: string) => {
    const reviewed = clipReviewed || reviewedSet.has(labelId)
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
            {formatLabelValue(flat[labelId])}
          </Typography.Text>
        </div>
        <Tag
          icon={reviewed ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
          color={reviewed ? 'success' : 'default'}
          style={{ margin: 0, flexShrink: 0 }}
        >
          {reviewed ? '已校核' : '待校核'}
        </Tag>
      </div>
    )
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Collapse
        size="small"
        defaultActiveKey={[]}
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
          children: <div>{group.nodes.map((node) => renderRow(node.label_id, node.name))}</div>,
        }))}
      />
      {orphanEntries.length > 0 ? (
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 8 }}>
            未在标签树中登记
          </Typography.Text>
          {orphanEntries.map(([id]) => renderRow(id, id))}
        </div>
      ) : null}
    </Space>
  )
}
