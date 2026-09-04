# Task 3 Report: 线性配方 hydrate 成链图

## Status

**DONE** — TDD RED → GREEN; 20/20 tests pass.

## TDD

### RED

Added `TestHydrateGraph` (2 cases) to `hmi/backend/scripts/test_platform_recipe_graph.py`.

```text
py -3 scripts/test_platform_recipe_graph.py TestHydrateGraph -v
→ 2 ERROR (ImportError: cannot import name 'hydrate_graph' from 'hmi.platform.recipe_graph')
```

### GREEN

Implemented `hydrate_graph` in `recipe_graph.py`, re-ran full suite:

```text
py -3 scripts/test_platform_recipe_graph.py -v
→ Ran 20 tests in 0.013s — OK
```

| Suite | Tests | Result |
|-------|-------|--------|
| TestHydrateGraph | 2 | PASS |
| TestValidateGraph (Task 1) | 12 | PASS |
| TestGraphExpr (Task 2) | 6 | PASS |
| **Total** | **20** | **PASS** |

## Files Changed

| File | Action |
|------|--------|
| `hmi/backend/hmi/platform/recipe_graph.py` | **Modified** — add `hydrate_graph(recipe)` |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | **Modified** — append `TestHydrateGraph` |

## Implementation Notes

- **Existing graph**: if `recipe.graph.nodes` present, return `validate_graph(raw)` unchanged (preserves custom titles).
- **Linear chain**: calls `hydrate_recipe_to_steps(recipe)`; maps steps to nodes (`source` / `op` / `label` by `card_kind` / `op_id`); chains edges prev→next; `y += 96`.
- **Label fallback**: if no label node after steps, append `stage-label` and connect from last node.
- Returns `validate_graph` output; does not mutate recipe.

## Self-Review

| Check | Verdict |
|-------|---------|
| Task 1+2 tests untouched / green | OK |
| Uses `hydrate_recipe_to_steps` from `recipe_pipeline` | OK |
| No DataWorks / local_sdk_worker / frontend changes | OK |
| No git commit | OK |

## Concerns

None blocking. `stage-label` fallback only fires when `hydrate_recipe_to_steps` omits a label card (e.g. legacy `ivi_ui_stub`).

## Commits

None (per task instructions).
