# Task 7 Report · 开跑 UI 分块勾选

**工单:** UI-DTYPE-SOURCE-NODES  
**分支:** feat/platform-datatype-kernel（工作树未提交）  
**日期:** 2026-09-02  
**Status:** DONE

## Summary

开跑 UI 分块勾选已在未提交工作树落地（Tasks 1–6 上下文）。对照 brief 核验：`LakeRunBindPanel` 按 `recipe.slots` 分块、kind 过滤、`assignments` 预检/开跑；`api/index.ts` + `types.ts` 已支持可选 `assignments`。无实现缺口，未改代码。`tsc -b` 通过。无 commit。

## Brief vs working tree

| Brief item | Status | Location |
|------------|--------|----------|
| 每 slot 一块 `data-testid="lake-run-slot-{id}"` | Present | `LakeRunBindPanel.tsx` |
| 标题 `slot.title \|\| slot.id` | Present | `slotTitle()` |
| 副文案 kinds × cardinality | Present | `{kinds} · {min}–{max} 个` |
| 块内表仅 kind 合格源 | Present | `sourcesForSlot()` |
| 勾选 → `Record<slotId, sourceId[]>` | Present | `selectedBySlot` state |
| 预检 / 开跑 POST `assignments` | Present | `runPreflight` / `createRun` |
| 去掉整表自动分槽主路径 | Present | 无 global auto-split；仅分块勾选 |
| 保留 `lake-run-sources-table` wrapper | Present | 外层 `data-testid`（e2e 仍用） |
| `preflightPlatformRun` / `createPlatformRun` `assignments?` | Present | `api/index.ts` + `SlotAssignment` in `types.ts` |

## Behavior (as implemented)

1. 选 published DataType → 按 slots 渲染分块表；未选类型不展示可勾选主表。
2. 每块独立 checkbox；同一 `source_id` 不可跨槽重复选用（`takenByOther`）。
3. 客户端基数校验（`slotError` / `blockErrors`）后，预检与创建均 POST `SlotAssignment[]`。
4. e2e 已覆盖 `lake-run-slot-audio_primary` / `lake-run-slot-ui_media`（`platform-lake.spec.ts`）。

## Verification

| Check | Command | Result |
|-------|---------|--------|
| TypeScript | `cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"` | **exit 0**（约 5.2s，无输出） |

## Gaps filled this task

None — UI/API 已与 brief 对齐；仅核验 + 写报告。

## Self-review

- No DataWorks changes
- Did not publish `audio_nvh-v2`
- Did not revert Tasks 1–6 LakeRunBind / assignments work
- No git commit (user forbade)

## Commits

None.

## Concerns

None material. Optional note: `lake-run-sources-table` 仍包住所有 slot 块（非单一 Table），与 e2e 约定一致。
