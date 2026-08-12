/**
 * Recursive form list for enum_tree values — same feel as flat enum inputs,
 * with a per-row「深层嵌套」switch to add children.
 */
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Form, Input, Space, Switch, Typography } from 'antd'
import { useEffect, useState } from 'react'

type NamePath = (string | number)[]

type EnumTreeNodesFormProps = {
  /**
   * Absolute path to this list in the form store (for useWatch / setFieldValue).
   * Root call: ['enum_tree_nodes'].
   */
  absPath: NamePath
  /**
   * Name passed to Form.List — root: 'enum_tree_nodes';
   * nested under a parent list item: [parentFieldName, 'children'].
   */
  listName: string | number | (string | number)[]
  depth?: number
  maxDepth?: number
}

export function EnumTreeNodesForm({
  absPath,
  listName,
  depth = 0,
  maxDepth = 6,
}: EnumTreeNodesFormProps) {
  const canNestDeeper = depth < maxDepth - 1

  return (
    <Form.List name={listName}>
      {(fields, { add, remove }) => (
        <Form.Item
          label={depth === 0 ? '枚举选项' : undefined}
          tooltip={
            depth === 0
              ? '填写选项值；打开「深层嵌套」后可继续添加子级（单层即原扁平枚举）'
              : undefined
          }
          style={{ marginBottom: depth === 0 ? 24 : 8 }}
        >
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {fields.map((field) => (
              <EnumTreeNodeRow
                key={field.key}
                fieldName={field.name}
                absPath={absPath}
                depth={depth}
                maxDepth={maxDepth}
                canNestDeeper={canNestDeeper}
                canRemove={fields.length > 1}
                onRemove={() => remove(field.name)}
              />
            ))}
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => add({ id: '', nested: false, children: [{ id: '', nested: false }] })}
              block={depth === 0}
            >
              {depth === 0 ? '添加选项' : '添加子选项'}
            </Button>
          </Space>
        </Form.Item>
      )}
    </Form.List>
  )
}

/** Root field used by TaxonomyTreeEditor. */
export function EnumTreeNodesFormRoot() {
  return <EnumTreeNodesForm absPath={['enum_tree_nodes']} listName="enum_tree_nodes" />
}

function EnumTreeNodeRow({
  fieldName,
  absPath,
  depth,
  maxDepth,
  canNestDeeper,
  canRemove,
  onRemove,
}: {
  fieldName: number
  absPath: NamePath
  depth: number
  maxDepth: number
  canNestDeeper: boolean
  canRemove: boolean
  onRemove: () => void
}) {
  const form = Form.useFormInstance()
  const nestedAbs = [...absPath, fieldName, 'nested']
  const childrenAbs = [...absPath, fieldName, 'children']
  const watchedNested = Form.useWatch(nestedAbs, form)
  const [showChildren, setShowChildren] = useState(Boolean(watchedNested))

  useEffect(() => {
    setShowChildren(Boolean(watchedNested))
  }, [watchedNested])

  return (
    <div
      style={{
        padding: depth > 0 ? '8px 0 8px 12px' : 0,
        borderLeft: depth > 0 ? '2px solid var(--ant-color-border-secondary, #f0f0f0)' : undefined,
      }}
    >
      <Space align="start" wrap style={{ width: '100%' }}>
        <Form.Item
          name={[fieldName, 'id']}
          rules={[{ required: true, message: '请输入选项值' }]}
          noStyle
        >
          <Input
            placeholder={depth === 0 ? '选项值 / 分组 id' : '子选项值'}
            style={{ width: Math.max(180, 300 - depth * 24) }}
          />
        </Form.Item>
        {canNestDeeper ? (
          <Space size={6} align="center">
            <Form.Item name={[fieldName, 'nested']} valuePropName="checked" noStyle>
              <Switch
                checkedChildren="嵌套"
                unCheckedChildren="叶子"
                onChange={(checked) => {
                  setShowChildren(checked)
                  if (checked) {
                    const kids = form.getFieldValue(childrenAbs)
                    if (!Array.isArray(kids) || kids.length === 0) {
                      form.setFieldValue(childrenAbs, [
                        { id: '', nested: false, children: [{ id: '', nested: false }] },
                      ])
                    }
                  }
                }}
              />
            </Form.Item>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              深层嵌套
            </Typography.Text>
          </Space>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12, lineHeight: '32px' }}>
            已达最大深度 {maxDepth}
          </Typography.Text>
        )}
        <Button type="text" danger icon={<MinusCircleOutlined />} onClick={onRemove} disabled={!canRemove} />
      </Space>

      {showChildren && canNestDeeper ? (
        <div style={{ marginTop: 8 }}>
          <EnumTreeNodesForm
            absPath={childrenAbs}
            listName={[fieldName, 'children']}
            depth={depth + 1}
            maxDepth={maxDepth}
          />
        </div>
      ) : null}
    </div>
  )
}
