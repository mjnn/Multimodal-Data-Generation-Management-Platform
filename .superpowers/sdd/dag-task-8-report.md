# Task 8 Report: 检查器条件 UI + 上云黄警告

**Status:** PASS  
**Commits:** none

## What changed

| File | Change |
|------|--------|
| `hmi/frontend/src/components/datatype/DagNodeInspector.tsx` | **Created** — wrapper `dag-inspector`; if Form.List predicates; op bind Select `pipe-bind-{op_id}-{port.id}`; label `pipe-label-model`; source kinds/required |
| `hmi/frontend/src/components/datatype/DagNodeInspector.css` | Inspector sidebar + `dag-editor-split` |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | Always `dag-cloud-hint`; `dag-cloud-lossy` when `graphIsLossy`; wire inspector; clone/`?from=` keeps graph topology |
| `hmi/frontend/src/components/datatype/PipelineDagCanvas.tsx` | `onSelect` / `selectedKey`; if node default `condition: { all: [] }` |
| `hmi/frontend/src/utils/recipeGraph.ts` | `graphToSteps` copies bindings; `remapGraphKeys`; `attachStepBindings` |
| `hmi/frontend/src/api/types.ts` | `RecipeGraphNode.bindings?` |
| `hmi/frontend/e2e/platform-dtype-editor.spec.ts` | First test asserts `dag-cloud-hint`; STFT clicks node → inspector bind |

## Behavior

- **Hint:** always `data-testid="dag-cloud-hint"` message `本地按图执行；上云只跑公共前缀。`
- **Warning:** `data-testid="dag-cloud-lossy"` message `图含 if 或打标后节点：上云不会执行这些分支。` when graph has if/review/export. Does **not** block draft or published save.
- **Inspector:** canvas click sets `selectedKey`. If node: Form.List of `{ field, op, value? }` on `node.condition.all`. Field AutoComplete presets + `labels.*`. Value hidden for `exists` / `not_exists`.
- **Clone:** if `src.graph?.nodes` exists, `remapGraphKeys` keeps DAG; else `hydrateGraphFromSteps`.

## tsc

```text
cwd: hmi/frontend
cmd: cmd /c "npx.cmd tsc -b"
exit: 0
output: (empty — success)
```

## Playwright

```text
cwd: hmi/frontend
cmd: cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
exit: 0 (retry)
output:
Running 3 tests using 1 worker
  ok 1 [chromium] › e2e\platform-dtype-editor.spec.ts:4:1 › admin can create draft data type with pipeline component cards (2.5s)
  ok 2 [chromium] › e2e\platform-dtype-editor.spec.ts:42:1 › STFT cannot bind to a video-only slot (1.5s)
  ok 3 [chromium] › e2e\platform-dtype-editor.spec.ts:54:1 › admin can open edit page for oms_cabin (1.7s)
  3 passed (13.3s)
```

First run failed test 1 on pre-existing `pressSequentially` flake (`e2e_orch_…` → `2e_orch_…`); hint assertion had already passed. Retry 3/3.

## Concerns

- Backend `validate_graph` still drops `bindings` on graph nodes; inspector bindings go through `graphToSteps` at save, and `attachStepBindings` restores them on edit load from compiled steps.
- Adding **if** without then/else edges still fails PUT (backend validate); the yellow warning does not block save locally, but the server will reject an incomplete if.
- If-predicate Form is a nested `Form component="div"` inside the editor form to avoid invalid nested `<form>`.
