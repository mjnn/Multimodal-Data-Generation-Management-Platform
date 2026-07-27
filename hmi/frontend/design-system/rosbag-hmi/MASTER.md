# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** 多模数据管理平台  
**Generated:** 2026-07-21 (ui-ux-pro-max + Linear visual merge)  
**Category:** Developer Tools / Data Pipeline HMI  
**Design Dials:** Variance 4/10 | Motion 4/10 | Density 9/10 (Dense Dashboard)

---

## Visual Foundation (Linear-inspired Dark)

This project uses **Linear** dark surfaces as the primary visual language, merged with **ui-ux-pro-max** Data-Dense Dashboard patterns and **ClickHouse-style** KPI stat accents.

| Role | Hex | CSS Variable | Usage |
|------|-----|--------------|-------|
| Canvas | `#010102` | `--color-canvas` | App shell background |
| Surface 1 | `#0f1011` | `--color-surface-1` | Cards, panels |
| Surface 2 | `#141516` | `--color-surface-2` | Hover, nested chrome |
| Hairline | `#23252a` | `--color-hairline` | Borders |
| Primary | `#5e6ad2` | `--color-primary` | CTAs, links, focus |
| Ink | `#f7f8f8` | `--color-ink` | Primary text |
| Ink Subtle | `#8a8f98` | `--color-ink-subtle` | Secondary text |
| Stat Accent | `#faff69` | `--color-accent-stat` | KPI numbers (Overview) |
| Success | `#27a644` | `--color-success` | Completed states |
| Warning | `#d97706` | `--color-warning` | Pending states |
| Error | `#ef4444` | `--color-error` | Failed states |

## Typography

- **UI:** Fira Sans (Google Fonts)
- **Code / IDs:** Fira Code
- **Density:** 14px body, 12px captions, tight table row padding

## Layout Pattern

- **Shell:** 240px collapsible dark sidebar + 56px header + scrollable content
- **Page:** `PageStack` → `PageHeader` → stat grid / `ContentCard` tables
- **Clip Explorer:** IDE-style toolbar + timeline panel + 2×2 camera grid + detail sidebar

## Navigation Hierarchy (ui-ux-pro-max)

| Level | Pattern | Implementation |
|-------|---------|------------------|
| L1 一级 | 侧栏分组导航 | `AppLayout` — 数据浏览 / 管线工作 / 系统管理 |
| L2 二级 | 页面 + 面包屑 | `PageHeader` + `Breadcrumb` |
| L3 三级 | 列表筛选 | `FilterBar`（Segmented），**禁止**用 Tabs 做筛选 |

See `design-system/rosbag-hmi/pages/list-pages.md` for page-level overrides.

## Component Library

| Component | Path | Purpose |
|-----------|------|---------|
| `PageHeader` | `src/components/ui/PageHeader.tsx` | Title + description + actions |
| `StatCard` | `src/components/ui/StatCard.tsx` | KPI metrics row |
| `ContentCard` | `src/components/ui/ContentCard.tsx` | Bordered content panel |
| `PageStack` | `src/components/ui/PageStack.tsx` | Vertical page rhythm |

## Ant Design Theme

Configured in `src/theme/linearTheme.ts` — dark algorithm with Linear token mapping.

## Anti-Patterns (Do NOT)

- ❌ Light/white content area breaking dark shell unity
- ❌ Emojis as icons
- ❌ Missing `cursor-pointer` on clickable rows/cards
- ❌ Instant state changes (always 150–300ms transitions)
- ❌ Invisible focus rings
- ❌ Decorative-only animation on data tables

## Pre-Delivery Checklist

- [ ] No emojis as icons
- [ ] All clickable elements have pointer cursor + keyboard support
- [ ] Hover/focus transitions 150–300ms
- [ ] Dark mode text contrast ≥ 4.5:1 on primary content
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive at 375 / 768 / 1024 / 1440px
- [ ] E2E testids and menu labels preserved
