import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import {
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tree,
  Typography,
  message,
} from 'antd'
import type { DataNode } from 'antd/es/tree'
import type { Key, ReactNode } from 'react'
import { useEffect, useMemo, useState } from 'react'
import type { TaxonomyNodeDetail } from '../api/types'
import type { EnumTreeFormNode } from '../utils/enumTree'
import { emptyEnumTreeFormNodes } from '../utils/enumTree'
import { isEnumValueKey } from '../utils/taxonomySchemaView'
import {
  groupTaxonomyLevels,
  levelCodes,
  parseLevelKey,
  removeLevel,
  renameLevel,
  reorderTaxonomyLevels,
  toEditorTreeData,
  type TaxonomyLevelMeta,
} from '../utils/taxonomyTree'
import { EnumTreeNodesFormRoot } from './EnumTreeNodesForm'
import {
  buildValueSchema,
  normalizeEditorDtype,
  schemaToFormFields,
} from '../utils/taxonomyLeafSchema'

type LevelFormValues = {
  level_code: string
  level_name: string
}

type LeafFormValues = {
  label_id: string
  name: string
  definition?: string
  dtype?: string
  enum_options?: string[]
  enum_tree_nodes?: EnumTreeFormNode[]
  bool_true_label?: string
  bool_false_label?: string
  string_example?: string
  is_active: boolean
}

type TaxonomyTreeEditorProps = {
  versionId: string
  nodes: TaxonomyNodeDetail[]
  emptyLevels: TaxonomyLevelMeta[]
  canEdit: boolean
  onNodesChange: (nodes: TaxonomyNodeDetail[]) => void
  onEmptyLevelsChange: (levels: TaxonomyLevelMeta[]) => void
}

function nextSortOrder(nodes: TaxonomyNodeDetail[], levelCode: string): number {
  const inLevel = nodes.filter((n) => n.level_code === levelCode)
  if (!inLevel.length) return 0
  return Math.max(...inLevel.map((n) => n.sort_order)) + 1
}

function newLeafNode(
  versionId: string,
  level: TaxonomyLevelMeta,
  values: LeafFormValues,
  valueSchema: unknown,
  sortOrder: number,
): TaxonomyNodeDetail {
  return {
    id: crypto.randomUUID(),
    taxonomy_version_id: versionId,
    parent_id: null,
    level_code: level.level_code,
    level_name: level.level_name,
    label_id: values.label_id.trim(),
    name: values.name.trim(),
    definition: values.definition?.trim() || null,
    dtype: values.dtype || null,
    value_schema: valueSchema,
    sort_order: sortOrder,
    is_active: values.is_active,
  }
}

