import {
  coerceEnumTreeNodes,
  emptyEnumTreeFormNodes,
  enumTreeToFormNodes,
  formNodesToEnumTree,
  isEnumTreeSchema,
  validateEnumTreeNodes,
  type EnumTreeFormNode,
} from './enumTree'

export type LeafSchemaFormFields = {
  /** @deprecated Flat enum options; legacy load migrates to enum_tree_nodes. */
  enum_options?: string[]
  /** Value tree rows for dtype=enum_tree (single-level = former flat enum). */
  enum_tree_nodes?: EnumTreeFormNode[]
  bool_true_label?: string
  bool_false_label?: string
  string_example?: string
}

/** Editor Select / save: flat `enum` is a single-level `enum_tree`. */
export function normalizeEditorDtype(dtype: string | null | undefined): string {
  const d = (dtype || '').toLowerCase()
  if (!d || d === 'enum') return 'enum_tree'
  return d
}

export function schemaToFormFields(
  dtype: string | null | undefined,
  schema: unknown,
): LeafSchemaFormFields {
  if (!schema || typeof schema !== 'object') {
    return { enum_tree_nodes: emptyEnumTreeFormNodes() }
  }
  const s = schema as Record<string, unknown>
  const dtypeNorm = (dtype || '').toLowerCase()
  // Flat enum / enum_tree / object-shaped values → one enum_tree form.
  if (
    dtypeNorm === 'enum_tree' ||
    dtypeNorm === 'enum' ||
    isEnumTreeSchema(schema) ||
    (Array.isArray(s.values) && s.values.length > 0)
  ) {
    const nodes = coerceEnumTreeNodes(Array.isArray(s.values) ? s.values : [])
    return {
      enum_tree_nodes: nodes.length ? enumTreeToFormNodes(nodes) : emptyEnumTreeFormNodes(),
    }
  }
  if (dtypeNorm === 'bool') {
    return {
      bool_true_label: String(s.true_label ?? s.trueLabel ?? '是'),
      bool_false_label: String(s.false_label ?? s.falseLabel ?? '否'),
    }
  }
  if (dtypeNorm === 'string') {
    return { string_example: String(s.example ?? '') }
  }
  return {}
}

export function buildValueSchema(
  dtype: string | null | undefined,
  fields: LeafSchemaFormFields,
): unknown | null {
  if (!dtype) return null
  const effective = normalizeEditorDtype(dtype)
  if (effective === 'enum_tree') {
    // Prefer tree form; fall back to legacy enum_options if present.
    let nodes = formNodesToEnumTree(fields.enum_tree_nodes)
    if (!nodes.length && fields.enum_options?.length) {
      nodes = coerceEnumTreeNodes(fields.enum_options)
    }
    const errors = validateEnumTreeNodes(nodes)
    if (errors.length) {
      throw new Error(errors[0])
    }
    return { type: 'enum_tree', values: nodes }
  }
  if (effective === 'bool') {
    return {
      type: 'bool',
      true_label: (fields.bool_true_label ?? '是').trim() || '是',
      false_label: (fields.bool_false_label ?? '否').trim() || '否',
    }
  }
  if (effective === 'string') {
    const example = (fields.string_example ?? '').trim()
    return example ? { type: 'string', example } : { type: 'string' }
  }
  return null
}
