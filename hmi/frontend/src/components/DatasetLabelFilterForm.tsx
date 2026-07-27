import { SearchOutlined } from '@ant-design/icons'
import { AutoComplete, Input, Select, Space, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api'
import type { TaxonomyNodeDetail } from '../api/types'

export type LabelFilters = Record<string, string | boolean>

function schemaEnumValues(node: TaxonomyNodeDetail): string[] {
  const schema = node.value_schema as { values?: unknown[] } | null
  if (!schema?.values?.length) return []
  return schema.values.map(String)
}

function activeNodes(nodes: TaxonomyNodeDetail[]): TaxonomyNodeDetail[] {
  return nodes
    .filter((n) => n.is_active !== false)
    .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
}

function nodeSearchText(node: TaxonomyNodeDetail): string {
  return [
    node.name,
    node.label_id,
    node.level_code,
    node.level_name,
    node.definition,
    ...schemaEnumValues(node),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function searchNodes(nodes: TaxonomyNodeDetail[], query: string): TaxonomyNodeDetail[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return activeNodes(nodes)
    .filter((node) => nodeSearchText(node).includes(q))
    .slice(0, 24)
}

function nodeById(nodes: TaxonomyNodeDetail[]): Map<string, TaxonomyNodeDetail> {
  return new Map(activeNodes(nodes).map((n) => [n.label_id, n]))
}

type LabelFilterFieldProps = {
  node: TaxonomyNodeDetail
  value: string | boolean | undefined
  onChange: (labelId: string, next: string | boolean | undefined) => void
  compact?: boolean
}

function LabelFilterField({ node, value, onChange, compact }: LabelFilterFieldProps) {
  const enumValues = schemaEnumValues(node)
  const label = compact ? node.name : `${node.name} (${node.label_id})`

  if (node.dtype === 'bool') {
    return (
      <div className="dataset-label-filter-field">
        {!compact && (
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            {label}
          </Typography.Text>
        )}
        <Select
          allowClear
          placeholder={compact ? `${label}：不限` : '不限'}
          style={{ width: '100%' }}
          value={value === undefined ? undefined : value ? 'true' : 'false'}
          options={[
            { value: 'true', label: '是' },
            { value: 'false', label: '否' },
          ]}
          onChange={(next) => {
            if (next == null) {
              onChange(node.label_id, undefined)
              return
            }
            onChange(node.label_id, next === 'true')
          }}
        />
      </div>
    )
  }

  if (enumValues.length > 0) {
    return (
      <div className="dataset-label-filter-field">
        {!compact && (
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            {label}
          </Typography.Text>
        )}
        <Select
          allowClear
          showSearch
          placeholder={compact ? `${label}：选择取值` : '不限'}
          style={{ width: '100%' }}
          value={typeof value === 'string' ? value : undefined}
          options={enumValues.map((v) => ({ value: v, label: v }))}
          onChange={(next) => onChange(node.label_id, next ?? undefined)}
        />
      </div>
    )
  }

  return (
    <div className="dataset-label-filter-field">
      {!compact && (
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
          {label}
        </Typography.Text>
      )}
      <Input
        allowClear
        placeholder={compact ? `${label}：精确匹配` : '精确匹配，留空表示不限'}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => {
          const next = e.target.value.trim()
          onChange(node.label_id, next || undefined)
        }}
      />
    </div>
  )
}

function formatFilterValue(value: string | boolean): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  return value
}

type DatasetLabelFilterFormProps = {
  nodes: TaxonomyNodeDetail[]
  value: LabelFilters
  onChange: (next: LabelFilters) => void
}

export function DatasetLabelFilterForm({ nodes, value, onChange }: DatasetLabelFilterFormProps) {
  const [searchInput, setSearchInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])

  const lookup = useMemo(() => nodeById(nodes), [nodes])
  const searchResults = useMemo(() => searchNodes(nodes, searchQuery), [nodes, searchQuery])

  const selectedNodes = useMemo(
    () =>
      Object.entries(value)
        .filter(([, filterValue]) => filterValue !== '' && filterValue != null)
        .map(([labelId]) => lookup.get(labelId))
        .filter((node): node is TaxonomyNodeDetail => node != null),
    [lookup, value],
  )

  const autocompleteOptions = useMemo((): { value: string; label: ReactNode }[] => {
    const fromNodes = searchNodes(nodes, searchInput).map((node) => ({
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
    if (fromNodes.length > 0) return fromNodes
    return suggestions
      .filter((s) => s.toLowerCase().includes(searchInput.trim().toLowerCase()))
      .slice(0, 8)
      .map((s) => ({ value: s, label: <span>{s}</span> }))
  }, [nodes, searchInput, suggestions])

  useEffect(() => {
    void api.getLabelSuggestions().then(setSuggestions).catch(() => setSuggestions([]))
  }, [])

  const handleFieldChange = (labelId: string, next: string | boolean | undefined) => {
    const merged = { ...value }
    if (next === undefined) {
      delete merged[labelId]
    } else {
      merged[labelId] = next
    }
    onChange(merged)
  }

  const submitSearch = (raw?: string) => {
    const q = (raw ?? searchInput).trim()
    setSearchInput(q)
    setSearchQuery(q)
  }

  const pickLabel = (labelId: string) => {
    const node = lookup.get(labelId)
    if (node) {
      setSearchInput(node.name)
      setSearchQuery(node.label_id)
      return
    }
    submitSearch(labelId)
  }

  if (lookup.size === 0) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无已发布标签树，无法按标签筛选。
      </Typography.Text>
    )
  }

  const activeFilterCount = Object.entries(value).filter(
    ([, filterValue]) => filterValue !== '' && filterValue != null,
  ).length
  const visibleResultNodes = searchQuery
    ? searchResults
    : selectedNodes.length > 0
      ? []
      : []

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        搜索标签并设置取值（多条件 AND）；已选 {activeFilterCount} 项
      </Typography.Text>

      {activeFilterCount > 0 && (
        <Space wrap size={[8, 8]}>
          {Object.entries(value)
            .filter(([, filterValue]) => filterValue !== '' && filterValue != null)
            .map(([labelId, filterValue]) => {
            const node = lookup.get(labelId)
            return (
              <Tag
                key={labelId}
                closable
                onClose={() => handleFieldChange(labelId, undefined)}
              >
                {node?.name ?? labelId}={formatFilterValue(filterValue)}
              </Tag>
            )
          })}
        </Space>
      )}

      <AutoComplete
        options={autocompleteOptions}
        style={{ width: '100%' }}
        value={searchInput}
        onChange={setSearchInput}
        onSelect={(selected) => {
          const node = lookup.get(String(selected))
          if (node) {
            pickLabel(node.label_id)
            return
          }
          submitSearch(String(selected))
        }}
      >
        <Input.Search
          allowClear
          placeholder="搜索标签名称、ID、层级或枚举值"
          enterButton={<SearchOutlined />}
          onSearch={submitSearch}
        />
      </AutoComplete>

      {searchQuery && visibleResultNodes.length === 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          未找到匹配标签，请换个关键词
        </Typography.Text>
      )}

      {visibleResultNodes.length > 0 && (
        <div className="dataset-label-filter-results">
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            搜索结果 {visibleResultNodes.length} 项
          </Typography.Text>
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {visibleResultNodes.map((node) => (
              <div key={node.label_id} className="dataset-label-filter-result">
                <div className="dataset-label-filter-result__meta">
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {node.name}
                  </Typography.Text>
                  <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>
                    {node.label_id}
                    {node.level_name ? ` · ${node.level_name}` : ''}
                  </Typography.Text>
                </div>
                <LabelFilterField
                  node={node}
                  value={value[node.label_id]}
                  onChange={handleFieldChange}
                  compact
                />
              </div>
            ))}
          </Space>
        </div>
      )}

      {selectedNodes.length > 0 && (
        <div className="dataset-label-filter-selected">
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
            已选标签条件
          </Typography.Text>
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            {selectedNodes.map((node) => (
              <div key={node.label_id} className="dataset-label-filter-result">
                <div className="dataset-label-filter-result__meta">
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {node.name}
                  </Typography.Text>
                  <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>
                    {node.label_id}
                  </Typography.Text>
                </div>
                <LabelFilterField
                  node={node}
                  value={value[node.label_id]}
                  onChange={handleFieldChange}
                  compact
                />
              </div>
            ))}
          </Space>
        </div>
      )}

      {activeFilterCount === 0 && !searchQuery && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          输入关键词搜索标签，从结果中选择并设置取值
        </Typography.Text>
      )}
    </Space>
  )
}
