import type { DataNode } from 'antd/es/tree'
import type { TaxonomyNodeDetail } from '../api/types'
import { enumDisplayOptions } from './labelDisplay'

const DTYPE_LABELS: Record<string, string> = {
  enum: '枚举',
  bool: '布尔',
  string: '字符串',
}

export function taxonomySchemaDetailNodes(node: TaxonomyNodeDetail): DataNode[] {
  const dtype = (node.dtype || 'string').toLowerCase()
  const typeLabel = DTYPE_LABELS[dtype] ?? dtype
  const rows: DataNode[] = [
    {
      key: `${node.label_id}__dtype`,
      title: `取值类型：${typeLabel}`,
      isLeaf: true,
      selectable: false,
    },
  ]

  const schema = node.value_schema
  if (dtype === 'enum') {
    const options = enumDisplayOptions(node)
    if (options.length) {
      rows.push({
        key: `${node.label_id}__enum`,
        title: '可枚举项',
        selectable: false,
        children: options.map((opt, idx) => ({
          key: `${node.label_id}__enum__${idx}`,
          title: opt.label,
          isLeaf: true,
          selectable: false,
        })),
      })
    } else if (schema && typeof schema === 'object') {
      const values = (schema as { values?: unknown[] }).values
      if (Array.isArray(values) && values.length) {
        rows.push({
          key: `${node.label_id}__enum`,
          title: '可枚举项',
          selectable: false,
          children: values.map((v, idx) => ({
            key: `${node.label_id}__enum__${idx}`,
            title: String(v),
            isLeaf: true,
            selectable: false,
          })),
        })
      }
    }
  } else if (dtype === 'bool' && schema && typeof schema === 'object') {
    const s = schema as { true_label?: string; false_label?: string }
    rows.push({
      key: `${node.label_id}__bool`,
      title: `示例：是 → ${s.true_label ?? '是'}，否 → ${s.false_label ?? '否'}`,
      isLeaf: true,
      selectable: false,
    })
  } else if (dtype === 'string' && schema && typeof schema === 'object') {
    const example = String((schema as { example?: string }).example ?? '').trim()
    if (example) {
      rows.push({
        key: `${node.label_id}__example`,
        title: `示例值：${example}`,
        isLeaf: true,
        selectable: false,
      })
    }
  }

  if (node.definition?.trim()) {
    rows.push({
      key: `${node.label_id}__def`,
      title: `定义：${node.definition.trim()}`,
      isLeaf: true,
      selectable: false,
    })
  }

  return rows
}
