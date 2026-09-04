### Task 11: 接入 `local_sdk_worker`（有 graph 才走解释器）

**Files:**
- Modify: `hmi/backend/hmi/services/local_sdk_worker.py`（`_run_sdk_and_ingest` 在读到 `recipe.graph.nodes` 后分支）
- Modify: `hmi/backend/hmi/platform/graph_runtime.py`（`assert_runnable_locally`、`preview_taken_op_ids`、`apply_graph_to_run_request`）

**Interfaces:**
- 无 `graph`：调用方完全走今日路径（`plan_and_run` / `_run_audio_array_spec`），零行为差
- 有 `graph`：先 `assert_runnable_locally`；再用假适配器 `preview_taken_op_ids` 得到本次会跑的 `op_id` 集合；把 `need_label` / `need_embed` / `bbox_enabled` 按 **taken** 集合写入，然后仍调用现有 `plan_and_run`（或阵列专用路径）
- `review` 在 taken 中：run 成功后对该 clip 调用 `hmi.review_db` 里现有的写入函数，`review_status="pending_review"`（打开 `review_db.py` 用真实函数名，不要编造）
- **ASR/标签之后的 if（钉死护栏）：** 若任一 if 的 `condition.all[].field` 以 `asr.` / `labels.` / `label.` 开头，`assert_runnable_locally` 抛 `RuntimeError("本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")`。图仍可保存（D10）；本地跑到该配方会失败而不是静默忽略。真正拆分 `plan_and_run` 不在本计划扩 scope，除非本任务实现中已有现成的独立 ASR API 可接（有则接；没有则只留护栏并写入 acceptance）

```python
def assert_runnable_locally(graph: dict[str, Any]) -> None:
    g = validate_graph(graph)
    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for pred in (n.get("condition") or {}).get("all") or []:
            field = str(pred.get("field") or "")
            if field.startswith("asr.") or field.startswith("labels.") or field.startswith("label."):
                raise RuntimeError("本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")
```

`preview_taken_op_ids(graph, ctx0)` = `execute_graph` + 对每个 `op`/`label` 注册 no-op adapter，返回 `status==success` 的 `op_id` 列表。

`apply_graph_to_run_request` 返回与今日 `overlay_run_request` 相同键：`need_label`、`need_embed`、`bbox_enabled` 等，来源改为 taken 集合。

- [ ] **Step 1: Failing test for the guard**

```python
    def test_assert_blocks_asr_if(self) -> None:
        from hmi.platform.graph_runtime import assert_runnable_locally
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
            ],
        })
        with self.assertRaises(RuntimeError):
            assert_runnable_locally(g)
```

- [ ] **Step 2: Run** `py -3 scripts/test_platform_graph_runtime.py TestGraphRuntime.test_assert_blocks_asr_if -v`  
working_directory: `hmi/backend`  
Expected: FAIL until `assert_runnable_locally` exists

- [ ] **Step 3: Implement guard + worker branch**

After `recipe = get_data_type(...)` in `_run_sdk_and_ingest`:

```python
    graph = (recipe or {}).get("graph") if recipe else None
    if isinstance(graph, dict) and graph.get("nodes"):
        from hmi.platform.graph_runtime import apply_graph_to_run_request, assert_runnable_locally

        assert_runnable_locally(graph)
        recipe_req = apply_graph_to_run_request(graph, recipe, settings)
```

If `graph` is missing, do not call these imports; keep the current `overlay_run_request` block.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_graph_runtime.py -v` Expected: PASS。不要跑真实 Omni。

---

