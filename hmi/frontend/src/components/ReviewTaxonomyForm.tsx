import { CompressOutlined, ExpandOutlined } from '@ant-design/icons'

import { Alert, Button, Collapse, Form, Input, Select, Space, Switch, Tag, Typography } from 'antd'

import type { FormInstance } from 'antd/es/form'

import { useEffect, useMemo, useState } from 'react'

import type { AiLabelHint, TaxonomyNodeDetail } from '../api/types'

import { AiLabelHintReference } from './AiLabelHintReference'

import { isLowConfidence } from '../utils/reviewConfidence'



type LevelGroup = {

  key: string

  title: string

  nodes: TaxonomyNodeDetail[]

}



function schemaEnumValues(node: TaxonomyNodeDetail): string[] {

  const schema = node.value_schema as { values?: unknown[] } | null

  if (!schema?.values?.length) return []

  return schema.values.map(String)

}



function groupActiveNodes(nodes: TaxonomyNodeDetail[]): LevelGroup[] {

  const groups = new Map<string, LevelGroup>()

  for (const node of nodes) {

    if (node.is_active === false) continue

    const levelCode = node.level_code || 'other'

    if (!groups.has(levelCode)) {

      groups.set(levelCode, {

        key: levelCode,

        title: node.level_name || levelCode,

        nodes: [],

      })

    }

    groups.get(levelCode)!.nodes.push(node)

  }

  for (const group of groups.values()) {

    group.nodes.sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))

  }

  return [...groups.values()].sort((a, b) => a.key.localeCompare(b.key))

}



type LabelFieldProps = {

  node: TaxonomyNodeDetail

  lowConfidence?: boolean

  hint?: AiLabelHint

}



function LabelField({ node, lowConfidence, hint }: LabelFieldProps) {

  const label = (

    <Space size={6} wrap>

      <span>{node.name}</span>

      <Typography.Text type="secondary" className="mono" style={{ fontSize: 11 }}>

        {node.label_id}

      </Typography.Text>

      {lowConfidence ? (

        <Tag color="orange" style={{ margin: 0 }}>

          低置信度

        </Tag>

      ) : null}

    </Space>

  )



  let field = null

  if (node.dtype === 'bool') {

    field = (

      <Form.Item name={node.label_id} label={label} valuePropName="checked">

        <Switch checkedChildren="是" unCheckedChildren="否" />

      </Form.Item>

    )

  } else {

    const enumValues = schemaEnumValues(node)

    field =

      enumValues.length > 0 ? (

        <Form.Item name={node.label_id} label={label}>

          <Select allowClear options={enumValues.map((v) => ({ value: v, label: v }))} />

        </Form.Item>

      ) : (

        <Form.Item name={node.label_id} label={label}>

          <Input />

        </Form.Item>

      )

  }



  return (

    <div

      className={

        lowConfidence ? 'review-label-field review-label-field--disputed' : 'review-label-field'

      }

    >

      {field}

      <AiLabelHintReference confidence={hint?.confidence} evidence={hint?.evidence} />

    </div>

  )

}



type ReviewTaxonomyFormProps = {

  form: FormInstance<Record<string, unknown>>

  nodes: TaxonomyNodeDetail[]

  /** When set, only show these label fields (task-focused review). */

  focusLabelIds?: string[]

  aiLabelHints?: Record<string, AiLabelHint>

}



export function ReviewTaxonomyForm({

  form,

  nodes,

  focusLabelIds,

  aiLabelHints = {},

}: ReviewTaxonomyFormProps) {

  const visibleNodes = useMemo(() => {

    if (!focusLabelIds?.length) return nodes

    const allowed = new Set(focusLabelIds)

    return nodes.filter((node) => allowed.has(node.label_id))

  }, [focusLabelIds, nodes])

  const groups = useMemo(() => groupActiveNodes(visibleNodes), [visibleNodes])

  const groupKeys = useMemo(() => groups.map((g) => g.key), [groups])

  const [activeKeys, setActiveKeys] = useState<string[]>([])



  const labelsWatch = Form.useWatch([], form)



  const lowConfidenceSet = useMemo(() => {

    const values = (labelsWatch ?? {}) as Record<string, unknown>

    const set = new Set<string>()

    for (const node of visibleNodes) {

      const hint = aiLabelHints[node.label_id]

      const value = values[node.label_id] ?? form.getFieldValue(node.label_id)

      if (isLowConfidence(value, hint?.confidence)) {

        set.add(node.label_id)

      }

    }

    return set

  }, [aiLabelHints, form, labelsWatch, visibleNodes])



  useEffect(() => {

    const keysWithLow = groups

      .filter((g) => g.nodes.some((n) => lowConfidenceSet.has(n.label_id)))

      .map((g) => g.key)

    setActiveKeys(keysWithLow.length > 0 ? keysWithLow : groupKeys)

  }, [groupKeys, groups, lowConfidenceSet])



  if (groups.length === 0) {

    return (

      <Typography.Text type="secondary">

        {focusLabelIds?.length

          ? '当前任务标签不在 taxonomy 中，请检查标签树发布状态。'

          : '无可用 taxonomy 节点，请检查标签树发布状态。'}

      </Typography.Text>

    )

  }



  return (

    <Space direction="vertical" size={12} style={{ width: '100%' }}>

      {lowConfidenceSet.size > 0 ? (

        <Alert

          type="warning"

          showIcon

          message={`${lowConfidenceSet.size} 个标签置信度偏低或缺失，建议优先核对`}

          description="橙色高亮字段为 AI 置信度低于阈值或未提供置信度的标签；请结合证据与音视频判断。"

        />

      ) : null}



      <Space wrap size={8}>

        <Button

          size="small"

          icon={<ExpandOutlined />}

          onClick={() => setActiveKeys(groupKeys)}

          disabled={activeKeys.length === groupKeys.length}

        >

          全部展开

        </Button>

        <Button

          size="small"

          icon={<CompressOutlined />}

          onClick={() => setActiveKeys([])}

          disabled={activeKeys.length === 0}

        >

          全部折叠

        </Button>

      </Space>



      <Form form={form} layout="vertical" className="review-taxonomy-form">

        <Collapse

          activeKey={activeKeys}

          onChange={(keys) => setActiveKeys(Array.isArray(keys) ? keys : [keys])}

          className="review-taxonomy-form__collapse"

          items={groups.map((group) => {

            const lowCount = group.nodes.filter((n) => lowConfidenceSet.has(n.label_id)).length

            return {

              key: group.key,

              label: (

                <Space size={8}>

                  <span>{group.title}</span>

                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>

                    {group.key} · {group.nodes.length} 项

                  </Typography.Text>

                  {lowCount > 0 ? (

                    <Tag color="orange" style={{ margin: 0 }}>

                      {lowCount} 项低置信度

                    </Tag>

                  ) : null}

                </Space>

              ),

              children: group.nodes.map((node) => (

                <LabelField

                  key={node.label_id}

                  node={node}

                  lowConfidence={lowConfidenceSet.has(node.label_id)}

                  hint={aiLabelHints[node.label_id]}

                />

              )),

            }

          })}

        />

      </Form>

    </Space>

  )

}

