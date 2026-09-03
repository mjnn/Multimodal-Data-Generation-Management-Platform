# DataType 总览组件拼版 Implementation Plan

> **For agentic workers:** Execute task-by-task. **不要 git commit**（用户未要求）。Windows 下禁止直接跑 `npm`/`npx`，用 `npm.cmd` / `npx.cmd`。

**Goal:** 配方用两套有序视图卡驱动列表页和 Clip 详情；旧 `overview_view` 变成预设一键填入。

**Architecture:** `views.py` 注册 widget + 预设布局；`validate_recipe` 规范化 `recipe.overview`；编辑器两个拼版区；运行时 Overview / Explorer / 校核只认卡列表，不再按 `dataTypeId` 硬切。

**Tech Stack:** FastAPI + existing recipe store; React/Ant Design; Playwright.

**Spec:** `docs/superpowers/specs/2026-09-02-overview-compose-design.md`

## Global Constraints

- 不 publish `audio_nvh-v2`
- 不改 DataWorks / worker 阶段顺序
- 不做自由画布；详情上下叠卡
- 运行时绑定为空仍走现有 clip/run API
- `list` 无 `clip_table` 时运行时补一张
- `detail` 为空时回退今日硬切（NVH bootstrap → 频谱，否则舱内时间轴）
- 不提交 git，除非用户明确要求

---

## File map

| File | Responsibility |
|------|----------------|
| `hmi/backend/hmi/platform/views.py` | widget 目录、预设卡、hydrate |
| `hmi/backend/hmi/platform/recipe.py` | `overview` 校验并写回 |
| `hmi/backend/hmi/platform/router.py` | catalog 暴露 widgets |
| `hmi/backend/scripts/test_platform_datatype_kernel.py` | hydrate / 拒存 |
| `hmi/frontend/src/api/types.ts` | ViewCard / RecipeOverview |
| `hmi/frontend/src/utils/overviewLayout.ts` | 预设填入、解析 list/detail |
| `hmi/frontend/src/components/datatype/OverviewComposer.tsx` | 两套拼版 UI |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | 保存 overview |
| `hmi/frontend/src/context/DataTypeWorkspaceContext.tsx` | 带 recipe |
| `hmi/frontend/src/pages/OverviewPage.tsx` | 按 list 卡渲染 |
| `hmi/frontend/src/components/ClipMediaPanel.tsx` | 按 detail 卡叠媒体 |
| `hmi/frontend/src/pages/ClipExplorerPage.tsx` | 复用 detail |
| `hmi/frontend/src/components/ReviewClipMediaPanel.tsx` | 复用 detail |
| `hmi/frontend/e2e/platform-dtype-editor.spec.ts` | 拼版区 + 切预设 |

---

## Task 1: Widget catalog + recipe.overview

- [ ] `VIEW_WIDGETS`：clip_metrics / label_search / clip_table / nvh_spl_column / cabin_multicam / nvh_spectrum / asr_panel / frame_gallery_bbox / json_tree
- [ ] `PRESET_LAYOUTS` 按 spec §4.1
- [ ] `cards_from_preset(preset_id)`、`hydrate_overview(recipe)`
- [ ] `validate_recipe` 始终写出 `overview.{preset,list,detail}`
- [ ] 未知 widget / surface 错位拒存；绑定只校验形状
- [ ] 测试：种子带卡；缺 overview 补全；未知 widget 失败
- [ ] `GET /operators` 加 `view_widgets`

## Task 2: Editor two lists

- [ ] 类型 + `overviewLayout.ts`
- [ ] `OverviewComposer`：预设 Select + 列表/详情拼版（折叠、拖动、绑定）
- [ ] `buildRecipe` 写入 `overview`；新建默认 cabin 预设卡
- [ ] Playwright：拼版区可见；oms_cabin 详情有舱内卡；切 NVH 预设出现声压列卡

## Task 3: Runtime

- [ ] Context 加载 recipe（AppLayout 级，Explorer/校核也能读 remembered DataType）
- [ ] OverviewPage 用 list 卡，去掉 `dataTypeId === 'audio_array_spec'`
- [ ] ClipMediaPanel 按 detail widget 叠；空则 bootstrap 兜底
- [ ] Explorer / Review 跟 detail
- [ ] 横幅显示预设标题

## Task 4: Acceptance + handoff

- [ ] `acceptance/UI-DTYPE-OVERVIEW-COMPOSE.md`
- [ ] CURRENT / tracking.csv / progress-board / changelog
- [ ] 下一工单仍为 UI-NVH-REVIEW-SAVE
