### Task 5: `validate_recipe` 接入 graph + ivi 种子 + `labels_tree` widget

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe.py`（`validate_recipe` 末尾；`SEED_RECIPES["ivi_ui_stub"]`）
- Modify: `hmi/backend/hmi/platform/views.py`（widget + `hydrate_overview`）
- Modify: `hmi/backend/hmi/platform/recipe_pipeline.py`（`pin_label_last` 改为 no-op 文档：函数保留但不再强制最后，避免旧调用崩；或改为只保证 label 存在）
- Test: `hmi/backend/scripts/test_platform_recipe_graph.py` + existing `test_pin_label_last` 更新

**Interfaces:**
- `validate_recipe`: 若有 `graph`，`validate_graph` 后 `project_graph` **覆盖** slots/preprocess/stages/bbox/require_any_kinds；再 `hydrate_overview`（此时已含 labels_tree）
- ivi seed: `"stages": {"label": {"enabled": True, "model": "default"}, "embed": {"enabled": False}}`

- [ ] **Step 1: Failing tests**

```python
class TestRecipeGraphIntegration(unittest.TestCase):
    def test_validate_recipe_projects_graph(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        out = validate_recipe(rec)
        self.assertTrue(out["graph"]["nodes"])
        self.assertTrue(out["stages"]["label"]["enabled"])
        self.assertEqual(out["overview"]["detail"][0]["widget_id"], "labels_tree")

    def test_ivi_seed_label_enabled(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        out = validate_recipe(SEED_RECIPES["ivi_ui_stub"])
        self.assertTrue(out["stages"]["label"]["enabled"])
```

Also change `test_pin_label_last` in `test_platform_datatype_editor.py` to:

```python
    def test_pin_label_last_keeps_label_present_not_forced_last(self) -> None:
        from hmi.platform.recipe_pipeline import pin_label_last

        steps = [
            {"op_id": "source", "card_kind": "source"},
            {"op_id": "label"},
            {"op_id": "parse_bag"},
        ]
        out = pin_label_last(steps)
        self.assertTrue(any(s.get("op_id") == "label" for s in out))
        # label may sit before parse_bag (DAG successor)
```

- [ ] **Step 2: Run — expect FAIL** ivi still `enabled: False`; no `labels_tree` widget

- [ ] **Step 3: Implement**

In `views.py` add widget before `VIEW_WIDGET_IDS`:

```python
    "labels_tree": {
        "id": "labels_tree",
        "surface": "detail",
        "title": "标签树",
        "description": "必选产物：当前 run 的 labels_json",
        "needs": ["labels_tree"],
    },
```

In `hydrate_overview`, after building `detail_cards`:

```python
    if not any(str(c.get("widget_id")) == "labels_tree" for c in detail_cards):
        detail_cards.insert(
            0,
            {
                "key": "locked-labels_tree",
                "widget_id": "labels_tree",
                "bindings": {"in": {"kind": "upstream", "step_key": "stage-label", "port_id": "labels_tree"}},
            },
        )
```

`_normalize_card_list` must allow `labels_tree` once it is in `VIEW_WIDGETS`.

In `validate_recipe` after existing overview hydrate:

```python
    graph_in = out.get("graph")
    if isinstance(graph_in, dict) and graph_in.get("nodes"):
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(graph_in)
        proj = project_graph(g)
        out["graph"] = g
        out["slots"] = proj["slots"]
        out["preprocess"] = proj["preprocess"]
        out["products"] = proj["products"]
        out["stages"] = proj["stages"]
        # keep label.model from original stages if projected enabled
        prev_model = ((recipe.get("stages") or {}).get("label") or {}).get("model")
        if prev_model and out["stages"]["label"].get("enabled"):
            out["stages"]["label"]["model"] = prev_model
        out["bbox"] = proj["bbox"]
        out["require_any_kinds"] = proj["require_any_kinds"]
    out["overview"] = hydrate_overview(out)
```

Call this **after** slots/preprocess were already normalized, so recipes without graph unchanged.

`pin_label_last`: return steps unchanged if a label exists; if missing, append a label card (same as today append behavior) but **do not move it to the end**.

ivi seed `label.enabled=True`.

- [ ] **Step 4: Run**

```
py -3 scripts/test_platform_recipe_graph.py -v
py -3 scripts/test_platform_datatype_editor.py -v
```

working_directory: `hmi/backend`  
Expected: both suites PASS（editor 里 `test_pin_label_last` 已改名/改断言）

---

