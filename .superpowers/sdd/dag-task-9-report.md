# Task 9 report: 橱窗锁死 `labels_tree`

**Status:** PASS  
**Commits:** none

## Changes

- `ensureLabelsTree(detail)` in `overviewLayout.ts` — insert locked card at index 0 (mirrors backend `hydrate_overview`). Called from `cardsFromPreset`, `hydrateOverview`, and `OverviewComposer` (detail `onChange` + mount).
- Composer: `widget_id==='labels_tree'` has no delete (`overview-remove-labels_tree` count 0); wrapper `data-testid="overview-locked-labels_tree"`; palette `overview-add-labels_tree` hidden when one exists.
- Runtime: ClipExplorerPage + ReviewClipMediaPanel render `<pre data-testid="overview-runtime-labels_tree">` from clip/task `labels_json` (empty `{}` if missing). Existing `overview-runtime-json_tree` and NVH `ClipLabelTreeView` unchanged.

## tsc

```
cwd: hmi/frontend
cmd: cmd /c "npx.cmd tsc -b"
exit: 0
output: (empty)
```

**PASS**

## Playwright

Command: `cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

First run failed 1/3 on pre-existing `dtype-id` flake (`pressSequentially` dropped leading `e`: expected `e2e_orch_…`, got `2e_orch_…`). Locked-card assertions had already passed. Retry:

```
Running 3 tests using 1 worker

  ok 1 [chromium] › e2e\platform-dtype-editor.spec.ts:4:1 › admin can create draft data type with pipeline component cards (3.0s)
  ok 2 [chromium] › e2e\platform-dtype-editor.spec.ts:44:1 › STFT cannot bind to a video-only slot (1.3s)
  ok 3 [chromium] › e2e\platform-dtype-editor.spec.ts:56:1 › admin can open edit page for oms_cabin (1.8s)

  3 passed (13.8s)
```

**3/3 PASS** (create + oms_cabin assert `overview-locked-labels_tree` visible and `overview-remove-labels_tree` count 0).

## Concerns

- Create-page `dtype-id` `pressSequentially` can drop the first character; unrelated to this slice.
- Review runtime uses `clip_card.labels_json` when present, otherwise `{}` (card type does not declare that field).
- `hydrateOverview(null)` still returns empty detail (no recipe); workspace recipes always get `labels_tree`.
