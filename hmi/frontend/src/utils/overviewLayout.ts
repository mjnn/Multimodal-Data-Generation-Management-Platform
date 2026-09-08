import type {
  DataTypeRecipe,
  PipelineBinding,
  PlatformCatalog,
  PlatformViewTemplate,
  RecipeOverview,
  ViewCard,
  ViewWidget,
} from '../api/types'

const FALLBACK_PRESETS: Record<string, { list: string[]; detail: string[] }> = {
  custom: { list: [], detail: [] },
}

export function widgetCatalog(catalog: PlatformCatalog | null | undefined): ViewWidget[] {
  return catalog?.view_widgets || []
}

export function widgetById(catalog: PlatformCatalog | null | undefined, id: string): ViewWidget | undefined {
  return widgetCatalog(catalog).find((w) => w.id === id)
}

function defaultCard(widgetId: string, prefix: string): ViewCard {
  return { key: `${prefix}-${widgetId}`, widget_id: widgetId, bindings: {} }
}

export function emptyOverview(): RecipeOverview {
  return { preset: 'custom', list: [], detail: [] }
}

export function cardsFromPreset(
  presetId: string,
  views?: PlatformViewTemplate[] | null,
): RecipeOverview {
  const view = views?.find((v) => v.id === presetId)
  const fallback = FALLBACK_PRESETS[presetId] || { list: [], detail: [] }
  const list = view?.list?.length ? view.list : fallback.list
  const detail = view?.detail ? view.detail : fallback.detail
  return {
    preset: presetId || 'custom',
    list: list.map((id) => defaultCard(id, 'list')),
    detail: detail.map((id) => defaultCard(id, 'detail')),
  }
}

export function hydrateOverview(
  recipe: Pick<DataTypeRecipe, 'overview_view' | 'overview'> | null | undefined,
  _views?: PlatformViewTemplate[] | null,
): RecipeOverview {
  if (!recipe) {
    return emptyOverview()
  }
  const preset = recipe.overview_view || 'custom'
  const raw = recipe?.overview
  if (raw && (Array.isArray(raw.list) || Array.isArray(raw.detail))) {
    return {
      preset: raw.preset || preset,
      list: Array.isArray(raw.list) ? raw.list.map(cloneCard) : [],
      detail: Array.isArray(raw.detail) ? raw.detail.map(cloneCard) : [],
    }
  }
  if (raw && Array.isArray(raw.list) === false && Array.isArray(raw.detail) === false) {
    return { preset: raw.preset || preset, list: [], detail: [] }
  }
  return { preset, list: [], detail: [] }
}

function cloneCard(card: ViewCard): ViewCard {
  return {
    key: card.key,
    widget_id: card.widget_id,
    bindings: card.bindings ? { ...card.bindings } : {},
    ...(card.sync_group ? { sync_group: card.sync_group } : {}),
  }
}

export function overviewWidgetIds(overview: RecipeOverview | null | undefined, surface: 'list' | 'detail'): string[] {
  return (overview?.[surface] || []).map((c) => c.widget_id).filter(Boolean)
}

export function hasOverviewWidget(
  recipe: Pick<DataTypeRecipe, 'overview_view' | 'overview'> | null | undefined,
  widgetId: string,
  surface?: 'list' | 'detail',
): boolean {
  const ov = hydrateOverview(recipe)
  if (surface) return overviewWidgetIds(ov, surface).includes(widgetId)
  return overviewWidgetIds(ov, 'list').includes(widgetId) || overviewWidgetIds(ov, 'detail').includes(widgetId)
}

export function resolveListCards(recipe: DataTypeRecipe | null | undefined): ViewCard[] {
  const ov = hydrateOverview(recipe)
  const list = [...ov.list]
  if (!list.some((c) => c.widget_id === 'clip_table')) {
    list.push(defaultCard('clip_table', 'list'))
  }
  return list
}

export function resolveDetailCards(recipe: DataTypeRecipe | null | undefined): ViewCard[] {
  return hydrateOverview(recipe).detail
}

export function portIdToChannelIndex(portId: string | undefined | null): number | null {
  const m = /^ch(\d+)$/.exec(String(portId || '').trim())
  if (!m) return null
  const n = Number(m[1])
  if (!Number.isFinite(n) || n < 1) return null
  return n - 1
}

export function remapOverviewKeys(overview: RecipeOverview, keymap: Map<string, string>): RecipeOverview {
  const remapBinding = (b: PipelineBinding): PipelineBinding => {
    if (b.kind === 'slot' && keymap.has(b.slot_id)) return { ...b, slot_id: keymap.get(b.slot_id)! }
    if (b.kind === 'upstream' && keymap.has(b.step_key)) return { ...b, step_key: keymap.get(b.step_key)! }
    return b
  }
  const remapCard = (card: ViewCard): ViewCard => {
    const bindings = { ...(card.bindings || {}) }
    const next: ViewCard['bindings'] = {}
    for (const [pid, raw] of Object.entries(bindings)) {
      next[pid] = Array.isArray(raw) ? raw.map(remapBinding) : remapBinding(raw)
    }
    return { ...card, bindings: next }
  }
  return { ...overview, list: overview.list.map(remapCard), detail: overview.detail.map(remapCard) }
}

export function overviewCustomized(overview: RecipeOverview, views?: PlatformViewTemplate[] | null): boolean {
  const preset = overview.preset || 'custom'
  const base = cardsFromPreset(preset, views)
  const ids = (cards: ViewCard[]) => cards.map((c) => c.widget_id).join('|')
  return ids(overview.list) !== ids(base.list) || ids(overview.detail) !== ids(base.detail)
}
