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
  cabin_timeline: {
    list: ['clip_metrics', 'label_search', 'clip_table'],
    detail: ['cabin_multicam', 'asr_panel'],
  },
  audio_nvh_timeline: {
    list: ['clip_metrics', 'nvh_spl_column', 'clip_table'],
    detail: ['nvh_spectrum'],
  },
  audio_spec_asr: {
    list: ['clip_metrics', 'clip_table'],
    detail: ['nvh_spectrum', 'asr_panel'],
  },
  frame_gallery_bbox: {
    list: ['clip_metrics', 'clip_table'],
    detail: ['frame_gallery_bbox'],
  },
  json_tree: {
    list: ['clip_metrics', 'clip_table'],
    detail: ['json_tree'],
  },
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

/** Mirror backend `hydrate_overview`: detail always has a locked labels_tree card. */
export function ensureLabelsTree(detail: ViewCard[]): ViewCard[] {
  if (detail.some((c) => c.widget_id === 'labels_tree')) return detail
  return [
    {
      key: 'locked-labels_tree',
      widget_id: 'labels_tree',
      bindings: { in: { kind: 'upstream', step_key: 'stage-label', port_id: 'labels_tree' } },
    },
    ...detail,
  ]
}

export function cardsFromPreset(
  presetId: string,
  views?: PlatformViewTemplate[] | null,
): RecipeOverview {
  const view = views?.find((v) => v.id === presetId)
  const fallback = FALLBACK_PRESETS[presetId] || { list: ['clip_table'], detail: [] }
  const list = view?.list?.length ? view.list : fallback.list
  const detail = view?.detail ? view.detail : fallback.detail
  return {
    preset: presetId,
    list: list.map((id) => defaultCard(id, 'list')),
    detail: ensureLabelsTree(detail.map((id) => defaultCard(id, 'detail'))),
  }
}

export function hydrateOverview(
  recipe: Pick<DataTypeRecipe, 'overview_view' | 'overview'> | null | undefined,
  views?: PlatformViewTemplate[] | null,
): RecipeOverview {
  if (!recipe) {
    return { preset: '', list: [], detail: [] }
  }
  const preset = recipe.overview_view || 'cabin_timeline'
  const raw = recipe?.overview
  if (raw && (Array.isArray(raw.list) || Array.isArray(raw.detail))) {
    return {
      preset: raw.preset || preset,
      list: Array.isArray(raw.list) ? raw.list.map(cloneCard) : [],
      detail: ensureLabelsTree(Array.isArray(raw.detail) ? raw.detail.map(cloneCard) : []),
    }
  }
  return cardsFromPreset(preset, views)
}

function cloneCard(card: ViewCard): ViewCard {
  return {
    key: card.key,
    widget_id: card.widget_id,
    bindings: card.bindings ? { ...card.bindings } : {},
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
  const preset = overview.preset || ''
  const base = cardsFromPreset(preset, views)
  const ids = (cards: ViewCard[]) => cards.map((c) => c.widget_id).join('|')
  return ids(overview.list) !== ids(base.list) || ids(overview.detail) !== ids(base.detail)
}
