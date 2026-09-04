# Task 1 Report: slots.title + preprocess.output_labels validation

**Status:** DONE  
**Branch:** feat/platform-datatype-kernel  
**Commits:** none (plan forbids commit unless user asks)

## What changed

### `hmi/backend/hmi/platform/recipe.py` — `validate_recipe`

1. **Slot `title`**
   - Normalized as `title = str(slot.get("title") or slot_id).strip() or slot_id`.
   - Always written onto each normalized slot object.
   - Case-insensitive uniqueness via `title.casefold()`; collision raises `ValueError("duplicate slot title")`.

2. **Preprocess `output_labels`**
   - After building each preprocess `entry` (and after `produces` / `params` are attached), optional `output_labels` is validated and stored as a **sibling** of `params` on the step — never inside `params` (so `param_keys_for_op` is unaffected).
   - Must be a `dict`; unknown ports raise `ValueError` containing `output_labels` when the step’s `produces` list is non-empty and the port is not in it.
   - Empty / whitespace-only label values are dropped; empty `clean` omits the field.
   - When `produces` is empty/absent, port membership is not enforced (`if allowed and port not in allowed`), matching the brief snippet (operator-default lookup left for later UI/hydrate work if needed).

### `hmi/backend/scripts/test_platform_datatype_editor.py`

Added three tests under `TestDataTypeEditorUpsert`:

| Test | Intent |
|------|--------|
| `test_slot_title_and_output_labels_roundtrip` | oms_cabin: set slot title; locate `op_id=="parse_bag"`, set `produces` then `output_labels`, re-validate |
| `test_output_labels_unknown_port_rejected` | `not_a_port` rejected with message containing `output_labels` |
| `test_duplicate_slot_title_rejected` | `Primary` vs `primary` → `duplicate slot title` |

Roundtrip attaches labels to **parse_bag by `op_id`**, not hard-coded index 0 (seed currently has parse_bag at [0], but lookup is clearer for future seeds).

## TDD sequence

1. Wrote failing tests first.
2. Ran the three new tests → FAIL/ERROR as expected (`KeyError: 'title'`; unknown port / duplicate title not raised).
3. Implemented minimal `validate_recipe` changes.
4. Re-ran full editor suite.

## Verification

```text
py -3 hmi/backend/scripts/test_platform_datatype_editor.py
Ran 15 tests in ~4.5s
OK
```

(Prior baseline was 12 tests; +3 new = 15.)

## Self-review

| Check | Result |
|-------|--------|
| Scope limited to Task 1 (no hydrate/compile / Task 2) | Yes |
| `output_labels` not inside `params` | Yes |
| Duplicate title message contains `duplicate slot title` | Yes |
| Unknown port message contains `output_labels` | Yes |
| Git commit | Not performed |
| Brief vs disk: followed brief + existing validate patterns | Yes |

## Concerns

1. **Empty `produces`:** Spec text says keys should belong to operator default outputs when `produces` is empty; the brief’s code snippet only skips the check when `allowed` is empty. Implementation follows the snippet. Tightening to catalog defaults can be a follow-up if UI ships unlabeled empty-produces steps.
2. **Default titles = slot ids:** After validate, every slot now has a `title` field. Casefold collisions between an explicit title and another slot’s id-default are intentional.
3. Pre-existing sqlite `ResourceWarning` noise in the test run is unrelated to this change.

## Files touched

- `hmi/backend/hmi/platform/recipe.py`
- `hmi/backend/scripts/test_platform_datatype_editor.py`
- `.superpowers/sdd/task-1-report.md` (this file)
