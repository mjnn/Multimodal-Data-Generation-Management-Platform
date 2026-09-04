### Task 3: 线性配方 hydrate 成链图

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_graph.py`
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py`

**Interfaces:**
- Consumes: `hydrate_recipe_to_steps` from `recipe_pipeline.py`
- Produces: `hydrate_graph(recipe: dict[str, Any]) -> dict[str, Any]` — if `recipe.graph` present, `validate_graph` it; else build a chain from existing cards and return graph **without writing the recipe**

- [ ] **Step 1: Failing test**

```python
class TestHydrateGraph(unittest.TestCase):
    def test_oms_cabin_chain_has_label(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph, validate_graph

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        self.assertFalse(rec.get("graph"))
        g = hydrate_graph(rec)
        validate_graph(g)
        types = [n["type"] for n in g["nodes"]]
        self.assertIn("source", types)
        self.assertEqual(types.count("label"), 1)
        keys = [n["key"] for n in g["nodes"]]
        # chain: each edge target index > source index in node list
        idx = {k: i for i, k in enumerate(keys)}
        for e in g["edges"]:
            self.assertLess(idx[e["source"]], idx[e["target"]])

    def test_existing_graph_not_rebuilt(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        rec["graph"]["nodes"][0]["title"] = "自定义源名"
        again = hydrate_graph(rec)
        self.assertEqual(again["nodes"][0]["title"], "自定义源名")
```

- [ ] **Step 2: Run — expect FAIL** `hydrate_graph` missing

- [ ] **Step 3: Implement**

```python
def hydrate_graph(recipe: dict[str, Any]) -> dict[str, Any]:
    raw = recipe.get("graph")
    if isinstance(raw, dict) and raw.get("nodes"):
        return validate_graph(raw)
    from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

    steps = hydrate_recipe_to_steps(recipe)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    prev: str | None = None
    y = 0
    for step in steps:
        key = str(step.get("key") or "").strip()
        if not key:
            continue
        op_id = str(step.get("op_id") or "")
        if step.get("card_kind") == "source" or op_id == "source":
            ntype = "source"
        elif op_id == "label":
            ntype = "label"
        else:
            ntype = "op"
        nodes.append(
            {
                "key": key,
                "type": ntype,
                "op_id": op_id or ntype,
                "title": str(step.get("title") or key),
                "params": dict(step.get("params") or {}),
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->{key}",
                    "source": prev,
                    "source_port": "out",
                    "target": key,
                    "target_port": "in",
                }
            )
        prev = key
        y += 96
    if not any(n["type"] == "label" for n in nodes):
        nodes.append(
            {
                "key": "stage-label",
                "type": "label",
                "op_id": "label",
                "title": "打标器",
                "params": {},
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->stage-label",
                    "source": prev,
                    "source_port": "out",
                    "target": "stage-label",
                    "target_port": "in",
                }
            )
    return validate_graph({"nodes": nodes, "edges": edges})
```

If `hydrate_recipe_to_steps` already inserts a label card for oms_cabin, the extra insert is skipped. For `ivi_ui_stub` before seed change, this function **adds** `stage-label` so `validate_graph` passes.

- [ ] **Step 4: Run** `py -3 scripts/test_platform_recipe_graph.py TestHydrateGraph -v` Expected: PASS

---

