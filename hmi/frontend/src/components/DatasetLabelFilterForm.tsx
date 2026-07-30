import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { AutoComplete, Button, Input, Select, Space, Typography } from 'antd'
import { useMemo, useState, type ReactNode } from 'react'
import type { TaxonomyNodeDetail } from '../api/types'
import { schemaEnumValues } from '../utils/labelDisplay'

export type LabelFilters = Record<string, string | boolean>

type FilterRow = {
  key: string
  labelId: string
}

function activeNodes(nodes: TaxonomyNodeDetail[]): TaxonomyNodeDetail[] {
  return nodes
    .filter((n) => n.is_active !== false)
    .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
}

function nodeLabelSearchText(node: TaxonomyNodeDetail): string {
  return [node.name, node.label_id, node.level_name, node.definition]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function nodeById(nodes: TaxonomyNodeDetail[]): Map<string, TaxonomyNodeDetail> {
  return new Map(activeNodes(nodes).map((n) => [n.label_id, n]))
}

function filtersToRows(value: LabelFilters): FilterRow[] {
  return Object.keys(value).map((labelId) => ({
    key: labelId,
    labelId,
  }))
}

function rowsToFilters(rows: FilterRow[], value: LabelFilters): LabelFilters {
  const out: LabelFilters = {}
  for (const row of rows) {
    if (!row.labelId) continue
    const v = value[row.labelId]
    if (v !== undefined && v !== '') {
      out[row.labelId] = v
    }
  }
  return out
}

type ValueEditorProps = {
  node: TaxonomyNodeDetail
  value: string | boolean | undefined
  onChange: (next: string | boolean | undefined) => void
}

function ValueEditor({ node, value, onChange }: ValueEditorProps) {
  const enumValues = schemaEnumValues(node)

  if (node.dtype === 'bool') {
    return (
      <Select
        allowClear
        placeholder="选择取值"
        style={{ width: '100%' }}
        value={value === undefined ? undefined : value ? 'true' : 'false'}
        options={[
          { value: 'true', label: '是' },
          { value: 'false', label: '否' },
        ]}
        onChange={(next) => {
          if (next == null) {
            onChange(undefined)
            return
          }
          onChange(next === 'true')
        }}
      />
    )
  }

  if (enumValues.length > 0) {
    return (
      <Select
        allowClear
        showSearch
        placeholder="选择枚举值"
        style={{ width: '100%' }}
        value={typeof value === 'string' ? value : undefined}
        options={enumValues.map((v) => ({ value: v, label: v }))}
        onChange={(next) => onChange(next ?? undefined)}
      />
    )
  }

  return (
    <Input
      allowClear
      placeholder="输入匹配值"
      value={typeof value === 'string' ? value : ''}
      onChange={(e) => {
        const next = e.target.value.trim()
        onChange(next || undefined)
      }}
    />
  )
}

type DatasetLabelFilterFormProps = {
  nodes: TaxonomyNodeDetail[]
  value: LabelFilters
  onChange: (next: LabelFilters) => void
}

export function DatasetLabelFilterForm({ nodes, value, onChange }: DatasetLabelFilterFormProps) {
  const lookup = useMemo(() => nodeById(nodes), [nodes])
  const [rows, setRows] = useState<FilterRow[]>(() =>
    filtersToRows(value).length > 0 ? filtersToRows(value) : [{ key: 'new-0', labelId: '' }],
  )
  const [labelQueries, setLabelQueries] = useState<Record<string, string>>({})

  const syncRowsFromValue = (nextValue: LabelFilters, nextRows: FilterRow[]) => {
    onChange(rowsToFilters(nextRows, nextValue))
  }

  const labelOptions = (rowKey: string): { value: string; label: ReactNode }[] => {
    const q = (labelQueries[rowKey] ?? '').trim().toLowerCase()
    const picked = new Set(rows.map((r) => r.labelId).filter(Boolean))
    return activeNodes(nodes)
      .filter((n) => !picked.has(n.label_id) || rows.find((r) => r.key === rowKey)?.labelId === n.label_id)
      .filter((n) => !q || nodeLabelSearchText(n).includes(q))
      .slice(0, 24)
      .map((node) => ({
        value: node.label_id,
        label: (
          <Space size={8} wrap>
            <span>{node.name}</span>
            <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>
              {node.label_id}
            </Typography.Text>
          </Space>
        ),
      }))
  }

  const updateRowLabel = (rowKey: string, labelId: string) => {
    const nextRows = rows.map((r) => (r.key === rowKey ? { ...r, labelId } : r))
    setRows(nextRows)
    const merged = { ...value }
    if (labelId && merged[labelId] === undefined) {
      const node = lookup.get(labelId)
      if (node?.dtype === 'bool') merged[labelId] = true
    }
    syncRowsFromValue(merged, nextRows)
  }

  const updateRowValue = (labelId: string, next: string | boolean | undefined) => {
    const merged = { ...value }
    if (next === undefined) {
      delete merged[labelId]
    } else {
      merged[labelId] = next
    }
    syncRowsFromValue(merged, rows)
  }

  const addRow = () => {
    setRows([...rows, { key: `new-${Date.now()}`, labelId: '' }])
  }

  const removeRow = (rowKey: string, labelId: string) => {
    const nextRows = rows.length > 1 ? rows.filter((r) => r.key !== rowKey) : [{ key: 'new-0', labelId: '' }]
    setRows(nextRows)
    const merged = { ...value }
    if (labelId) delete merged[labelId]
    syncRowsFromValue(merged, nextRows)
  }

  if (lookup.size === 0) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无已发布标签树，无法按标签筛选。
      </Typography.Text>
    )
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        点击「添加筛选项」选择标签并设置取值（多条件 AND）
      </Typography.Text>

      {rows.map((row) => {
        const node = row.labelId ? lookup.get(row.labelId) : undefined
        return (
          <Space key={row.key} align="start" style={{ width: '100%' }} wrap>
            <AutoComplete
              style={{ minWidth: 260, flex: 1 }}
              options={labelOptions(row.key)}
              value={
                row.labelId
                  ? node?.name ?? row.labelId
                  : labelQueries[row.key] ?? ''
              }
              onChange={(text) => setLabelQueries((prev) => ({ ...prev, [row.key]: text }))}
              onSelect={(selected) => {
                updateRowLabel(row.key, String(selected))
                setLabelQueries((prev) => ({ ...prev, [row.key]: '' }))
              }}
              placeholder="搜索标签名称或 ID"
            />
            <div style={{ minWidth: 200, flex: 1 }}>
              {node ? (
                <ValueEditor
                  node={node}
                  value={value[row.labelId]}
                  onChange={(next) => updateRowValue(row.labelId, next)}
                />
              ) : (
                <Input disabled placeholder="先选择标签" />
              )}
            </div>
            <Button
              type="text"
              danger
              icon={<MinusCircleOutlined />}
              aria-label="移除筛选项"
              onClick={() => removeRow(row.key, row.labelId)}
            />
          </Space>
        )
      })}

      <Button type="dashed" icon={<PlusOutlined />} onClick={addRow} block>
        添加筛选项
      </Button>
    </Space>
  )
}
