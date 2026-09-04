### Task 10: `graph_runtime` 调度 + 假适配器（切片 D）

**Files:**
- Create: `hmi/backend/hmi/platform/graph_runtime.py`
- Test: `hmi/backend/scripts/test_platform_graph_runtime.py`

**Interfaces:**
- `Adapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]`  `(node, ctx) -> ctx patch`
- `execute_graph(graph, *, ctx0: dict, adapters: dict[str, Adapter]) -> dict` returns `{ctx, run: [{key, status}]}` where status is `success|skipped`
- Walk: start from all `source` nodes (mark success, merge `source.kind` / `source.slot_id` from ctx0 or node params). Ready set = nodes whose **at least one incoming edge** was taken, or no incoming. If node has incoming, require the taken predecessor. Never wait for untaken if-branch.
- `if`: `eval_condition`; take `then` if True else `else`. Missing `else` target = no-op.
- Unknown `op_id` with no adapter → raise `RuntimeError(f"missing adapter for op_id={op_id}")`
- `label` adapter required in the map; if label never executed → `RuntimeError("打标器未执行")`
- `review` adapter may set `ctx["review_status"]="pending_review"`
- `export` adapter may set `ctx["exported_product_ids"]=list`

- [ ] **Step 1: Failing tests**

```python
class TestGraphRuntime(unittest.TestCase):
    def test_if_false_skips_then_op(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True, "kinds": ["audio"]}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
                {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        })
        ran = []

        def frames(_n, ctx):
            ran.append("frames")
            return ctx

        def label(_n, ctx):
            ran.append("label")
            ctx = dict(ctx)
            ctx["labels"] = {"ok": True}
            return ctx

        out = execute_graph(
            g,
            ctx0={"source": {"kind": "audio", "slot_id": "src"}, "asr": {"avg_confidence": 0.1}},
            adapters={"extract_frames": frames, "label": label},
        )
        self.assertEqual(ran, ["label"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["fr"], "skipped")
        self.assertEqual(statuses["lab"], "success")

    def test_review_sets_pending(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 80}},
                {"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"},
                {"id": "b", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"},
            ],
        })
        out = execute_graph(
            g,
            ctx0={"source": {"kind": "video", "slot_id": "src"}},
            adapters={"label": lambda n, c: {**c, "labels": {}}},
        )
        self.assertEqual(out["ctx"].get("review_status"), "pending_review")
```

- [ ] **Step 2: Run — expect FAIL** missing module

- [ ] **Step 3: Implement `execute_graph`**

Use a worklist. Record `taken_edges: set[str]`. When executing `if`, add only the chosen outgoing edge id to `taken_edges`. A node is runnable when every **incoming edge from a taken predecessor path** is satisfied: if all incoming edges' sources are skipped, and none taken, skip the node. XOR join: if **any** incoming edge is taken, run once.

Default adapters inside `execute_graph` for `review` / `export` / `source` / `if` so tests need not pass them. `op` and `label` must be in `adapters`.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_graph_runtime.py -v` Expected: PASS  
Also re-run `test_platform_recipe_graph.py` PASS

---

