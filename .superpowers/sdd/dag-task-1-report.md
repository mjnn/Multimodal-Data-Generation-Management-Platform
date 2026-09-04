# Task 1 Report: 图校验（无环、打标器必经、if 端口）

## What you implemented

Added `hmi/backend/hmi/platform/recipe_graph.py` with `validate_graph(graph) -> dict` and `NODE_TYPES` / `IF_OUT_PORTS` constants.

`validate_graph` performs structural normalization and validation on a recipe DAG canvas graph:

| Rule | Behavior |
|------|----------|
| Schema | `graph` must be a dict; `nodes` non-empty list; `edges` optional list |
| Node keys | Unique, non-empty; `type` ∈ `NODE_TYPES` |
| Normalization | Fills defaults for `op_id`, `title`, `params`, `position`; source gets `params.required=True`; label gets `op_id="label"`; if nodes get `condition` |
| Exactly one label | Raises if count ≠ 1 |
| Edges | Endpoints must exist; if-node outgoing ports must be `then` or `else` |
| Acyclic | DFS cycle detection → `ValueError("graph contains a cycle")` |
| if ports | Each if node must have both `then` and `else` outgoing edges |
| Required sources | `params.required=True` sources must reach the label node (Chinese error) |
| review/export order | Must be reachable from label (downstream of label) |

Returns a deep-copied, normalized graph on success; raises `ValueError` on failure.

Test suite: `hmi/backend/scripts/test_platform_recipe_graph.py` — 6 cases covering valid chain, cycle, missing label, orphan required source, incomplete if ports, and review-before-label.

## TDD Evidence

### RED

```text
Command: py -3 scripts/test_platform_recipe_graph.py -v
CWD:     hmi/backend

test_if_requires_then_else_ports ... ERROR
test_rejects_cycle ... ERROR
test_required_source_must_reach_label ... ERROR
test_requires_exactly_one_label ... ERROR
test_review_before_label_rejected ... ERROR
test_valid_chain_roundtrip ... ERROR

ModuleNotFoundError: No module named 'hmi.platform.recipe_graph'

Ran 6 tests in 0.003s
FAILED (errors=6)
```

### GREEN

```text
Command: py -3 scripts/test_platform_recipe_graph.py -v
CWD:     hmi/backend

test_if_requires_then_else_ports ... ok
test_rejects_cycle ... ok
test_required_source_must_reach_label ... ok
test_requires_exactly_one_label ... ok
test_review_before_label_rejected ... ok
test_valid_chain_roundtrip ... ok

Ran 6 tests in 0.007s
OK
```

## Files changed

| File | Action |
|------|--------|
| `hmi/backend/hmi/platform/recipe_graph.py` | Created |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | Created |

No other files touched (per task scope).

## Self-review

- Implementation matches brief verbatim; no catalog/op lookup (Task 1 scope).
- Cycle detection uses standard 3-color DFS over normalized adjacency; ignores edges to unknown targets (already rejected at edge validation).
- `_reaches_label` and `label_reach` use forward reachability from source/label respectively — correct for “must reach label” and “review/export after label”.
- `deepcopy` ensures caller input is not mutated; normalized nodes/edges replace lists in output.
- Tests import inside each method (brief pattern) — works with `sys.path` bootstrap.
- Linter: no issues on new files.

## Concerns

1. **No export-node test** — brief only tests review-before-label; export ordering uses same code path but lacks explicit test (acceptable for Task 1 minimal scope).
2. **Optional sources** — non-required orphan sources are allowed; only tested implicitly via valid chain (no orphan). Future tasks may want explicit test.
3. **if with both branches to same target** — allowed if both `then` and `else` edges exist; semantic dedup not in Task 1 scope.
4. **No integration with `recipe.py` / router yet** — validate_graph is standalone until later slices wire it in.

## Fix round

Addressed Important review findings: forbid parallel compute joins (allow XOR if-merge and multi-source fan-in); require review/export reachable only via label (no bypass paths from sources).

### TDD RED

```text
Command: py -3 scripts/test_platform_recipe_graph.py -v
CWD:     hmi/backend

test_rejects_parallel_join_of_compute_branches ... FAIL (ValueError not raised)
test_review_mixed_path_rejected ... FAIL (ValueError not raised)
test_export_mixed_path_rejected ... FAIL (ValueError not raised)

Ran 12 tests in 0.007s
FAILED (failures=3)
```

### TDD GREEN

```text
Command: py -3 scripts/test_platform_recipe_graph.py -v
CWD:     hmi/backend

test_allows_multi_source_fan_in_to_label ... ok
test_allows_xor_merge_at_label ... ok
test_export_mixed_path_rejected ... ok
test_if_requires_then_else_ports ... ok
test_rejects_cycle ... ok
test_rejects_parallel_join_of_compute_branches ... ok
test_required_source_must_reach_label ... ok
test_requires_exactly_one_label ... ok
test_review_before_label_rejected ... ok
test_review_mixed_path_rejected ... ok
test_review_only_after_label_passes ... ok
test_valid_chain_roundtrip ... ok

Ran 12 tests in 0.008s
OK
```

### Files changed

| File | Change |
|------|--------|
| `hmi/backend/hmi/platform/recipe_graph.py` | Added `_rev_adj`, `_incoming_if_arm`, `_check_parallel_joins`, `_reachable_without`; review/export now rejects any source→node path that bypasses label |
| `hmi/backend/scripts/test_platform_recipe_graph.py` | +6 tests: parallel join reject, XOR merge allow, multi-source fan-in, review/export mixed-path reject, review-only-after-label pass |
