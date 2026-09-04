# Task 8 Report · 切片 B Playwright + 收工文档

**工单:** UI-DTYPE-SOURCE-NODES  
**分支:** feat/platform-datatype-kernel（工作树未提交）  
**日期:** 2026-09-02  
**Status:** DONE

## Summary

切片 B Playwright 全绿：**7 passed (48.2s)** = editor **3/3** + lake **4/4**。`platform-lake.spec.ts` 已覆盖 wav→`audio_array_spec`→`lake-run-slot-audio_primary` 预检，以及 `ivi_ui_stub` 隐藏 `.txt`。进度四件套 + acceptance 已刷新本跑证据；推荐下一工单 **UI-NVH-REVIEW-SAVE**。无 git commit。

## Spec / lake coverage

| Case | Result |
|------|--------|
| 入湖 wav → `/pipeline?tab=run` → `audio_array_spec` → `lake-run-slot-audio_primary` 勾选 → 预检通过 | ok |
| `ivi_ui_stub`：`.txt` 不出现在 `lake-run-slot-ui_media` | ok |
| 源湖列表持久化 / OSS 浏览 tab | ok |
| editor：数据源卡 / STFT 绑定 / oms_cabin | ok |

Slot id `audio_primary` / `ui_media` 与 `seed_recipes()` 一致；spec 未改猜错 id。

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Playwright | `cd hmi/frontend && cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts e2e/platform-lake.spec.ts"` | **7 passed (48.2s)** |
| Backend | `GET http://127.0.0.1:8000/api/health` | `data_source=local` |

明细：

```
ok 1 … pipeline component cards (29.0s)
ok 2 … STFT cannot bind to a video-only slot (1.3s)
ok 3 … admin can open edit page for oms_cabin (1.9s)
ok 4 … lake page lists persisted sources (1.5s)
ok 5 … lake page hosts OSS browser tab (2.0s)
ok 6 … lake-run audio_array_spec preflight (3.1s)
ok 7 … ivi_ui_stub filters text source (2.8s)
```

## Docs updated

| File | Change |
|------|--------|
| `project-management/CURRENT.md` | Task 8 收工；下一 **UI-NVH-REVIEW-SAVE** |
| `project-management/tracking.csv` | UTF-8 BOM 保留；备注 Task8 e2e 7/7 |
| `project-management/progress-board.md` | Done 行注明 Task 8 e2e 7/7 |
| `project-management/changelog-progress.md` | 追加 Task 8 Playwright 条目 |
| `project-management/acceptance/UI-DTYPE-SOURCE-NODES.md` | A-E2E 执行记录刷新为本跑 7/7 · 48.2s |

## Code changes this task

None required — `platform-lake.spec.ts` / editor spec 已满足 brief；仅文档与验收记录。

## Self-review

- No DataWorks changes
- Did not publish `audio_nvh-v2`
- No git commit (user forbade)
- tracking.csv BOM verified after write

## Commits

None.

## Concerns

None.
