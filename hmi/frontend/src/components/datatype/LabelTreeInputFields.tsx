import { useEffect, useMemo, useState } from 'react'
import { Input, Select, Tree, Typography } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { api } from '../../api'
import type {
  PipelineBinding,
  PipelineStep,
  PlatformOperator,
  RecipeGraphNode,
  TaxonomyNodeDetail,
} from '../../api/types'
import { bindingOptions, decodeBinding, encodeBinding, slotsFromSteps } from '../../utils/recipePipeline'
import { groupTaxonomyLevels, pickTaxonomyVersion, toEditorTreeData } from '../../utils/taxonomyTree'

export type LabelFill = {
  label_id: string
  mode?: 'const' | 'upstream'
  value?: unknown
  bind_step_key?: string
  bind_port_id?: string
}

type Props = {
  node: RecipeGraphNode
  step: PipelineStep
  steps: PipelineStep[]
  operators: PlatformOperator[]
  typeProvides: Record<string, string[]>
  taxonomyId?: string
  onPatch: (patch: Partial<RecipeGraphNode>) => void
}

function fillsOf(node: RecipeGraphNode): LabelFill[] {
  const raw = node.params?.assignments
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item): LabelFill => ({
      label_id: String(item.label_id || '').trim(),
      mode: item.mode === 'upstream' ? 'upstream' : 'const',
      value: item.value,
      bind_step_key: item.bind_step_key != null ? String(item.bind_step_key) : undefined,
      bind_port_id: item.bind_port_id != null ? String(item.bind_port_id) : undefined,
    }))
    .filter((item) => item.label_id)
}

function encodeFillBind(item: LabelFill): string {
  if (!item.bind_step_key) return ''
  return encodeBinding({
    kind: 'upstream',
    step_key: item.bind_step_key,
    port_id: item.bind_port_id || 'out',
  })
}

export function LabelTreeInputFields({
  node,
  step,
  steps,
  operators,
  typeProvides,
  taxonomyId,
  onPatch,
}: Props) {
  const params = node.params || {}
  const fills = fillsOf(node)
  const [nodes, setNodes] = useState<TaxonomyNodeDetail[]>([])
  const labelIdSet = useMemo(
    () => new Set(nodes.filter((n) => n.is_active !== false).map((n) => n.label_id)),
    [nodes],
  )
  const treeData = useMemo((): DataNode[] => {
    const groups = groupTaxonomyLevels(nodes.filter((n) => n.is_active !== false))
    return toEditorTreeData(groups, false)
  }, [nodes])
  const nameById = useMemo(() => {
    const map = new Map<string, string>()
    for (const n of nodes) map.set(n.label_id, n.name)
    return map
  }, [nodes])

  useEffect(() => {
    let cancelled = false
    void api
      .listTaxonomyVersions()
      .then((versions) => {
        const picked = pickTaxonomyVersion(versions, String(taxonomyId || ''))
        if (!picked) {
          if (!cancelled) setNodes([])
          return undefined
        }
        return api.getTaxonomyTree(picked.id)
      })
      .then((tree) => {
        if (!cancelled && tree) setNodes(tree.nodes || [])
      })
      .catch(() => {
        if (!cancelled) setNodes([])
      })
    return () => {
      cancelled = true
    }
  }, [taxonomyId])

  const options = bindingOptions({
    neededTypes: ['json_value', 'structured_json', '.json'],
    slots: slotsFromSteps(steps),
    upstream: steps.filter((s) => s.key !== step.key),
    operators,
    typeProvides,
  })

  const setFills = (next: LabelFill[]) => {
    const bindings: Record<string, PipelineBinding> = { ...(node.bindings || {}) } as Record<
      string,
      PipelineBinding
    >
    for (const key of Object.keys(bindings)) {
      if (key.startsWith('value:')) delete bindings[key]
    }
    for (const item of next) {
      if (item.mode === 'upstream' && item.bind_step_key) {
        bindings[`value:${item.label_id}`] = {
          kind: 'upstream',
          step_key: item.bind_step_key,
          port_id: item.bind_port_id || 'out',
        }
      }
    }
    onPatch({
      params: { ...params, assignments: next },
      bindings,
    })
  }

  return (
    <div className="pipe-step__params" data-testid="pipe-label-tree-input">
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        从标签树选择条目
      </Typography.Text>
      {nodes.length ? (
        <Tree
          checkable
          selectable={false}
          treeData={treeData}
          checkedKeys={fills.map((f) => f.label_id)}
          height={180}
          data-testid="pipe-label-tree-picker"
          style={{
            border: '1px solid var(--ant-color-border-secondary, #f0f0f0)',
            borderRadius: 8,
            padding: 8,
          }}
          onCheck={(keys) => {
            const list = (Array.isArray(keys) ? keys : keys.checked)
              .map(String)
              .filter((k) => labelIdSet.has(k))
            const prev = new Map(fills.map((f) => [f.label_id, f]))
            setFills(
              list.map((lid) => prev.get(lid) || { label_id: lid, mode: 'const', value: '' }),
            )
          }}
        />
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          暂无可用标签树（检查配方绑定的 taxonomy_id）
        </Typography.Text>
      )}
      {fills.map((item, idx) => (
        <div key={item.label_id} className="dag-inspector__fill" data-testid={`pipe-label-fill-${item.label_id}`}>
          <Typography.Text style={{ fontSize: 12 }}>{nameById.get(item.label_id) || item.label_id}</Typography.Text>
          <Select
            size="small"
            style={{ width: '100%' }}
            value={item.mode || 'const'}
            options={[
              { value: 'const', label: '常量' },
              { value: 'upstream', label: '上游节点' },
            ]}
            onChange={(mode: 'const' | 'upstream') => {
              const next = [...fills]
              next[idx] = { ...item, mode }
              setFills(next)
            }}
          />
          {item.mode === 'upstream' ? (
            <Select
              allowClear
              size="small"
              placeholder="绑定 JSON 值提取等上游产出"
              style={{ width: '100%' }}
              value={encodeFillBind(item) || undefined}
              options={options.map((o) => ({ value: o.value, label: o.label }))}
              onChange={(v: string | null) => {
                const decoded = decodeBinding(v || '')
                const next = [...fills]
                next[idx] = {
                  ...item,
                  mode: 'upstream',
                  bind_step_key: decoded?.kind === 'upstream' ? decoded.step_key : undefined,
                  bind_port_id: decoded?.kind === 'upstream' ? decoded.port_id || 'out' : undefined,
                }
                setFills(next)
              }}
            />
          ) : (
            <Input
              size="small"
              placeholder="填写值"
              value={item.value == null ? '' : String(item.value)}
              onChange={(e) => {
                const next = [...fills]
                next[idx] = { ...item, mode: 'const', value: e.target.value }
                setFills(next)
              }}
            />
          )}
        </div>
      ))}
    </div>
  )
}
