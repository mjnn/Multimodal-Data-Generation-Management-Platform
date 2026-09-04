### Task 4: 图投影公共前缀

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_graph.py`
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Produces: `project_graph(graph: dict[str, Any]) -> dict[str, Any]` with keys `slots`, `preprocess`, `products`, `stages`, `bbox`, `require_any_kinds`
- Produces: `graph_is_lossy(graph: dict[str, Any]) -> bool` — True if any `if` / `review` / `export` node exists

**公共前缀算法（钉死）：** 从每个必选 source BFS。遇到 `type==if` **停止向下计入 preprocess**（if 本身不是 op）。`then`/`else` 子图里的 `op` 都不进 `preprocess`。if 之前、且能到达 label 的 `op` 按一种稳定序（节点在 `nodes` 数组中的顺序）写入 `preprocess`。`embed`：若其节点在该前缀集合中则 `stages.embed.enabled=True`。`detect_bbox` 同理 → `bbox.enabled`。`label` 永远 `stages.label.enabled=True`。

- [ ] **Step 1: Failing tests**

```python
class TestProjectGraph(unittest.TestCase):
    def test_chain_projects_asr_into_preprocess(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(_chain())
        proj = project_graph(g)
        self.assertEqual(proj["slots"][0]["id"], "src")
        self.assertTrue(proj["stages"]["label"]["enabled"])
        ops = [p["op_id"] for p in proj["preprocess"]]
        self.assertEqual(ops, ["audio_asr"])

    def test_then_only_op_not_in_preprocess(self) -> None:
        from hmi.platform.recipe_graph import graph_is_lossy, project_graph, validate_graph

        g = {
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "源", "params": {}, "position": {"x": 0, "y": 0}},
                {"key": "iff", "type": "if", "title": "if", "condition": {"all": []}, "params": {}, "position": {"x": 0, "y": 80}},
                {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
                {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        g = validate_graph(g)
        proj = project_graph(g)
        self.assertEqual(proj["preprocess"], [])
        self.assertTrue(graph_is_lossy(g))
        self.assertTrue(proj["stages"]["label"]["enabled"])
```

If `audio_asr` is rejected later by `validate_recipe` (unknown op), Task 4 `project_graph` still emits it; `validate_recipe` in Task 5 only accepts catalog ops — keep `_chain` using a real preprocess op from `OPERATORS`. Check `hmi/backend/hmi/platform/operators.py` and replace `audio_asr` with an existing id (e.g. `mel_spectrogram` or whatever ASR is actually called, often `asr` or `audio_asr`). **Do this lookup in Task 4 Step 3** and fix `_chain()` to use a real `op_id` from `OPERATORS` so Task 5 roundtrip works. If no ASR op exists, use `extract_frames`.

- [ ] **Step 2: Run — expect FAIL** `project_graph` missing

- [ ] **Step 3: Implement `project_graph` / `graph_is_lossy`**

Use `slots_from_steps`-compatible slot dicts: `id=source.key`, `title`, `kinds` from `params.kinds` or `["video"]` default only if missing — prefer copying `params` kinds list. For hydrate-from-seed, source nodes should copy kinds from the card in Task 3:

Update Task 3 `hydrate_graph` source nodes to include `"params": {**step.params, "kinds": step.get("kinds"), "required": step.get("required", True), "cardinality_min": ..., "cardinality_max": ...}`.

`project_graph` slots:

```python
def graph_is_lossy(graph: dict[str, Any]) -> bool:
    g = validate_graph(graph)
    return any(n["type"] in {"if", "review", "export"} for n in g["nodes"])


def _prefix_op_keys(g: dict[str, Any]) -> list[str]:
    nodes = {n["key"]: n for n in g["nodes"]}
    adj = _adj(g["edges"])
    blocked: set[str] = set()

    def mark_from(start: str) -> None:
        stack = [start]
        seen = {start}
        while stack:
            u = stack.pop()
            blocked.add(u)
            for e in adj.get(u, []):
                v = str(e.get("target") or "")
                if v and v not in seen:
                    seen.add(v)
                    stack.append(v)

    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for e in adj.get(n["key"], []):
            tgt = str(e.get("target") or "")
            if tgt:
                mark_from(tgt)
    prefix: list[str] = []
    for n in g["nodes"]:
        if n["type"] == "op" and n["key"] not in blocked:
            prefix.append(n["key"])
    return prefix


def project_graph(graph: dict[str, Any]) -> dict[str, Any]:
    from hmi.platform.recipe_pipeline import _require_any_kinds_from_slots

    g = validate_graph(graph)
    nodes = {n["key"]: n for n in g["nodes"]}
    slots = []
    for n in g["nodes"]:
        if n["type"] != "source":
            continue
        p = n["params"]
        kinds = list(p.get("kinds") or ["video"])
        slots.append(
            {
                "id": n["key"],
                "title": n["title"],
                "kinds": kinds,
                "cardinality_min": int(p.get("cardinality_min") or 1),
                "cardinality_max": int(p.get("cardinality_max") or 1),
                "role": str(p.get("role") or "input"),
                "required": bool(p.get("required", True)),
            }
        )
    prefix_keys = _prefix_op_keys(g)
    preprocess = []
    products = []
    bbox = {"enabled": False, "detector": "opencv", "yolo_classes": ""}
    embed_enabled = False
    for key in prefix_keys:
        n = nodes[key]
        op_id = str(n.get("op_id") or "")
        if op_id == "embed":
            embed_enabled = True
            continue
        if op_id == "detect_bbox":
            bbox = {
                "enabled": True,
                "detector": str(n["params"].get("detector") or "opencv"),
                "yolo_classes": str(n["params"].get("yolo_classes") or ""),
            }
        entry: dict[str, Any] = {"op_id": op_id, "when_kind": n["params"].get("when_kind"), "required": False}
        produces = n["params"].get("produces")
        if produces:
            entry["produces"] = list(produces)
            for name in produces:
                products.append({"id": name, "from_op": op_id, "reusable": True})
        preprocess.append(entry)
    return {
        "slots": slots,
        "preprocess": preprocess,
        "products": products,
        "stages": {"label": {"enabled": True}, "embed": {"enabled": embed_enabled}},
        "bbox": bbox,
        "require_any_kinds": _require_any_kinds_from_slots(slots),
    }
```

If `_require_any_kinds_from_slots` is private, export it or duplicate the small helper in `recipe_graph.py` (copy the existing function body from `recipe_pipeline.py` rather than importing a private name if tests complain).

- [ ] **Step 4: Run** `py -3 scripts/test_platform_recipe_graph.py TestProjectGraph -v` Expected: PASS

---

