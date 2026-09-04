# Task 3 Report: frontend types + recipePipeline source-card mirror

**Status:** DONE  
**Branch:** (working tree)  
**Commits:** none (plan forbids commit unless user asks)

## What changed

### `hmi/frontend/src/api/types.ts`

| Type | Fields added |
|------|----------------|
| `PipelineStep` | `card_kind?`, `title?`, `kinds?`, `cardinality_min?`, `cardinality_max?`, `output_labels?` |
| `DataTypeSlot` | `title?` |
| `DataTypePreprocessStep` | `output_labels?` |

### `hmi/frontend/src/utils/recipePipeline.ts`

Mirrored Task 2 backend helpers:

| Function | Behavior |
|----------|----------|
| `isSourceCard` | `card_kind==='source'` **or** `op_id==='source'` |
| `newSourceCard` | Shape: `card_kind/op_id=source`, `produces=kinds`, `bindings={}` |
| `slotsFromSteps` | Source cards → `{id: key, title, kinds, cardinality_*, required, role: 'input'}` |
| `assertUpwardBindings` | Binding refs that match a card `key` must sit at a lower index; unresolved ids skipped |

`hydrateRecipeToSteps`:

- Prepends source cards from `recipe.slots` (`key=slot.id`, `title=slot.title \|\| id`).
- Copies preprocess `output_labels` onto op cards.

`compileSteps`:

- Calls `assertUpwardBindings` first.
- If steps contain source cards, uses `slotsFromSteps` (ignores Form.List slots arg).
- Skips source cards when building preprocess.
- Attaches `output_labels` onto preprocess entries.
- Return type now includes `slots` + `require_any_kinds` (required sources’ kinds; all-optional fallback like backend). Still returns `preprocess` / `products` / `stages` / `bbox` so `DataTypeEditorPage.buildRecipe` keeps working.

`bindingOptions`:

- Slot / source-card options use `title` as label (fallback `槽位 {id}`); source cards in `upstream` act as slots (deduped by id).
- Op products: `` `${op.title} · ${output_labels?.[name] \|\| typeLabel(name)}` ``.

`typeLabel(t, labels?)`: prefers `labels[t]`, then existing `normalizeSourceKind` / `TYPE_LABELS` (`frames` → 连续帧).

### `hmi/frontend/src/components/datatype/PipelineOrchestrator.tsx`

Skips rendering source cards (`isSourceCard`) so `PipelineStepCard` is not fed `op_id==='source'`. Full Source card UI is Task 4. **Did not** remove the 源槽位 Form.List.

## Verification

```text
cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"
exit code: 0
```

## Self-review

| Check | Result |
|-------|--------|
| Types optional; mirror backend field names | Yes |
| hydrate prepends source cards | Yes |
| compile returns slots + require_any_kinds; keeps preprocess/stages/bbox | Yes |
| Form.List 源槽位 untouched | Yes |
| No git commit | Yes |
| tsc green | Yes |

## Concerns

1. **Dual slot state until Task 4:** After hydrate, steps hold source cards while Form.List still edits `slots`. `compileSteps` prefers source cards when present, so Form.List edits may be ignored on save for loaded recipes — expected until Task 4 removes Form.List and adds Source card UI.
2. **Source cards hidden:** Orchestrator skips them; empty-state copy may show if only source cards exist (unlikely while Form.List + default label step remain).
3. **`buildRecipe` still computes `require_any_kinds` from Form.List then spreads `...compiled`**, so compiled slots/require_any_kinds win when source cards exist — consistent with backend.