export function TaxonomyTreeEditor({
  versionId,
  nodes,
  emptyLevels,
  canEdit,
  onNodesChange,
  onEmptyLevelsChange,
}: TaxonomyTreeEditorProps) {
  const [selectedKey, setSelectedKey] = useState<string>()
  const [levelModalOpen, setLevelModalOpen] = useState(false)
  const [levelEditing, setLevelEditing] = useState<TaxonomyLevelMeta | null>(null)
  const [leafModalOpen, setLeafModalOpen] = useState(false)
  const [leafEditing, setLeafEditing] = useState<TaxonomyNodeDetail | null>(null)
  const [leafLevel, setLeafLevel] = useState<TaxonomyLevelMeta | null>(null)

  const [levelForm] = Form.useForm<LevelFormValues>()
  const [leafForm] = Form.useForm<LeafFormValues>()

  const groups = useMemo(
    () => groupTaxonomyLevels(nodes, emptyLevels),
    [nodes, emptyLevels],
  )
  const treeData = useMemo(() => toEditorTreeData(groups, canEdit), [groups, canEdit])
  const levelExpandKeys = useMemo(
    () => groups.map((g) => `level:${g.level_code}`),
    [groups],
  )
  // Expand levels by default so labels are visible; leave enum nesting collapsed for layer-by-layer expand.
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([])
  useEffect(() => {
    setExpandedKeys((prev) => {
      const prevSet = new Set(prev.map(String))
      const next = prev.filter((k) => {
        const s = String(k)
        if (s.startsWith('level:')) return levelExpandKeys.includes(s)
        return true
      })
      for (const k of levelExpandKeys) {
        if (!prevSet.has(k)) next.push(k)
      }
      return next
    })
  }, [levelExpandKeys])

  const selectedLevelCode = selectedKey ? parseLevelKey(selectedKey) : null
  const selectedLeaf = selectedKey && !selectedLevelCode && !isEnumValueKey(selectedKey)
    ? nodes.find((n) => n.label_id === selectedKey) ?? null
    : null

  const openCreateLevel = () => {
    setLevelEditing(null)
    levelForm.resetFields()
    setLevelModalOpen(true)
  }

  const openEditLevel = (level: TaxonomyLevelMeta) => {
    setLevelEditing(level)
    levelForm.setFieldsValue(level)
    setLevelModalOpen(true)
  }

  const saveLevel = async () => {
    const values = await levelForm.validateFields()
    const code = values.level_code.trim()
    const name = values.level_name.trim()
    const codes = levelCodes(nodes, emptyLevels)

    if (levelEditing) {
      if (levelEditing.level_code !== code && codes.has(code)) {
        message.error('层级 code 已存在')
        return
      }
      const renamed = renameLevel(nodes, emptyLevels, levelEditing.level_code, {
        level_code: code,
        level_name: name,
      })
      onNodesChange(renamed.nodes)
      onEmptyLevelsChange(renamed.emptyLevels)
    } else {
      if (codes.has(code)) {
        message.error('层级 code 已存在')
        return
      }
      const maxSort = Math.max(
        -1,
        ...nodes.map((n) => n.sort_order),
        ...emptyLevels.map((l) => l.sort_order ?? -1),
      )
      onEmptyLevelsChange([
        ...emptyLevels,
        { level_code: code, level_name: name, sort_order: maxSort + 1000 },
      ])
    }
    setLevelModalOpen(false)
    setLevelEditing(null)
    levelForm.resetFields()
  }

  const deleteLevel = (levelCode: string) => {
    const next = removeLevel(nodes, emptyLevels, levelCode)
    onNodesChange(next.nodes)
    onEmptyLevelsChange(next.emptyLevels)
    if (selectedKey === `level:${levelCode}` || selectedLeaf?.level_code === levelCode) {
      setSelectedKey(undefined)
    }
  }

  const openCreateLeaf = (level: TaxonomyLevelMeta) => {
    setLeafEditing(null)
    setLeafLevel(level)
    leafForm.resetFields()
    leafForm.setFieldsValue({
      is_active: true,
      dtype: 'enum_tree',
      enum_tree_nodes: emptyEnumTreeFormNodes(),
    })
    setLeafModalOpen(true)
  }

  const openEditLeaf = (node: TaxonomyNodeDetail) => {
    setLeafEditing(node)
    setLeafLevel({ level_code: node.level_code, level_name: node.level_name || node.level_code })
    leafForm.setFieldsValue({
      label_id: node.label_id,
      name: node.name,
      definition: node.definition ?? '',
      dtype: normalizeEditorDtype(node.dtype),
      is_active: node.is_active !== false,
      ...schemaToFormFields(node.dtype, node.value_schema),
    })
    setLeafModalOpen(true)
  }

  const saveLeaf = async () => {
    if (!leafLevel) return
    const values = await leafForm.validateFields()
    const dtype = normalizeEditorDtype(values.dtype)
    let valueSchema: unknown = null
    try {
      valueSchema = buildValueSchema(dtype, values)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'schema 无效')
      return
    }

    if (leafEditing) {
      onNodesChange(
        nodes.map((n) =>
          n.label_id === leafEditing.label_id
            ? {
                ...n,
                name: values.name.trim(),
                definition: values.definition?.trim() || null,
                dtype,
                value_schema: valueSchema,
                is_active: values.is_active,
              }
            : n,
        ),
      )
    } else {
      const labelId = values.label_id.trim()
      if (nodes.some((n) => n.label_id === labelId)) {
        message.error('label_id 已存在')
        return
      }
      onNodesChange([
        ...nodes,
        newLeafNode(
          versionId,
          leafLevel,
          { ...values, dtype },
          valueSchema,
          nextSortOrder(nodes, leafLevel.level_code),
        ),
      ])
      onEmptyLevelsChange(emptyLevels.filter((l) => l.level_code !== leafLevel.level_code))
    }

    setLeafModalOpen(false)
    setLeafEditing(null)
    setLeafLevel(null)
    leafForm.resetFields()
  }

  const deleteLeaf = (labelId: string) => {
    const target = nodes.find((n) => n.label_id === labelId)
    const nextNodes = nodes.filter((n) => n.label_id !== labelId)
    onNodesChange(nextNodes)
    if (target) {
      const stillHasSiblings = nextNodes.some(
        (n) => n.level_code === target.level_code && n.is_active !== false,
      )
      if (
        !stillHasSiblings &&
        !emptyLevels.some((l) => l.level_code === target.level_code)
      ) {
        onEmptyLevelsChange([
          ...emptyLevels,
          {
            level_code: target.level_code,
            level_name: target.level_name || target.level_code,
            sort_order: target.sort_order,
          },
        ])
      }
    }
    if (selectedKey === labelId) setSelectedKey(undefined)
  }

  const onDrop = (info: {
    dragNode: { key: Key }
    node: { key: Key; pos?: string }
    dropToGap: boolean
    dropPosition: number
  }) => {
    const dragKey = String(info.dragNode.key)
    const dropKey = String(info.node.key)
    // Enum option nodes are display-only in the outer tree
    if (isEnumValueKey(dragKey) || isEnumValueKey(dropKey)) return

    const dragLevel = parseLevelKey(dragKey)
    const dropLevel = parseLevelKey(dropKey)

    // Reorder whole levels
    if (dragLevel) {
      if (!dropLevel || dragLevel === dropLevel) return
      const codes = groups.map((g) => g.level_code)
      if (!codes.includes(dragLevel) || !codes.includes(dropLevel)) return
      const without = codes.filter((c) => c !== dragLevel)
      let insertAt = without.indexOf(dropLevel)
      if (insertAt < 0) return
      const dropPosParts = String(info.node.pos || '').split('-')
      const dropPosIndex = Number(dropPosParts[dropPosParts.length - 1] ?? 0)
      const relative = info.dropPosition - dropPosIndex
      // relative: -1 before, 0 inside, 1 after — levels only allow before/after
      if (relative >= 0) insertAt += 1
      without.splice(insertAt, 0, dragLevel)
      const reordered = reorderTaxonomyLevels(nodes, emptyLevels, without)
      onNodesChange(reordered.nodes)
      onEmptyLevelsChange(reordered.emptyLevels)
      return
    }

    // Reorder leaves within the same level
    if (dropLevel) return
    const dragLeaf = nodes.find((n) => n.label_id === dragKey)
    const dropLeaf = nodes.find((n) => n.label_id === dropKey)
    if (!dragLeaf || !dropLeaf || dragLeaf.level_code !== dropLeaf.level_code) return

    const levelCode = dragLeaf.level_code
    const ordered = nodes
      .filter((n) => n.level_code === levelCode)
      .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
    const without = ordered.filter((n) => n.label_id !== dragKey)
    const dropIndex = without.findIndex((n) => n.label_id === dropKey)
    if (dropIndex < 0) return
    const insertAt = info.dropToGap ? dropIndex + 1 : dropIndex
    without.splice(insertAt, 0, dragLeaf)
    const sortMap = new Map(without.map((n, i) => [n.label_id, i]))
    const levelIndex = groups.findIndex((g) => g.level_code === levelCode)
    const band = Math.max(0, levelIndex) * 1000
    onNodesChange(
      nodes.map((n) =>
        n.level_code === levelCode && sortMap.has(n.label_id)
          ? { ...n, sort_order: band + sortMap.get(n.label_id)! }
          : n,
      ),
    )
  }

  const allowDrop = (info: {
    dragNode: { key: Key }
    dropNode: { key: Key }
    dropPosition: number
  }) => {
    const dragKey = String(info.dragNode.key)
    const dropKey = String(info.dropNode.key)
    if (isEnumValueKey(dragKey) || isEnumValueKey(dropKey)) return false

    const dragLevel = parseLevelKey(dragKey)
    const dropLevel = parseLevelKey(dropKey)

    if (dragLevel) {
      // Levels can only be reordered relative to other levels (not nested inside)
      return Boolean(dropLevel) && info.dropPosition !== 0
    }

    if (dropLevel) {
      // Don't drop a leaf onto/beside a level root as a sibling of all levels
      return false
    }

    const dragLeaf = nodes.find((n) => n.label_id === dragKey)
    const dropLeaf = nodes.find((n) => n.label_id === dropKey)
    return Boolean(dragLeaf && dropLeaf && dragLeaf.level_code === dropLeaf.level_code)
  }

  const onTreeSelect = (keys: Key[]) => {
    const key = keys[0] as string | undefined
    setSelectedKey(key)
    if (!key || !canEdit) return
    if (isEnumValueKey(key)) return
    const levelCode = parseLevelKey(key)
    if (levelCode) {
      const level = groups.find((g) => g.level_code === levelCode)
      if (level) openEditLevel(level)
      return
    }
    const leaf = nodes.find((n) => n.label_id === key)
    if (leaf) openEditLeaf(leaf)
  }

  const titleRender = (node: DataNode) => {
    const key = String(node.key)
    if (isEnumValueKey(key)) {
      return (
        <div className="taxonomy-tree-node taxonomy-tree-node--enum">
          <span className="taxonomy-tree-node__title">{node.title as ReactNode}</span>
        </div>
      )
    }
    const levelCode = parseLevelKey(key)
    const leaf = !levelCode ? nodes.find((n) => n.label_id === key) : null

    return (
      <div className="taxonomy-tree-node">
        <span className="taxonomy-tree-node__title">{node.title as ReactNode}</span>
        {canEdit && (
          <Space size={4} className="taxonomy-tree-node__actions" onClick={(e) => e.stopPropagation()}>
            {levelCode ? (
              <>
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  aria-label="新增标签"
                  onClick={() => {
                    const level = groups.find((g) => g.level_code === levelCode)
                    if (level) openCreateLeaf(level)
                  }}
                />
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  aria-label="编辑层级"
                  onClick={() => {
                    const level = groups.find((g) => g.level_code === levelCode)
                    if (level) openEditLevel(level)
                  }}
                />
                <Popconfirm
                  title="删除此层级及其下全部标签？"
                  onConfirm={() => deleteLevel(levelCode)}
                >
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="删除层级" />
                </Popconfirm>
              </>
            ) : leaf ? (
              <>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  aria-label="编辑标签"
                  onClick={() => openEditLeaf(leaf)}
                />
                <Popconfirm title="删除此标签节点？" onConfirm={() => deleteLeaf(leaf.label_id)}>
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="删除标签" />
                </Popconfirm>
              </>
            ) : null}
          </Space>
        )}
      </div>
    )
  }

  if (groups.length === 0) {
    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Typography.Text type="secondary">此版本暂无层级与标签节点</Typography.Text>
        {canEdit && (
          <Button type="dashed" icon={<PlusOutlined />} onClick={openCreateLevel}>
            新增层级
          </Button>
        )}
        <LevelModal
          open={levelModalOpen}
          editing={levelEditing}
          form={levelForm}
          onCancel={() => {
            setLevelModalOpen(false)
            setLevelEditing(null)
            levelForm.resetFields()
          }}
          onOk={() => void saveLevel()}
        />
      </Space>
    )
  }

  return (
    <>
      {canEdit && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Button size="small" icon={<PlusOutlined />} onClick={openCreateLevel}>
            新增层级
          </Button>
          <Button
            size="small"
            icon={<PlusOutlined />}
            disabled={!selectedLevelCode && !selectedLeaf}
            onClick={() => {
              const level =
                (selectedLevelCode &&
                  groups.find((g) => g.level_code === selectedLevelCode)) ||
                (selectedLeaf && {
                  level_code: selectedLeaf.level_code,
                  level_name: selectedLeaf.level_name || selectedLeaf.level_code,
                })
              if (level) openCreateLeaf(level)
            }}
          >
            新增标签
          </Button>
        </Space>
      )}

      {!canEdit && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {groups.length} 个层级，{nodes.length} 个标签节点（只读）
        </Typography.Paragraph>
      )}

      {canEdit && (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          支持层级与标签增删改；可拖动整个层级调整顺序，同级标签也可拖动排序。枚举类型标签可在树中逐层展开查看选项嵌套（编辑仍点铅笔）。保存后生效。
        </Typography.Paragraph>
      )}

      {canEdit && emptyLevels.length > 0 ? (
        <Typography.Paragraph type="danger" style={{ marginBottom: 8, fontSize: 12 }}>
          空层级（无标签）不会写入版本：
          {emptyLevels.map((l) => `${l.level_name}（${l.level_code}）`).join('、')}
          。请添加标签或删除该层级。
        </Typography.Paragraph>
      ) : null}

      <Tree
        treeData={treeData}
        selectedKeys={selectedKey ? [selectedKey] : []}
        expandedKeys={expandedKeys}
        onExpand={(keys) => setExpandedKeys(keys)}
        blockNode
        draggable={
          canEdit
            ? {
                icon: false,
                nodeDraggable: (n) => !isEnumValueKey(String(n.key)),
              }
            : false
        }
        allowDrop={canEdit ? allowDrop : undefined}
        titleRender={titleRender}
        onSelect={onTreeSelect}
        onDrop={onDrop}
      />

      <LevelModal
        open={levelModalOpen}
        editing={levelEditing}
        form={levelForm}
        onCancel={() => {
          setLevelModalOpen(false)
          setLevelEditing(null)
          levelForm.resetFields()
        }}
        onOk={() => void saveLevel()}
      />

      <LeafModal
        open={leafModalOpen}
        editing={leafEditing}
        level={leafLevel}
        form={leafForm}
        onCancel={() => {
          setLeafModalOpen(false)
          setLeafEditing(null)
          setLeafLevel(null)
          leafForm.resetFields()
        }}
        onOk={() => void saveLeaf()}
      />
    </>
  )
}

