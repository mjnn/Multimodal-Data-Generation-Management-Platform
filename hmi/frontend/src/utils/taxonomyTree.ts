import type { DataNode } from 'antd/es/tree'
import type { TaxonomyNodeDetail, TaxonomyNodeInput } from '../api/types'
import { taxonomySchemaDetailNodes } from './taxonomySchemaView'

export type TaxonomyLevelMeta = {
  level_code: string
  level_name: string
}

export type TaxonomyLevelGroup = TaxonomyLevelMeta & {
  nodes: TaxonomyNodeDetail[]
}

export function groupTaxonomyLevels(
  nodes: TaxonomyNodeDetail[],
  emptyLevels: TaxonomyLevelMeta[] = [],
): TaxonomyLevelGroup[] {
  const map = new Map<string, TaxonomyLevelGroup>()
  for (const level of emptyLevels) {
    map.set(level.level_code, { ...level, nodes: [] })
  }
  for (const node of nodes) {
    if (node.is_active === false) continue
    const code = node.level_code || 'other'
    if (!map.has(code)) {
      map.set(code, {
        level_code: code,
        level_name: node.level_name || code,
        nodes: [],
      })
    }
    map.get(code)!.nodes.push(node)
  }
  for (const group of map.values()) {
    group.nodes.sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
  }
  return [...map.values()].sort((a, b) => a.level_code.localeCompare(b.level_code))
}

export function toEditorTreeData(
  groups: TaxonomyLevelGroup[],
  canEdit: boolean,
): DataNode[] {
  return groups.map((group) => ({
    key: `level:${group.level_code}`,
    title: `${group.level_name} (${group.level_code})`,
    selectable: canEdit,
    children: group.nodes
      .filter((node) => node.is_active !== false)
      .map((node) => {
        const base: DataNode = {
          key: node.label_id,
          title: `${node.name} (${node.label_id})`,
        }
        if (canEdit) {
          return { ...base, isLeaf: true }
        }
        return {
          ...base,
          isLeaf: false,
          children: taxonomySchemaDetailNodes(node),
        }
      }),
  }))
}

export function nodesToPayload(nodes: TaxonomyNodeDetail[]): TaxonomyNodeInput[] {
  return nodes
    .filter((n) => n.is_active !== false)
    .map((n) => ({
    label_id: n.label_id,
    level_code: n.level_code,
    level_name: n.level_name,
    name: n.name,
    definition: n.definition,
    dtype: n.dtype,
    value_schema: n.value_schema,
    sort_order: n.sort_order,
    is_active: n.is_active,
  }))
}

export function parseLevelKey(key: string): string | null {
  return key.startsWith('level:') ? key.slice('level:'.length) : null
}

export function renameLevel(
  nodes: TaxonomyNodeDetail[],
  emptyLevels: TaxonomyLevelMeta[],
  oldCode: string,
  next: TaxonomyLevelMeta,
): { nodes: TaxonomyNodeDetail[]; emptyLevels: TaxonomyLevelMeta[] } {
  const updatedNodes = nodes.map((n) =>
    n.level_code === oldCode
      ? { ...n, level_code: next.level_code, level_name: next.level_name }
      : n,
  )
  const updatedEmpty = emptyLevels.map((l) =>
    l.level_code === oldCode ? next : l,
  )
  return { nodes: updatedNodes, emptyLevels: updatedEmpty }
}

export function removeLevel(
  nodes: TaxonomyNodeDetail[],
  emptyLevels: TaxonomyLevelMeta[],
  levelCode: string,
): { nodes: TaxonomyNodeDetail[]; emptyLevels: TaxonomyLevelMeta[] } {
  return {
    nodes: nodes.filter((n) => n.level_code !== levelCode),
    emptyLevels: emptyLevels.filter((l) => l.level_code !== levelCode),
  }
}

export function levelCodes(
  nodes: TaxonomyNodeDetail[],
  emptyLevels: TaxonomyLevelMeta[],
): Set<string> {
  const codes = new Set<string>()
  for (const n of nodes) codes.add(n.level_code)
  for (const l of emptyLevels) codes.add(l.level_code)
  return codes
}
