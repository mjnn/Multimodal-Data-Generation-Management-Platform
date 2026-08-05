import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Input, InputNumber, Select, Space, Table, Typography } from 'antd'
import { useMemo } from 'react'
import type { LabelDistributionConfig, TaxonomyNodeDetail } from '../api/types'
import { formatLabelValue, schemaEnumValues } from '../utils/labelDisplay'

function activeNodes(nodes: TaxonomyNodeDetail[]): TaxonomyNodeDetail[] {
  return nodes
    .filter((n) => n.is_active !== false)
    .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
}

function rawEnumKeys(node: TaxonomyNodeDetail): string[] {
  if (node.dtype === 'bool') return ['true', 'false']
  const schema = node.value_schema
  if (schema && typeof schema === 'object' && Array.isArray((schema as { values?: unknown[] }).values)) {
    return (schema as { values: unknown[] }).values.map(String)
  }
  return schemaEnumValues(node)
}

function enumDisplay(node: TaxonomyNodeDetail, key: string): string {
  if (node.dtype === 'bool') {
    return key === 'true' ? '是' : '否'
  }
  return formatLabelValue(key, node)
}

function isEnumLike(node: TaxonomyNodeDetail | undefined): boolean {
  if (!node) return false
  if (node.dtype === 'bool' || node.dtype === 'enum') return true
  return rawEnumKeys(node).length > 0
}

function emptyDistribution(labelId: string, node: TaxonomyNodeDetail): LabelDistributionConfig {
  if (isEnumLike(node)) {
    const keys = rawEnumKeys(node)
    const weights: Record<string, number | undefined> = {}
    for (const k of keys) weights[k] = undefined
    return { label_id: labelId, kind: 'enum', weights }
  }
  return { label_id: labelId, kind: 'string', buckets: [] }
}

export function validateLabelDistribution(config: LabelDistributionConfig | null): string | null {
  if (!config?.label_id) return null
  if (config.kind === 'string') {
    for (const bucket of config.buckets) {
      const hasExact = bucket.match === 'exact' && bucket.value?.trim()
      const hasRange = bucket.match === 'range' && (bucket.min?.trim() || bucket.max?.trim())
      if ((hasExact || hasRange) && (bucket.weight == null || bucket.weight <= 0)) {
        return '已填写取值或范围时，必须填写占比（%）'
      }
    }
  }
  return null
}

export function hasActiveLabelDistribution(config: LabelDistributionConfig | null): boolean {
  if (!config?.label_id) return false
  if (config.kind === 'enum') {
    return Object.values(config.weights).some((w) => w != null && w > 0)
  }
  return config.buckets.some(
    (b) =>
      b.weight != null &&
      b.weight > 0 &&
      ((b.match === 'exact' && Boolean(b.value?.trim())) ||
        (b.match === 'range' && Boolean(b.min?.trim() || b.max?.trim()))),
  )
}

type Props = {
  nodes: TaxonomyNodeDetail[]
  value: LabelDistributionConfig | null
  onChange: (next: LabelDistributionConfig | null) => void
}

