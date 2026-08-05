import type { DataNode } from 'antd/es/tree'
import type { TaxonomyNodeDetail, TaxonomyNodeInput } from '../api/types'
import { taxonomySchemaDetailNodes } from './taxonomySchemaView'

export type TaxonomyLevelMeta = {
  level_code: string
  level_name: string
  /** Display order among levels (lower first). Persisted via node sort_order bands when saving. */
  sort_order?: number
}

export type TaxonomyLevelGroup = TaxonomyLevelMeta & {
  nodes: TaxonomyNodeDetail[]
}

const LEVEL_SORT_BAND = 1000

function levelSortKey(group: TaxonomyLevelGroup): number {
  if (typeof group.sort_order === 'number' && Number.isFinite(group.sort_order)) {
    return group.sort_order
  }
  if (group.nodes.length > 0) {
    return Math.min(...group.nodes.map((n) => n.sort_order))
  }
  return Number.MAX_SAFE_INTEGER
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
  return [...map.values()].sort((a, b) => {
    const ka = levelSortKey(a)
    const kb = levelSortKey(b)
    if (ka !== kb) return ka - kb
    return a.level_code.localeCompare(b.level_code)
  })
}

/** Reorder levels and rewrite node/emptyLevel sort_order so the order persists after save. */
export function reorderTaxonomyLevels(
  nodes: TaxonomyNodeDetail[],
  emptyLevels: TaxonomyLevelMeta[],
  orderedLevelCodes: string[],
): { nodes: TaxonomyNodeDetail[]; emptyLevels: TaxonomyLevelMeta[] } {
  const codeSet = new Set(orderedLevelCodes)
  const groups = groupTaxonomyLevels(nodes, emptyLevels)
  const remaining = groups.map((g) => g.level_code).filter((c) => !codeSet.has(c))
  const finalOrder = [
    ...orderedLevelCodes.filter((c) => groups.some((g) => g.level_code === c)),
    ...remaining,
  ]

  const nextNodes = nodes.map((n) => {
    const levelIndex = finalOrder.indexOf(n.level_code)
    if (levelIndex < 0) return n
    const siblings = nodes
      .filter((x) => x.level_code === n.level_code)
      .sort((a, b) => a.sort_order - b.sort_order || a.label_id.localeCompare(b.label_id))
    const localIndex = siblings.findIndex((x) => x.label_id === n.label_id)
    return {
      ...n,
      sort_order: levelIndex * LEVEL_SORT_BAND + Math.max(0, localIndex),
    }
  })

  const nextEmpty = emptyLevels.map((l) => {
    const levelIndex = finalOrder.indexOf(l.level_code)
    return {
      ...l,
      sort_order: levelIndex >= 0 ? levelIndex * LEVEL_SORT_BAND : l.sort_order,
    }
  })

  return { nodes: nextNodes, emptyLevels: nextEmpty }
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
    l.level_code === oldCode ? { ...next, sort_order: l.sort_order } : l,
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
