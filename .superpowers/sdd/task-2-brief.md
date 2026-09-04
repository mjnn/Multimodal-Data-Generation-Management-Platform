### Task 2: hydrate 槽位为数据源卡；compile 源卡回 slots

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe_pipeline.py`
- Test: `hmi/backend/scripts/test_platform_datatype_editor.py`

**Interfaces:**
- Consumes: `hydrate_recipe_to_steps(recipe) -> list[dict]`；`compile_steps(steps, slots=None) -> dict`
- Produces:
  - `is_source_card(card) -> bool`：`card.get("card_kind") == "source"` 或 `card.get("op_id") == "source"`
  - `new_source_card(*, key, title, kinds, cardinality_min=1, cardinality_max=1, required=True) -> dict`
  - `slots_from_steps(steps) -> list[dict]`：source 卡 → `{id: key, title, kinds, cardinality_*, required, role: "input"}`
  - hydrate：先把 `recipe.slots` 编成 source 卡（顺序与 slots 一致）插在 **算子卡之前**
  - compile：忽略传入的旧 `slots` 参数若 steps 含 source 卡，改用 `slots_from_steps`；返回值增加 `"slots"` 与 `"require_any_kinds"`（required 源的 kinds 各组）
  - `assert_upward_bindings(steps)`：`bindings.slot_id` / `step_key` 必须是当前卡下标之前的 `key`

Source 卡形状：

```python
{
    "key": "rosbag",
    "card_kind": "source",
    "op_id": "source",
    "title": "舱内 bag",
    "kinds": [".bag"],
    "cardinality_min": 1,
    "cardinality_max": 8,
    "required": False,
    "produces": [".bag"],  # 供 type_compatible：用 kinds
    "bindings": {},
}
```

- [ ] **Step 1: Write the failing test**

```python
    def test_hydrate_oms_cabin_starts_with_source_cards(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps, slots_from_steps

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        steps = hydrate_recipe_to_steps(rec)
        sources = [s for s in steps if s.get("card_kind") == "source"]
        self.assertEqual([s["key"] for s in sources], ["rosbag", "video", "image", "audio"])
        self.assertTrue(any(s.get("op_id") == "parse_bag" for s in steps))
        self.assertLess(steps.index(sources[0]), next(i for i, s in enumerate(steps) if s.get("op_id") == "parse_bag"))

        compiled = compile_steps(steps)
        self.assertEqual([s["id"] for s in compiled["slots"]], ["rosbag", "video", "image", "audio"])
        self.assertEqual(slots_from_steps(steps)[0]["id"], "rosbag")

    def test_binding_to_later_source_rejected(self) -> None:
        from hmi.platform.recipe_pipeline import assert_upward_bindings, new_source_card, new_step_from_op

        src = new_source_card(key="bag", title="bag", kinds=[".bag"])
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=[], upstream=[])
        parse["bindings"] = {"in": {"kind": "slot", "slot_id": "bag"}}
        with self.assertRaises(ValueError):
            assert_upward_bindings([parse, src])
        assert_upward_bindings([src, parse])  # ok
```

- [ ] **Step 2: Run tests — expect FAIL**（`slots_from_steps` / `new_source_card` 未定义）

- [ ] **Step 3: Implement**

`hydrate_recipe_to_steps`：开头

```python
source_cards = []
for slot in recipe.get("slots") or []:
    sid = str(slot.get("id") or "").strip()
    kinds = list(slot.get("kinds") or [])
    source_cards.append({
        "key": sid,
        "card_kind": "source",
        "op_id": "source",
        "title": str(slot.get("title") or sid),
        "kinds": kinds,
        "cardinality_min": int(slot.get("cardinality_min") or 1),
        "cardinality_max": int(slot.get("cardinality_max") or 1),
        "required": bool(slot.get("required", True)),
        "produces": list(kinds),
        "bindings": {},
    })
# 然后现有 preprocess 循环；return source_cards + steps
```

hydrate preprocess 时把 `raw.get("output_labels")` 拷到卡上。

`compile_steps`：跳过 `is_source_card`；从 steps 抽出 slots；preprocess entry 带上 `card.get("output_labels")`。

`binding_options`：source 卡当作 slot，`label` 用 `title`；upstream 算子 label 用 `output_labels.get(name) or name`（后端测试可不依赖中文）。

`assert_upward_bindings` 在 `compile_steps` 开头调用。

- [ ] **Step 4: Run** `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` — 全绿

- [ ] **Step 5: Commit**（仅当用户要求）

---