export function DatasetLabelDistributionForm({ nodes, value, onChange }: Props) {
  const lookup = useMemo(() => new Map(activeNodes(nodes).map((n) => [n.label_id, n])), [nodes])
  const selectedNode = value?.label_id ? lookup.get(value.label_id) : undefined

  const labelOptions = activeNodes(nodes).map((node) => ({
    value: node.label_id,
    label: `${node.name} (${node.label_id})`,
  }))

  const onSelectLabel = (labelId: string | null) => {
    if (!labelId) {
      onChange(null)
      return
    }
    const node = lookup.get(labelId)
    if (!node) {
      onChange(null)
      return
    }
    onChange(emptyDistribution(labelId, node))
  }

  const updateEnumWeight = (enumKey: string, pct: number | null) => {
    if (!value || value.kind !== 'enum') return
    onChange({
      ...value,
      weights: { ...value.weights, [enumKey]: pct ?? undefined },
    })
  }

  const addStringBucket = () => {
    if (!value || value.kind !== 'string') return
    onChange({
      ...value,
      buckets: [
        ...value.buckets,
        { id: `b-${Date.now()}`, match: 'exact', value: '', weight: undefined },
      ],
    })
  }

  const updateStringBucket = (
    id: string,
    patch: Partial<{ match: 'exact' | 'range'; value: string; min: string; max: string; weight: number | undefined }>,
  ) => {
    if (!value || value.kind !== 'string') return
    onChange({
      ...value,
      buckets: value.buckets.map((b) => {
        if (b.id !== id) return b
        const merged = { ...b, ...patch }
        if (merged.weight == null) delete merged.weight
        return merged
      }),
    })
  }

  const removeStringBucket = (id: string) => {
    if (!value || value.kind !== 'string') return
    onChange({
      ...value,
      buckets: value.buckets.filter((b) => b.id !== id),
    })
  }

  if (lookup.size === 0) {
    return (
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        暂无已发布标签树，无法配置标签值分布。
      </Typography.Text>
    )
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }} data-testid="label-distribution-form">
      <div>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          选择标签
        </Typography.Text>
        <Select
          allowClear
          showSearch
          placeholder="选择要控制分布的标签"
          style={{ width: '100%' }}
          value={value?.label_id}
          options={labelOptions}
          optionFilterProp="label"
          onChange={(v) => onSelectLabel(v ?? null)}
        />
      </div>

      {selectedNode && value?.kind === 'enum' ? (
        <div>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            为该标签各枚举值指定在数据集中的占比（%）。未填写的取值将随机分配剩余比例。
          </Typography.Paragraph>
          <Table
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={rawEnumKeys(selectedNode).map((key) => ({
              key,
              label: enumDisplay(selectedNode, key),
            }))}
            columns={[
              { title: '枚举值', dataIndex: 'label', key: 'label' },
              {
                title: '占比（%）',
                key: 'weight',
                width: 140,
                render: (_, row) => (
                  <InputNumber
                    min={0}
                    max={100}
                    placeholder="随机"
                    style={{ width: '100%' }}
                    value={value.weights[row.key]}
                    onChange={(n) => updateEnumWeight(row.key, n)}
                  />
                ),
              },
            ]}
          />
        </div>
      ) : null}

      {selectedNode && value?.kind === 'string' ? (
        <div>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            添加一个或多个取值范围或具体值，并填写对应占比（%）。填写了范围/值时必须填写占比。
          </Typography.Paragraph>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {value.buckets.map((bucket) => (
              <Space key={bucket.id} align="start" wrap style={{ width: '100%' }}>
                <Select
                  style={{ width: 120 }}
                  value={bucket.match}
                  options={[
                    { value: 'exact', label: '具体值' },
                    { value: 'range', label: '范围' },
                  ]}
                  onChange={(match) =>
                    updateStringBucket(bucket.id, {
                      match,
                      value: '',
                      min: '',
                      max: '',
                    })
                  }
                />
                {bucket.match === 'exact' ? (
                  <Input
                    placeholder="字符串取值"
                    style={{ minWidth: 160 }}
                    value={bucket.value}
                    onChange={(e) => updateStringBucket(bucket.id, { value: e.target.value })}
                  />
                ) : (
                  <>
                    <Input
                      placeholder="起始（含）"
                      style={{ width: 120 }}
                      value={bucket.min}
                      onChange={(e) => updateStringBucket(bucket.id, { min: e.target.value })}
                    />
                    <Typography.Text type="secondary">至</Typography.Text>
                    <Input
                      placeholder="结束（含）"
                      style={{ width: 120 }}
                      value={bucket.max}
                      onChange={(e) => updateStringBucket(bucket.id, { max: e.target.value })}
                    />
                  </>
                )}
                <InputNumber
                  min={0}
                  max={100}
                  placeholder="占比 %"
                  style={{ width: 100 }}
                  value={bucket.weight}
                    onChange={(n) => updateStringBucket(bucket.id, { weight: n ?? undefined })}
                />
                <Button
                  type="text"
                  danger
                  icon={<MinusCircleOutlined />}
                  aria-label="移除"
                  onClick={() => removeStringBucket(bucket.id)}
                />
              </Space>
            ))}
            <Button type="dashed" icon={<PlusOutlined />} onClick={addStringBucket} block>
              添加取值或范围
            </Button>
          </Space>
        </div>
      ) : null}

      {!value?.label_id ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          留空表示不按标签值分布约束，纳入全部符合校核条件的 clip（可在下一步设置随机取样）。
        </Typography.Text>
      ) : null}
    </Space>
  )
}
