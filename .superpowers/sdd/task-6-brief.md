### Task 6: 开跑 assignments API

**Files:**
- Modify: `hmi/backend/hmi/platform/store.py` `create_run_from_sources`
- Modify: `hmi/backend/hmi/platform/run_bind.py`（抽出 `validate_assignments`）
- Modify: `hmi/backend/hmi/platform/router.py` POST `/runs`
- Test: `hmi/backend/scripts/test_platform_lake_run_bind.py`

**Interfaces:**

```python
def validate_source_assignments(
    recipe: dict[str, Any],
    assignments: list[dict[str, Any]],
    *,
    source_kind_by_id: dict[str, str],
) -> list[str]:
    """Return flattened source_ids. Raise ValueError with a Chinese or English message listing the slot title."""
```

规则（照 spec §5）：required slot 必须出现；kind ∈ slot.kinds；min/max；同一 source_id 不能两个 slot。

`create_run_from_sources(source_ids, data_type_id, assignments=None)`：

- `assignments` 非空：用 validate 结果当 ids，预检用各文件 kind 列表
- `assignments` 空：若 `len(recipe["slots"])==1`，把 `source_ids` 当成该 slot 的 assignment；否则 `raise ValueError("assignments required")`

Router body 增加可选 `assignments`。

- [x] **Step 1: Failing tests**

```python
    def test_assignments_required_for_multi_slot(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source
        bag = put_source(content=b"x", kind="rosbag", filename="a.bag")
        with self.assertRaises(ValueError) as ctx:
            create_run_from_sources([bag["source_id"]], "oms_cabin")
        self.assertIn("assignments", str(ctx.exception).lower())

    def test_single_slot_source_ids_still_works(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source
        wav = put_source(content=b"audio-bytes", kind="audio", filename="a.wav")
        run = create_run_from_sources([wav["source_id"]], "audio_array_spec")
        self.assertTrue(run["run_id"])

    def test_assignments_maps_wav_to_audio_slot(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source
        wav = put_source(content=b"audio-bytes", kind="audio", filename="b.wav")
        run = create_run_from_sources(
            [],
            "audio_array_spec",
            assignments=[{"slot_id": "audio_primary", "source_ids": [wav["source_id"]]}],
        )
        self.assertEqual(run["source_ids"], [wav["source_id"]])
```

（`audio_array_spec` 的 slot id 以种子为准，实现前 grep `SEED_RECIPES["audio_array_spec"]["slots"][0]["id"]`。）

- [x] **Step 2:** 跑测 FAIL

- [x] **Step 3:** 实现 validate + store + router

- [x] **Step 4:** `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py` 全绿；kernel / editor 回归

- [ ] **Step 5: Commit**（仅当用户要求）

---

