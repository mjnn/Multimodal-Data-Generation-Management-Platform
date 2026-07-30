export type LeafSchemaFormFields = {
  enum_options?: string[]
  bool_true_label?: string
  bool_false_label?: string
  string_example?: string
}

export function schemaToFormFields(
  dtype: string | null | undefined,
  schema: unknown,
): LeafSchemaFormFields {
  if (!schema || typeof schema !== 'object') {
    return { enum_options: [''] }
  }
  const s = schema as Record<string, unknown>
  if (dtype === 'enum') {
    const values = Array.isArray(s.values) ? s.values.map(String) : []
    return { enum_options: values.length ? values : [''] }
  }
  if (dtype === 'bool') {
    return {
      bool_true_label: String(s.true_label ?? s.trueLabel ?? '是'),
      bool_false_label: String(s.false_label ?? s.falseLabel ?? '否'),
    }
  }
  if (dtype === 'string') {
    return { string_example: String(s.example ?? '') }
  }
  return {}
}

export function buildValueSchema(
  dtype: string | null | undefined,
  fields: LeafSchemaFormFields,
): unknown | null {
  if (!dtype) return null
  if (dtype === 'enum') {
    const values = (fields.enum_options ?? []).map((v) => v.trim()).filter(Boolean)
    if (!values.length) {
      throw new Error('请至少添加一个枚举选项')
    }
    return { type: 'enum', values }
  }
  if (dtype === 'bool') {
    return {
      type: 'bool',
      true_label: (fields.bool_true_label ?? '是').trim() || '是',
      false_label: (fields.bool_false_label ?? '否').trim() || '否',
    }
  }
  if (dtype === 'string') {
    const example = (fields.string_example ?? '').trim()
    return example ? { type: 'string', example } : { type: 'string' }
  }
  return null
}
