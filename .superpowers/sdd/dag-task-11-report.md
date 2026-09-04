# Task 11 report: 接入 `local_sdk_worker`（有 graph 才走解释器）

**Status:** PASS  
**Commits:** none

## Changes

- `hmi/backend/hmi/platform/graph_runtime.py`: `assert_runnable_locally`, `preview_taken_op_ids`, `apply_graph_to_run_request`.
- `hmi/backend/hmi/services/local_sdk_worker.py`: graph branch at `_run_sdk_and_ingest` recipe_req site; review via `hmi.review_db.get_or_create_review` after `sdk_mc_write` success.
- Tests: `test_assert_blocks_asr_if`, `test_assert_allows_source_kind_if`, `test_preview_taken_op_ids`, `test_apply_graph_to_run_request`.

## Worker branch location

`hmi/backend/hmi/services/local_sdk_worker.py` → `_run_sdk_and_ingest` **after** `clip_cfg = _clip_config_from_settings()`, **~lines 740–769**:

```python
recipe_req: dict[str, Any] = {}
graph = (recipe or {}).get("graph") if recipe else None
graph_taken: list[str] = []
if isinstance(graph, dict) and graph.get("nodes"):
    assert_runnable_locally(graph)
    recipe_req = apply_graph_to_run_request(graph, recipe, settings)
    graph_taken = preview_taken_op_ids(graph, {})
elif recipe is not None:
    recipe_req = overlay_run_request(recipe, settings)
```

`assert_runnable_locally` is **not** inside the `get_data_type` try/except that logs `data_type overlay skipped`. If assert raises, `sdk_infer` is marked failed (same as `assert_bbox_settings_runnable`) and re-raised.

Review node: after `sdk_mc_write` success (~L858–863) call `_maybe_create_graph_review` → `get_or_create_review(..., review_status="pending_review")` when taken includes `review`. Import script still uses `--no-review`.

## RED

```
cwd: hmi/backend
cmd: py -3 scripts/test_platform_graph_runtime.py TestGraphRuntime.test_assert_blocks_asr_if -v
exit: 1
```

```
test_assert_blocks_asr_if ... ERROR

ERROR: test_assert_blocks_asr_if
  ImportError: cannot import name 'assert_runnable_locally' from 'hmi.platform.graph_runtime'

Ran 1 test in 0.006s
FAILED (errors=1)
```

## GREEN

```
cwd: hmi/backend
cmd: py -3 scripts/test_platform_graph_runtime.py -v
exit: 0
```

```
test_apply_graph_to_run_request ... ok
test_assert_allows_source_kind_if ... ok
test_assert_blocks_asr_if ... ok
test_if_false_skips_then_op ... ok
test_if_true_runs_then_op ... ok
test_missing_adapter_raises ... ok
test_preview_taken_op_ids ... ok
test_review_sets_pending ... ok

Ran 8 tests in 0.014s
OK
```

**8/8 PASS**

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

- No separate ASR API; `asr.` / `labels.` / `label.` ifs keep the exact RuntimeError `本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支`. Did not split `plan_and_run`.
- `audio_array_spec` still returns before the recipe_req branch; graphs on that type are unchanged.
- Graph review after ingest is best-effort (warning log on failure); ingest already succeeded.
- Did not run real Omni / `plan_and_run` E2E.
