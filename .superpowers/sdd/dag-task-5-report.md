# Task 5 Report: `validate_recipe` + graph + ivi seed + `labels_tree`

## Status

**DONE** — no commits.

## Changes

| File | Change |
|------|--------|
| `hmi/backend/hmi/platform/recipe.py` | `validate_recipe` projects graph when `graph.nodes` present; ivi seed `label.enabled=True` + `model=default` |
| `hmi/backend/hmi/platform/views.py` | `labels_tree` widget; `hydrate_overview` inserts locked card at detail[0] |
| `hmi/backend/hmi/platform/recipe_pipeline.py` | `pin_label_last`: keep order if label present; append if missing |
| `scripts/test_platform_recipe_graph.py` | `TestRecipeGraphIntegration` |
| `scripts/test_platform_datatype_editor.py` | renamed `test_pin_label_last_*` |
| `scripts/test_platform_datatype_kernel.py` | ivi label enabled; overview expects `labels_tree`; preflight expects `label` in ops |

## TDD

### RED (before implement)

| Suite | Result |
|-------|--------|
| `test_platform_recipe_graph.py` | **FAIL** ×2 — `test_ivi_seed_label_enabled` (False); `test_validate_recipe_projects_graph` (`cabin_multicam` ≠ `labels_tree`) |
| `test_platform_datatype_editor.py` | OK (weaker pin_label assertion already passes) |
| `test_platform_datatype_kernel.py` | **FAIL** ×3 — ivi enabled; overview cards missing `labels_tree` |

### GREEN (after implement)

| Suite | Result |
|-------|--------|
| `test_platform_recipe_graph.py` | **OK** — 24 tests |
| `test_platform_datatype_editor.py` | **OK** — 26 tests |
| `test_platform_datatype_kernel.py` | **OK** — 19 tests (also updated `test_image_ivi_ok` to expect `label` in ops) |

cwd: `hmi/backend`

## Concerns

- `hydrate_overview` always injects `labels_tree` for every recipe (not only graph recipes); kernel overview assertions updated accordingly.
- Graph projection overwrites normalized slots/preprocess without a second normalize pass (relies on `project_graph` shape).
- Enabling ivi label changes preflight ops; callers assuming label-off for ivi may need review.
