import { Select, Space, Typography } from 'antd'
import {
  coerceEnumTreeNodes,
  enumChildrenAt,
  inspectEnumReviewValue,
  isNestedEnumSchema,
  resolveEnumPath,
  toStoredEnumReviewValue,
  type EnumTreeNode,
} from '../utils/enumTree'

type Props = {
  value?: unknown
  onChange?: (value: unknown) => void
  schema: unknown
  dtype?: string | null
  disabled?: boolean
  size?: 'small' | 'middle' | 'large'
}

function optionLabel(node: EnumTreeNode): string {
  return node.name?.trim() ? `${node.name} (${node.id})` : node.id
}

export function EnumCascadeSelect({
  value,
  onChange,
  schema,
  dtype,
  disabled,
  size = 'middle',
}: Props) {
  const values =
    schema && typeof schema === 'object' && 'values' in schema
      ? (schema as { values?: unknown[] }).values
      : undefined
  const nodes = coerceEnumTreeNodes(values)
  const nested = isNestedEnumSchema(schema, dtype)
  const resolved = resolveEnumPath(nodes, value) ?? []
  const inspect = inspectEnumReviewValue(schema, value, dtype)

  const levels: EnumTreeNode[][] = [nodes]
  for (let i = 0; i < resolved.length; i++) {
    const kids = enumChildrenAt(nodes, resolved.slice(0, i + 1))
    if (kids.length) levels.push(kids)
    else break
  }

  const setLevel = (levelIdx: number, id: string | undefined) => {
    const next = resolved.slice(0, levelIdx)
    if (id) next.push(id)
    onChange?.(toStoredEnumReviewValue(schema, next, dtype))
  }

  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }} data-testid="review-enum-cascade">
      {levels.map((options, idx) => (
        <Select
          key={idx}
          allowClear
          disabled={disabled}
          size={size}
          style={{ width: '100%' }}
          placeholder={idx === 0 ? '选择第 1 级' : `选择第 ${idx + 1} 级`}
          value={resolved[idx]}
          options={options.map((n) => ({ value: n.id, label: optionLabel(n) }))}
          onChange={(v) => setLevel(idx, v)}
          data-testid={`review-enum-cascade-level-${idx}`}
        />
      ))}
      {nested && !inspect.complete ? (
        <Typography.Text type="warning" data-testid="review-enum-incomplete-hint">
          {inspect.message}
        </Typography.Text>
      ) : null}
    </Space>
  )
}