function LevelModal({
  open,
  editing,
  form,
  onCancel,
  onOk,
}: {
  open: boolean
  editing: TaxonomyLevelMeta | null
  form: ReturnType<typeof Form.useForm<LevelFormValues>>[0]
  onCancel: () => void
  onOk: () => void
}) {
  return (
    <Modal
      title={editing ? `编辑层级 · ${editing.level_code}` : '新增层级'}
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="level_code"
          label="层级编码"
          rules={[{ required: true, message: '请输入层级编码' }]}
        >
          <Input placeholder="L1.1" disabled={Boolean(editing)} />
        </Form.Item>
        <Form.Item
          name="level_name"
          label="层级名称"
          rules={[{ required: true, message: '请输入层级名称' }]}
        >
          <Input placeholder="时间维度" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function LeafModal({
  open,
  editing,
  level,
  form,
  onCancel,
  onOk,
}: {
  open: boolean
  editing: TaxonomyNodeDetail | null
  level: TaxonomyLevelMeta | null
  form: ReturnType<typeof Form.useForm<LeafFormValues>>[0]
  onCancel: () => void
  onOk: () => void
}) {
  return (
    <Modal
      title={
        editing
          ? `编辑标签 · ${editing.label_id}`
          : level
            ? `新增标签 · ${level.level_name}`
            : '新增标签'
      }
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      destroyOnHidden
      width={640}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="label_id"
          label="标签 ID"
          rules={[{ required: true, message: '请输入标签 ID' }]}
        >
          <Input placeholder="L1.1.day_period" disabled={Boolean(editing)} />
        </Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="definition" label="定义">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name="dtype" label="数据类型">
          <Select
            options={[
              { value: 'enum_tree', label: '枚举' },
              { value: 'bool', label: '布尔' },
              { value: 'string', label: '字符串' },
            ]}
            onChange={(next) => {
              if (next === 'enum_tree') {
                const cur = form.getFieldValue('enum_tree_nodes')
                if (!Array.isArray(cur) || cur.length === 0) {
                  form.setFieldValue('enum_tree_nodes', emptyEnumTreeFormNodes())
                }
              }
            }}
          />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, cur) => prev.dtype !== cur.dtype}>
          {({ getFieldValue }) => {
            const dtype = getFieldValue('dtype') as string | undefined
            if (dtype === 'enum_tree' || dtype === 'enum') {
              return <EnumTreeNodesFormRoot />
            }
            if (dtype === 'bool') {
              return (
                <>
                  <Form.Item name="bool_true_label" label="「真」含义">
                    <Input placeholder="例如：是 / 开启" />
                  </Form.Item>
                  <Form.Item name="bool_false_label" label="「假」含义">
                    <Input placeholder="例如：否 / 关闭" />
                  </Form.Item>
                </>
              )
            }
            if (dtype === 'string') {
              return (
                <Form.Item name="string_example" label="示例值">
                  <Input placeholder="用于自动生成 string schema" />
                </Form.Item>
              )
            }
            return null
          }}
        </Form.Item>
        <Form.Item name="is_active" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}
