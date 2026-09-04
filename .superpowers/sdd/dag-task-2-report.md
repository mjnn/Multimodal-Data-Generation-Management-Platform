# Task 2 Report: 条件表达式求值

## Status

**DONE** — TDD RED → GREEN; 18/18 tests pass.

## TDD

### RED

Added `TestGraphExpr` (6 cases) to `hmi/backend/scripts/test_platform_recipe_graph.py`.

```text
py -3 scripts/test_platform_recipe_graph.py TestGraphExpr -v
→ 6 ERROR (ModuleNotFoundError: hmi.platform.graph_expr)
```

### GREEN

Implemented `graph_expr.py`, wired `validate_condition` into `validate_graph`, re-ran full suite:

```text
py -3 scripts/test_platform_recipe_graph.py -v
→ Ran 18 tests in 0.010s — OK
```

| Suite | Tests | Result |
|-------|-------|--------|
| TestGraphExpr | 6 | PASS |
| TestValidateGraph (Task 1) | 12 | PASS |
| **Total** | **18** | **PASS** |

## Files Changed

| File | Action |
|------|--------|
| `hmi/backend/hmi/platform/graph_expr.py` | **Created** — `OPS`, `FIELD_WHITELIST`, `validate_condition`, `eval_condition` |
| `hmi/backend/hmi/platform/recipe_graph.py` | **Modified** — import `validate_condition`; defer if-node condition until adj built; `after_label = ik in label_reach` |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | **Modified** — append `TestGraphExpr` |

## Implementation Notes

### `graph_expr.py`

- **Whitelist**: `BASE_FIELDS` (source/asr) always allowed; `POST_LABEL_FIELDS` + `labels.*` dot-paths only when `after_label=True`.
- **Validation**: one-level `{"all": [pred, ...]}`; rejects unknown fields/ops (incl. `eval`); normalizes predicates; `exists`/`not_exists` omit `value`.
- **Evaluation**: AND semantics over predicates; missing ctx → `None` → false for comparisons; empty/missing `all` → true.

### `validate_graph` wiring

1. First pass stores raw `condition` on if nodes as `_raw_condition` (internal, stripped before return).
2. After edges normalized and `adj` built: `label_reach = _reachable(label_key, adj)`.
3. For each if node: `after_label = ik in label_reach`; `condition = validate_condition(raw, after_label=after_label)`.
4. All Task 1 checks (cycle, one label, if then/else, parallel-join, review/export after label) unchanged.

## Self-Review

| Check | Verdict |
|-------|---------|
| Task 1 tests untouched / green | OK |
| Brief interfaces (`OPS`, `FIELD_WHITELIST`, `validate_condition`, `eval_condition`) | OK |
| `after_label` = reachable from label node | OK (`ik in _reachable(label_key, adj)`) |
| No pipeline/dataworks / local_sdk_worker changes | OK |
| No git commit | OK |

### Minor notes (non-blocking)

- `_raw_condition` is an internal staging key; popped before output — not part of public graph schema.
- `FIELD_WHITELIST` exports static base+post-label fields; dynamic `labels.*` paths are allowed only at validate time when `after_label=True`.
- Numeric compares coerce via `float()`; non-numeric left for `gt`/`gte`/etc. returns false (per brief `_cmp`).

## Concerns

None blocking. Future tasks may want integration tests that `validate_graph` rejects `labels.*` on pre-label if nodes end-to-end (currently covered only in `TestGraphExpr.validate_condition` unit tests).

## Commits

None (per task instructions).
