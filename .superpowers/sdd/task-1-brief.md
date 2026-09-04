### Task 1: slots.title + preprocess.output_labels 校验

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe.py`（`validate_recipe` 槽位循环与 preprocess 循环）
- Test: `hmi/backend/scripts/test_platform_datatype_editor.py`

**Interfaces:**
- Consumes: 现有 `validate_recipe(recipe: dict) -> dict`
- Produces: 每个 slot 可有 `title: str`（默认 = id）；preprocess 步可有 `output_labels: dict[str, str]`，key 必须属于该步 `produces`（若 produces 空则属于算子默认产出）

- [ ] **Step 1: Write the failing test**

在 `test_platform_datatype_editor.py` 增加：

```python
    def test_slot_title_and_output_labels_roundtrip(self) -> None:
        from hmi.platform.recipe import validate_recipe
        from hmi.platform.recipe import SEED_RECIPES

        rec = dict(SEED_RECIPES["oms_cabin"])
        rec = validate_recipe(rec)
        rec["slots"][0]["title"] = "舱内 bag"
        rec["preprocess"][0]["output_labels"] = {"frames": "舱内连续帧"}
        rec["preprocess"][0]["produces"] = ["frames", ".wav", ".json"]
        out = validate_recipe(rec)
        self.assertEqual(out["slots"][0]["title"], "舱内 bag")
        self.assertEqual(out["preprocess"][0]["output_labels"]["frames"], "舱内连续帧")

    def test_output_labels_unknown_port_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["preprocess"][0]["output_labels"] = {"not_a_port": "x"}
        rec["preprocess"][0]["produces"] = ["frames", ".wav", ".json"]
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(rec)
        self.assertIn("output_labels", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 hmi/backend/scripts/test_platform_datatype_editor.py TestDataTypeEditorUpsert.test_slot_title_and_output_labels_roundtrip`

Expected: `AttributeError` 或 `KeyError` / `unknown params` / title 被丢掉（FAIL）

- [ ] **Step 3: Write minimal implementation**

在 `recipe.py` 规范化 slot 时保留 title：

```python
title = str(slot.get("title") or slot_id).strip() or slot_id
norm_slots.append({..., "title": title, ...})
```

同配方 `title` 大小写不敏感去重：撞车 `raise ValueError("duplicate slot title")`。

在 preprocess 循环、写出 `entry` 之后：

```python
labels = step.get("output_labels")
if labels is not None:
    if not isinstance(labels, dict):
        raise ValueError(f"preprocess {op_id}.output_labels must be an object")
    allowed = set(entry.get("produces") or [])
    clean: dict[str, str] = {}
    for pk, pv in labels.items():
        port = str(pk).strip()
        if allowed and port not in allowed:
            raise ValueError(f"output_labels unknown port={port!r}")
        name = str(pv).strip()
        if name:
            clean[port] = name
    if clean:
        entry["output_labels"] = clean
```

不要把 `output_labels` 放进 `params`（`param_keys_for_op` 会拒未知 key）。

- [ ] **Step 4: Run tests**

Run: `py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

Expected: 原 12 个 + 新测试全绿

- [ ] **Step 5: Commit**（仅当用户要求）

```bash
git add hmi/backend/hmi/platform/recipe.py hmi/backend/scripts/test_platform_datatype_editor.py
git commit -m "feat(platform): allow slot.title and preprocess.output_labels"
```

---

