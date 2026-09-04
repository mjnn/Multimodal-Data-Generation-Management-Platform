# Task 4 Report: DataType editor — source cards in pipeline list

**Status:** DONE  
**Branch:** (working tree)  
**Commits:** none

## What changed

- Created `PipelineSourceCard.tsx`: title / kinds (catalog `sourceKindOptions`) / min / max / required; `data-testid="pipe-source-card"`.
- `PipelineOrchestrator`: dropped `slots` prop (`slotsFromSteps(steps)`); `pipe-add-source` inserts `newSourceCard({ key: src-${Date.now()}, title: '数据源', kinds: ['.mp4'] })` at list start; renders source vs operator cards; operator `index`/`total` count operators only; move/remove use real array index; removing a source clears `bindings.kind==='slot' && slot_id===gone`.
- `DataTypeEditorPage`: deleted 源槽位 Card + Form.List; `EditorForm` has no `slots`; `buildRecipe` uses `compileSteps(steps, [], ops)` slots / require_any_kinds / preprocess / stages / bbox.
- `PipelineStepCard`: produce chips show `output_labels[t] || typeLabel(t)` plus a compact display-name Input per produce.

## Verification

```text
cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"
exit code: 0
```

Playwright not updated (Task 5). Lake-run not touched (Task 6–7).

## Concerns

1. Existing e2e still clicks「添加槽位」and assumes Form.List — will fail until Task 5.
2. New recipes have no source card until `pipe-add-source`; save requires at least one compiled slot.
3. Home page copy still mentions 源槽位 (out of scope).

## Task 4 review fix (clone binding remap)

**Status:** DONE

- Added local `remapStepKeys(steps, suffix='-copy')` in `DataTypeEditorPage.tsx`: suffixes step keys and rewrites bindings where `kind==='slot'` (`slot_id`) or `kind==='upstream'` (`step_key`) appear in the keymap.
- Both clone paths (`?from=` URL param + template Select) now call `remapStepKeys(hydrateRecipeToSteps(...))` instead of bare key suffix.
- `defaultNewSteps` seeds one `newSourceCard` for brand-new recipes.

**Verification**

```text
cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"
exit code: 0
```
