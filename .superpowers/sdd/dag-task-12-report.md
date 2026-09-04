# Task 12 report — Playwright 收口 + 验收文档

Date: 2026-09-03  
Repo: `D:\cursor_project\rosbag_to_labels_pipline`  
Commits: none  
DataWorks: unchanged  
`audio_nvh-v2`: not published

## Code change

`hmi/frontend/e2e/platform-dtype-editor.spec.ts`

- After successful draft save + reopen: click `palette-op-if`; assert `/dag-node-.*if/` and `dag-cloud-lossy` text `图含 if 或打标后节点：上云不会执行这些分支。`; **do not save**.
- Kept: `dag-canvas`, `dag-node-label`, no `dag-remove-label`, `overview-locked-labels_tree`, `overview-remove-labels_tree` count 0, `dag-cloud-hint` first sentence, draft save.
- ID entry: `click` + `Control+A` + `keyboard.insertText` (Ant Form.Item ignores bare `fill`; `pressSequentially` had leading-`e` flake).

## Commands and counts

Working directory `hmi/backend` unless noted.

| # | Command | Result |
|---|---------|--------|
| 1 | `py -3 scripts/test_platform_recipe_graph.py -v` | **Ran 24 tests in 0.016s OK** (exit 0) |
| 2 | `py -3 scripts/test_platform_graph_runtime.py -v` | **Ran 8 tests in 0.013s OK** (exit 0). Includes `test_assert_blocks_asr_if` → RuntimeError `本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支` |
| 3 | `py -3 scripts/test_platform_datatype_editor.py -v` | **Ran 26 tests in 5.565s OK** (exit 0) |
| 4 | `py -3 scripts/test_platform_datatype_kernel.py -v` | **Ran 19 tests in 4.830s OK** (exit 0) |

Working directory `hmi/frontend`:

| # | Command | Result |
|---|---------|--------|
| 5 | `cmd /c "npx.cmd tsc -b"` | **OK** (exit 0, empty stdout) |
| 6a | `cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"` | **FAIL** 1/3 — `fill()` on `dtype-id` did not stick (Ant Form). STFT + oms_cabin passed. |
| 6b | same after insertText fix | **3 passed (13.3s)** (exit 0) |

A totals: 24 + 8 + 26 + 19 = **77** unit tests + tsc.  
A-E2E: **3/3** Playwright.

## Docs written

- `project-management/acceptance/UI-DTYPE-DAG-CANVAS.md` (A / A-E2E / H 节写「本工单无 H」)
- Progress 四件套: CURRENT.md, tracking.csv (UTF-8 BOM preserved), progress-board.md, changelog-progress.md
- SDD ledger: `.superpowers/sdd/progress.md` Task 12 complete
- Recommended next: **UI-NVH-REVIEW-SAVE**

## Guard (recorded in acceptance)

ASR/标签 if 本地仍 RuntimeError「本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支」，符合计划 Task 11 护栏。

## Concerns

- First Playwright run failed on `fill`; final green run is 6b only.
- Incomplete if-graph is still not saved in e2e (by design); no A-E2E that PUT a valid then/else if-graph.
