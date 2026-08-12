import { Tree, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { useMemo } from 'react'
import type { TaxonomyNodeDetail } from '../api/types'
import { groupTaxonomyLevels, toEditorTreeData } from '../utils/taxonomyTree'

type DatasetTaxonomyCropFormProps = {
  nodes: TaxonomyNodeDetail[]
  value: string[]
  onChange: (next: string[]) => void
}

export function DatasetTaxonomyCropForm({ nodes, value, onChange }: DatasetTaxonomyCropFormProps) {
  const labelIdSet = useMemo(
    () => new Set(nodes.filter((n) => n.is_active !== false).map((n) => n.label_id)),
    [nodes],
  )
  const treeData = useMemo((): DataNode[] => {
    const groups = groupTaxonomyLevels(nodes.filter((n) => n.is_active !== false))
    return toEditorTreeData(groups, false)
  }, [nodes])

  if (!nodes.length) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无可用标签树版本，无法裁剪导出 schema。
      </Typography.Text>
    )
  }

  return (
    <Tree
      checkable
      selectable={false}
      treeData={treeData}
      checkedKeys={value}
      onCheck={(keys) => {
        const list = Array.isArray(keys) ? keys : keys.checked
        // Keep only real taxonomy leaf ids (ignore level / dtype / enumval synthetic keys).
        onChange(list.map(String).filter((k) => labelIdSet.has(k)))
      }}
      height={240}
      data-testid="dataset-taxonomy-crop-tree"
      style={{ border: '1px solid var(--ant-color-border-secondary, #f0f0f0)', borderRadius: 8, padding: 8 }}
    />
  )
}
