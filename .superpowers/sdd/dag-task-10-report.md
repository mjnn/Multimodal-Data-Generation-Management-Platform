# Task 10 report: `graph_runtime` 调度 + 假适配器

**Status:** PASS  
**Commits:** none

## Changes

- Created `hmi/backend/hmi/platform/graph_runtime.py` — `execute_graph(graph, *, ctx0, adapters)` walks the DAG with a worklist + `taken_edges`.
- Default adapters for `source` / `if` / `review` / `export`. `op` and `label` must be supplied or raise `missing adapter for op_id=…`. Label never `success` → `打标器未执行`.
- `if`: `eval_condition`; take `then` or `else` (missing else = no-op). XOR join: any taken incoming edge runs the node once; all preds processed and none taken → skip.
- Tests: `hmi/backend/scripts/test_platform_graph_runtime.py` (brief + if-true + missing adapter). Did **not** implement `assert_runnable_locally`.

## RED

```
cwd: hmi/backend
cmd: py -3 scripts/test_platform_graph_runtime.py -v
exit: 1
```

```
test_if_false_skips_then_op ... ERROR
test_if_true_runs_then_op ... ERROR
test_missing_adapter_raises ... ERROR
test_review_sets_pending ... ERROR

ERROR: test_if_false_skips_then_op
  ModuleNotFoundError: No module named 'hmi.platform.graph_runtime'
ERROR: test_if_true_runs_then_op
  ModuleNotFoundError: No module named 'hmi.platform.graph_runtime'
ERROR: test_missing_adapter_raises
  ModuleNotFoundError: No module named 'hmi.platform.graph_runtime'
ERROR: test_review_sets_pending
  ModuleNotFoundError: No module named 'hmi.platform.graph_runtime'

Ran 4 tests in 0.003s
FAILED (errors=4)
```

## GREEN

```
cwd: hmi/backend
cmd: py -3 scripts/test_platform_graph_runtime.py -v
exit: 0
```

```
test_if_false_skips_then_op ... ok
test_if_true_runs_then_op ... ok
test_missing_adapter_raises ... ok
test_review_sets_pending ... ok

Ran 4 tests in 0.008s
OK
```

**4/4 PASS**

### Regression: `test_platform_recipe_graph.py`

```
cwd: hmi/backend
cmd: py -3 scripts/test_platform_recipe_graph.py -v
exit: 0
```

```
Ran 24 tests in 0.013s
OK
```

**24/24 PASS**

## Concerns

- Waiting join nodes are not re-queued on `continue`; they rely on a later predecessor finish to `enqueue` them again (safe on DAGs).
- Skipped `op` nodes do not require an adapter (only when actually executed). Label is still required to reach `success`.
- `validate_graph` still requires both `then` and `else` edges; runtime "missing else = no-op" is for graphs that would not currently validate.
- Task 11 (`assert_runnable_locally`, `local_sdk_worker`) not started, per brief.
