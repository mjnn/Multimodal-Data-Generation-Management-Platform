# List & Filter Pages — Navigation Override

> Overrides `MASTER.md` for list-style pages: Overview, Review Queue, Datasets, Label Search.

## Navigation Hierarchy (3 levels)

| Level | Component | Example |
|-------|-----------|---------|
| **L1 Primary** | Sidebar menu groups | 数据浏览 / 管线工作 / 系统管理 |
| **L2 Page** | `PageHeader` + breadcrumb | 校核队列 |
| **L3 Filter** | `FilterBar` (Segmented) inside `ContentCard.toolbar` | 待校核 / 已校核 |

**Never use Ant Design `Tabs` for L3 list filters** — Tabs imply same-hierarchy view switching and conflict with sidebar (ux: avoid-mixed-patterns).

## URL State (required)

All list filters and pagination sync to URL query params via `useListQueryState`:

- Review: `?status=pending_review&page=2`
- Datasets: `?status=building&page=1`
- Overview: `?pipeline=failed`
- Search: `?q=keyword&label=node_id`

Enables back-button state restoration (ux: state-preservation).

## Interaction Patterns

- **Table rows**: entire row clickable → drill-down detail
- **Back navigation**: `BackLink` uses history first, then fallback route
- **Filter counts**: show in FilterBar badges when cheap to fetch
- **Keyboard**: result cards and table rows support Enter/Space activation

## Visual Separation

- Sidebar: full-height, grouped labels uppercase 11px
- FilterBar: lives in `content-card__toolbar` with `surface-2` background
- Primary CTA (创建/新建): only in `PageHeader.extra`, never in filter bar
