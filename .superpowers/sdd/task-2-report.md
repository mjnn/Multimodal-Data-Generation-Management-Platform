# Task 2 Report: hydrate slots → source cards; compile source cards → slots

**Status:** DONE  
**Branch:** feat/platform-datatype-kernel  
**Commits:** none (plan forbids commit unless user asks)

## What changed

### `hmi/backend/hmi/platform/recipe_pipeline.py`

New helpers:

| Function | Behavior |
|----------|----------|
| `is_source_card(card)` | `card_kind=="source"` **or** `op_id=="source"` |
| `new_source_card(*, key, title, kinds, cardinality_min=1, cardinality_max=1, required=True)` | Shape: `card_kind/op_id=source`, `produces=kinds`, `bindings={}` |
| `slots_from_steps(steps)` | Source cards → `{id: key, title, kinds, cardinality_*, required, role: "input"}` |
| `assert_upward_bindings(steps)` | `bindings.slot_id` / `step_key` that match a card `key` must sit at a **lower index**. Unresolved ids (legacy slots not present as cards) are allowed so `new_step_from_op(..., slots=[])` / compile-with-slots-param tests stay valid. |

`hydrate_recipe_to_steps`:

- Builds source cards from `recipe.slots` in slot order (`key=slot.id`, `title=slot.title or id`).
- Then existing preprocess / bbox-synthetic / stage cards.
- Copies `raw["output_labels"]` onto the preprocess op card (sibling of params, not inside params).

`compile_steps`:

- Calls `assert_upward_bindings` first.
- If steps contain source cards, **ignores** the `slots=` argument and uses `slots_from_steps`.
- Skips `is_source_card` when building preprocess (so `op_id=source` never becomes a preprocess step).
- Attaches card `output_labels` onto preprocess entries.
- Return value adds `"slots"` and `"require_any_kinds"`. Required sources each contribute one kinds group; if none are required, falls back to every source’s kinds (so all-optional `oms_cabin` still validates).

`binding_options`:

- Slot / source-card options use `title` as `label` (fallback `槽位 {id}`).
- Source cards in `upstream` are treated as slots (deduped by id).
- Upstream op port label is `output_labels.get(name) or name` (still prefixed with operator title).

`new_step_from_op` is unchanged in signature; existing `slots=[]` callers remain valid.

Task 1 (`validate_recipe` title / `output_labels`) was not touched.

## Tests added (`test_platform_datatype_editor.py`)

| Test | Intent |
|------|--------|
| `test_hydrate_oms_cabin_starts_with_source_cards` | oms_cabin hydrates `rosbag/video/image/audio` source cards **before** `parse_bag`; compile returns the same slot ids |
| `test_binding_to_later_source_rejected` | `[parse, src]` raises; `[src, parse]` ok |
| `test_hydrate_output_labels_compile_back` | hydrate copies `output_labels`; compile writes them back; skips source in preprocess; required source → `require_any_kinds` |

## TDD sequence

1. Wrote the two brief tests plus one output_labels / require_any_kinds test.
2. Ran the three new tests → ERROR as expected (`ImportError: slots_from_steps` / `assert_upward_bindings` / `new_source_card`).
3. Implemented helpers + hydrate/compile/binding_options.
4. Re-ran full editor + kernel suites.

## Verification

```text
py -3 hmi/backend/scripts/test_platform_datatype_editor.py
Ran 18 tests in ~4.7s
OK

py -3 hmi/backend/scripts/test_platform_datatype_kernel.py
Ran 15 tests in ~3.9s
OK
```

(Prior editor suite after Task 1 was 15 tests; +3 new = 18.)

## Self-review

| Check | Result |
|-------|--------|
| Scope limited to Task 2 (no frontend) | Yes |
| Task 1 validate_recipe not reverted | Yes |
| parse_bag picture product still `frames`, not `.mp4` | Yes (untouched) |
| Source cards: `card_kind=="source"`, `op_id=="source"`, `key=slot.id` | Yes |
| Hydrate: source cards first (slot order), then op/stage cards | Yes |
| compile skips source cards; returns slots + require_any_kinds; copies output_labels | Yes |
| `assert_upward_bindings` in `compile_steps` | Yes |
| `new_step_from_op` still exists | Yes |
| Git commit | Not performed |

## Concerns

1. **All-optional slots and `require_any_kinds`:** Brief says groups come from **required** sources. `oms_cabin` slots are all `required=False`, so a strict empty list would fail `validate_recipe` on hydrate→compile (`recipe.require_any_kinds must be a non-empty list`). Implementation falls back to every source’s kinds, matching `DataTypeEditorPage` (`required.length ? required : all slots`). Existing `test_hydrate_compile_oms_cabin_stages` depends on this.
2. **`assert_upward_bindings` and legacy slot ids:** Refs that are not any card `key` are skipped (not raised). Strict “must be an earlier card key” would break `compile_steps([mel, label], slots)` where `slot_id` is only in the `slots=` param. The brief’s failing case (target card exists **later**) still raises.
3. **`slots_from_steps` always `role: "input"`:** Original seed roles (`bag` / `video` / …) are dropped on compile, as the brief specifies.
4. **`new_step_from_op` `when_kind`:** If the chosen option is a source card from `upstream` rather than the `slots` list, `when_kind` stays `None` because lookup is still `slots` by id. Frontend Task 4 can pass source-derived slots if needed.

## Files touched

- `hmi/backend/hmi/platform/recipe_pipeline.py`
- `hmi/backend/scripts/test_platform_datatype_editor.py`
- `.superpowers/sdd/task-2-report.md` (this file)
