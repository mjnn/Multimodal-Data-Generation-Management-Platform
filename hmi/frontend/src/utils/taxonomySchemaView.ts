import type { DataNode } from 'antd/es/tree'
import type { TaxonomyNodeDetail } from '../api/types'
import {
  coerceEnumTreeNodes,
  isEnumTreeSchema,
  type EnumTreeNode,
} from './enumTree'
import { enumDisplayOptions } from './labelDisplay'

const DTYPE_LABELS: Record<string, string> = {
  enum: '枚举',
  enum_tree: '枚举',
  bool: '布尔',
  string: '字符串',
}

/** Synthetic tree keys for enum option nodes under a taxonomy leaf. */
export const ENUM_VALUE_KEY_PREFIX = 'enumval:'

export function isEnumValueKey(key: string): boolean {
  return key.startsWith(ENUM_VALUE_KEY_PREFIX)
}

function isEnumLikeDtype(dtype: string, schema: unknown): boolean {
  const d = dtype.toLowerCase()
  return d === 'enum' || d === 'enum_tree' || isEnumTreeSchema(schema)
}

function enumNodeTitle(n: EnumTreeNode, labels: Record<string, string>): string {
  const label = labels[n.id] ?? n.name ?? n.id
  return label === n.id ? n.id : `${label} (${n.id})`
}

/** Nested Ant Tree nodes for an enum_tree (or legacy flat enum) value list. */
export function enumTreeToDataNodes(
  labelId: string,
  nodes: EnumTreeNode[],
  labels: Record<string, string> = {},
  pathPrefix = '',
): DataNode[] {
  return nodes.map((n, idx) => {
    const path = pathPrefix ? `${pathPrefix}-${idx}` : String(idx)
    const hasKids = Boolean(n.children?.length)
    return {
      key: `${ENUM_VALUE_KEY_PREFIX}${labelId}:${path}`,
      title: enumNodeTitle(n, labels),
      selectable: false,
      disableCheckbox: true,
      isLeaf: !hasKids,
      children: hasKids
        ? enumTreeToDataNodes(labelId, n.children!, labels, path)
        : undefined,
    }
  })
}

/**
 * Enum option nodes only (no dtype / definition wrappers).
 * Used by the editable outer TaxonomyTreeEditor so nesting is visible without opening the leaf modal.
 */
export function taxonomyEnumOuterNodes(node: TaxonomyNodeDetail): DataNode[] {
  const dtype = (node.dtype || '').toLowerCase()
  const schema = node.value_schema
  if (!isEnumLikeDtype(dtype, schema)) return []
  if (!schema || typeof schema !== 'object') return []
  const s = schema as { values?: unknown[]; labels?: Record<string, string> }
  const nodes = coerceEnumTreeNodes(s.values)
  if (nodes.length) {
    return enumTreeToDataNodes(node.label_id, nodes, s.labels ?? {})
  }
  const options = enumDisplayOptions(node)
  if (!options.length) return []
  return options.map((opt, idx) => ({
    key: `${ENUM_VALUE_KEY_PREFIX}${node.label_id}:${idx}`,
    title: opt.label,
    selectable: false,
    disableCheckbox: true,
    isLeaf: true,
  }))
}

export function taxonomySchemaDetailNodes(node: TaxonomyNodeDetail): DataNode[] {
  const dtype = (node.dtype || 'string').toLowerCase()
  const schema = node.value_schema
  const effectiveDtype = isEnumLikeDtype(dtype, schema) ? 'enum_tree' : dtype
  const typeLabel = DTYPE_LABELS[effectiveDtype] ?? effectiveDtype
  const rows: DataNode[] = [
    {
      key: `${node.label_id}__dtype`,
      title: `取值类型：${typeLabel}`,
      isLeaf: true,
      selectable: false,
      disableCheckbox: true,
    },
  ]

  if (effectiveDtype === 'enum_tree' && schema && typeof schema === 'object') {
    const enumChildren = taxonomyEnumOuterNodes(node)
    if (enumChildren.length) {
      rows.push({
        key: `${node.label_id}__enum_tree`,
        title: '枚举选项',
        selectable: false,
        disableCheckbox: true,
        children: enumChildren,
      })
    }
  } else if (dtype === 'bool' && schema && typeof schema === 'object') {
    const s = schema as { true_label?: string; false_label?: string }
    rows.push({
      key: `${node.label_id}__bool`,
      title: `示例：是 → ${s.true_label ?? '是'}，否 → ${s.false_label ?? '否'}`,
      isLeaf: true,
      selectable: false,
      disableCheckbox: true,
    })
  } else if (dtype === 'string' && schema && typeof schema === 'object') {
    const example = String((schema as { example?: string }).example ?? '').trim()
    if (example) {
      rows.push({
        key: `${node.label_id}__example`,
        title: `示例值：${example}`,
        isLeaf: true,
        selectable: false,
        disableCheckbox: true,
      })
    }
  }

  if (node.definition?.trim()) {
    rows.push({
      key: `${node.label_id}__def`,
      title: `定义：${node.definition.trim()}`,
      isLeaf: true,
      selectable: false,
      disableCheckbox: true,
    })
  }

  return rows
}
