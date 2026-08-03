import { RightOutlined } from '@ant-design/icons'
import { Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { DatasetLineageContext, DatasetSnapshotRef } from '../api/types'

const STATUS_COLOR: Record<string, string> = {
  building: 'processing',
  ready: 'success',
  failed: 'error',
  archived: 'default',
}

interface DatasetLineageBarProps {
  snapshotId: string
  snapshotName: string
  lineage: DatasetLineageContext | null | undefined
}

function SnapshotLink({ node }: { node: DatasetSnapshotRef }) {
  return (
    <Link to={`/datasets/${node.id}`}>
      {node.name}
    </Link>
  )
}

export function DatasetLineageBar({ snapshotId, snapshotName, lineage }: DatasetLineageBarProps) {
  if (!lineage) {
    return (
      <div data-testid="dataset-lineage-bar">
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          血缘信息不可用
        </Typography.Text>
      </div>
    )
  }

  const ancestors = lineage.ancestor_chain ?? []
  const children = lineage.derived_children ?? []

  return (
    <div data-testid="dataset-lineage-bar">
      <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
        派生血缘
        {lineage.derivation_depth > 0 ? (
          <Typography.Text type="secondary" style={{ fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
            深度 {lineage.derivation_depth}
            {lineage.root_snapshot_id && lineage.root_snapshot_id !== snapshotId ? (
              <> · 根集 <Link to={`/datasets/${lineage.root_snapshot_id}`}>{lineage.root_snapshot_id.slice(0, 8)}…</Link></>
            ) : null}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary" style={{ fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
            根快照
          </Typography.Text>
        )}
      </Typography.Text>
      <Space wrap size={[4, 8]} align="center">
        {ancestors.map((node) => (
          <Space key={node.id} size={4} align="center">
            <SnapshotLink node={node} />
            <RightOutlined style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)' }} />
          </Space>
        ))}
        <Tag color="blue">{snapshotName}</Tag>
        {children.length > 0 ? (
          <>
            <RightOutlined style={{ fontSize: 10, color: 'var(--ant-color-text-quaternary)' }} />
            {children.map((child) => {
              const statusKey = child.status ?? 'archived'
              return (
              <Link key={child.id} to={`/datasets/${child.id}`}>
                <Tag color={STATUS_COLOR[statusKey] ?? 'default'}>{child.name}</Tag>
              </Link>
              )
            })}
          </>
        ) : null}
      </Space>
      {children.length === 0 && ancestors.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 8, fontSize: 12 }}>
          尚无派生子快照；就绪后可继续「派生扩展」。
        </Typography.Paragraph>
      ) : null}
    </div>
  )
}
