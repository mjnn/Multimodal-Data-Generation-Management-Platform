# DataType 数据源节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]` / `- [x]`) syntax for tracking.

**Goal:** 把 DataType 编辑器的「源槽位」改成编排列表里的数据源节点；算子输入选上方数据源或上游产物（产物可设显示名）；开跑按数据源分块勾选入湖文件。

**Architecture:** 编辑器 `steps[]` 混放 `card_kind=source|op`。视觉上顶部一张数据源容器卡，卡内多行 = 多个逻辑源。Compile 把每一行写成现有 `recipe.slots`，算子卡仍写 `preprocess`/`stages`/`bbox`；`output_labels` 与 `params` 并列挂在 preprocess 步上，worker 忽略。开跑 `assignments: [{slot_id, source_ids}]` 替代「按后缀一篮子多选」。

**Tech Stack:** FastAPI `hmi/backend/hmi/platform/`；React 编辑器 `DataTypeEditorPage` + `PipelineOrchestrator`；开跑 `LakeRunBindPanel`；单测 `hmi/backend/scripts/test_platform_datatype_*.py`；Playwright `hmi/frontend/e2e/`。Windows 前端命令必须 `npx.cmd` / `cmd /c`，禁止直接 `npm`。

**Spec:** `docs/superpowers/specs/2026-09-02-datatype-source-nodes-design.md`（已审通过）

## Working-tree status（2026-09-02）

本工作区 **Tasks 1–8 实现与验收已落地**（editor 23/23、kernel 19/19、bind 9/9、e2e editor 3/3 + lake 4/4）。下方步骤勾选反映现状。从干净分支重做时把 `[x]` 改回 `[ ]` 再按 TDD 执行。Git commit 步骤仍为 `[ ]`，除非用户明确要求提交。

## Global Constraints

- 不改 DataWorks、不改 `local_sdk_worker` 阶段顺序、不 publish `audio_nvh-v2`
- 源 kind 仍是入湖后缀；`parse_bag` 画面产物仍是 `frames`（连续帧），不是 `.mp4`
- 产物自定义名只是显示名；绑定/缓存/port id 仍用 `frames` / `.wav`
- 列表从上到下；只能绑更上方的数据源或产物
- 切片 A 编辑器可独立验收；切片 B 开跑分源勾选依赖 A 的 slots 语义
- 不要 commit，除非用户在该会话明确要求
- 收工回写 CURRENT / tracking.csv（UTF-8 BOM）/ progress-board / changelog / `acceptance/UI-DTYPE-SOURCE-NODES.md`（A / A-E2E 分节）

## File map

| 文件 | 职责 |
|------|------|
| `hmi/backend/hmi/platform/recipe.py` | `output_labels` 校验；source title 不进 DB 时可放 `slots[].title` |
| `hmi/backend/hmi/platform/recipe_pipeline.py` | hydrate 槽位→数据源卡；compile 源卡→slots；向上绑定校验 |
| `hmi/backend/hmi/platform/run_bind.py` + `store.py` | `assignments` |
| `hmi/backend/hmi/platform/router.py` | POST `/runs` 收 assignments |
| `hmi/frontend/src/api/types.ts` | `PipelineStep.card_kind`、`output_labels`、`DataTypeSlot.title` |
| `hmi/frontend/src/utils/recipePipeline.ts` | 与后端 hydrate/compile 镜像 |
| `hmi/frontend/src/components/datatype/PipelineSourceCard.tsx` | 数据源卡 UI（新建，避免把 StepCard 撑爆） |
| `hmi/frontend/src/components/datatype/PipelineOrchestrator.tsx` | 添加数据源；混排两种卡 |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | 删除源槽位 Form.List |
| `hmi/frontend/src/components/pipeline/LakeRunBindPanel.tsx` | 按 slot 分块勾选 |
| `hmi/backend/scripts/test_platform_datatype_editor.py` | 切片 A |
| `hmi/backend/scripts/test_platform_lake_run_bind.py` | 切片 B |
| `hmi/frontend/e2e/platform-dtype-editor.spec.ts` | A-E2E |
| `hmi/frontend/e2e/platform-lake.spec.ts` | B-E2E |

---

### Task 1: slots.title + preprocess.output_labels 校验

**Files:**
- Modify: `hmi/backend/hmi/platform/recipe.py`（`validate_recipe` 槽位循环与 preprocess 循环）
- Test: `hmi/backend/scripts/test_platform_datatype_editor.py`

**Interfaces:**
- Consumes: 现有 `validate_recipe(recipe: dict) -> dict`
- Produces: 每个 slot 可有 `title: str`（默认 = id）；preprocess 步可有 `output_labels: dict[str, str]`，key 必须属于该步 `produces`（若 produces 空则属于算子默认产出）

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run test to verify it fails**

Run: `py -3 hmi/backend/scripts/test_platform_datatype_editor.py TestDataTypeEditorUpsert.test_slot_title_and_output_labels_roundtrip`

Expected: `AttributeError` 或 `KeyError` / `unknown params` / title 被丢掉（FAIL）

- [x] **Step 3: Write minimal implementation**

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

- [x] **Step 4: Run tests**

Run: `py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

Expected: 原 12 个 + 新测试全绿

- [ ] **Step 5: Commit**（仅当用户要求）

```bash
git add hmi/backend/hmi/platform/recipe.py hmi/backend/scripts/test_platform_datatype_editor.py
git commit -m "feat(platform): allow slot.title and preprocess.output_labels"
```

---

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

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run tests — expect FAIL**（`slots_from_steps` / `new_source_card` 未定义）

- [x] **Step 3: Implement**

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

- [x] **Step 4: Run** `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` — 全绿

- [ ] **Step 5: Commit**（仅当用户要求）

---

### Task 3: 前端类型 + recipePipeline 镜像

**Files:**
- Modify: `hmi/frontend/src/api/types.ts`
- Modify: `hmi/frontend/src/utils/recipePipeline.ts`
- Test: 无独立 jest；用 `npx.cmd tsc -b`

**Interfaces:**
- `PipelineStep` 增加：`card_kind?: 'source' | 'op'`；`title?: string`；`kinds?: string[]`；`cardinality_min?: number`；`cardinality_max?: number`；`output_labels?: Record<string, string>`
- `DataTypeSlot` 增加 `title?: string`
- `DataTypePreprocessStep` 增加 `output_labels?: Record<string, string>`
- 镜像：`isSourceCard`、`newSourceCard`、`slotsFromSteps`、`hydrateRecipeToSteps` 前置 source 卡、`compileSteps` 返回 `slots`、`typeLabel(t, labels?)` 优先 `labels[t]`

- [x] **Step 1:** 改 `types.ts`（先改类型，tsc 可能仍过，因为字段可选）

- [x] **Step 2:** `recipePipeline.ts` 实现与 Task 2 同名逻辑；`bindingOptions` 把 `upstream` 里的 source 卡当成槽位，label = `title`；算子产物 label = `${op.title} · ${step.output_labels?.[name] || typeLabel(name)}`

- [x] **Step 3:** `cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"` — 退出码 0

- [ ] **Step 4: Commit**（仅当用户要求）

---

### Task 4: 编辑器 UI — 去掉槽位表，数据源容器卡 + 卡内行

**Files:**
- Create: `hmi/frontend/src/components/datatype/PipelineSourceCard.tsx`
- Modify: `PipelineOrchestrator.tsx`、`PipelineStepCard.tsx`、`DataTypeEditorPage.tsx`

**Interfaces:**
- 编排列表 **顶部固定一张** 数据源容器卡（`data-testid="pipe-source-card"`）。逻辑源是卡内行 `data-testid="pipe-source-row"`，每行编译为一个 slot。
- 「添加数据源」按钮在 **卡内**（`data-testid="pipe-add-source"`），调用 `newSourceCard` 追加一行，**不要**再长出第二张 source 卡。
- `oms_cabin` hydrate：1 张卡、4 行（rosbag / video / image / audio），不是 4 张卡。
- `PipelineOrchestrator` **删除 `slots` prop**；从 `steps` 推导 source 行。
- `DataTypeEditorPage`：删除「源槽位」Card / `Form.List`；`buildRecipe` 用 `compileSteps(steps)` 的 `slots` + preprocess，不再读 `values.slots`
- `EditorForm` 去掉 `slots`
- 算子卡产出芯片：显示 `output_labels[t] || typeLabel(t)`；chip 旁可改显示名（写入 `output_labels`，不进 `params`）

每行最小字段：title、kinds（多选 catalog suffixes）、min/max、required。

删行时清掉 `bindings.kind==='slot' && slot_id===gone`。

- [x] **Step 1:** 实现容器卡 + 卡内行 + Orchestrator；算子卡仍按 `card_kind=op` 渲染

- [x] **Step 2:** 拆掉 Editor 槽位表单；保存走 compile 出的 slots

- [x] **Step 3:** `cmd /c "npx.cmd tsc -b --pretty false"` 于 `hmi/frontend`

- [ ] **Step 4: Commit**（仅当用户要求）

---

### Task 5: 切片 A 验收（单测 + Playwright）

**Files:**
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`
- Modify: `hmi/backend/scripts/test_platform_datatype_editor.py`（若 Task 2 已覆盖 hydrate，本任务只补 e2e）

- [x] **Step 1:** 更新 e2e

  - 新建页：`getByTestId('pipeline-orchestrator')` 可见；**没有**「源槽位（绑定可入湖 kinds）」标题；`pipe-add-source` 追加 `pipe-source-row`（`pipe-source-card` 仍为 1）
  - STFT 用例：默认源 kinds=`.mp4` →「无兼容输入」
  - `oms_cabin`：`pipe-source-card` count=1、`pipe-source-row` count=4（含 `rosbag`）；解析器芯片「连续帧」；ASR「ROSBAG 解析器 · .wav」；编码器「ROSBAG 解析器 · 连续帧」

- [x] **Step 2:** 后端 `:8000` local 已起时：

```powershell
cd hmi/frontend
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
```

Expected: 3 passed（若新增用例则全绿）

- [x] **Step 3:** `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` 与 `test_platform_datatype_kernel.py`

- [x] **Step 4:** 写 `project-management/acceptance/UI-DTYPE-SOURCE-NODES.md` 的 **A / A-E2E**（切片 B 在 Task 8 补全）

- [ ] **Step 5: Commit**（仅当用户要求）

---

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

### Task 7: 开跑 UI 分块勾选

**Files:**
- Modify: `hmi/frontend/src/components/pipeline/LakeRunBindPanel.tsx`
- Modify: `hmi/frontend/src/api/index.ts` + `types.ts`（`createPlatformRun` 增加 `assignments?`）

每个 `recipe.slots` 一块 `data-testid="lake-run-slot-{id}"`：标题 `slot.title || slot.id`，副文案 kinds 与基数。块内表格只列出 kind 合格源。勾选写入 `Record<slotId, sourceId[]>`。预检/开跑 POST `assignments`。

去掉「整表一个 checkbox 再自动分槽」作为主路径。

- [x] **Step 1:** 改面板

- [x] **Step 2:** `tsc -b`

- [ ] **Step 3: Commit**（仅当用户要求）

---

### Task 8: 切片 B Playwright + 收工文档

**Files:**
- Modify: `hmi/frontend/e2e/platform-lake.spec.ts`
- Modify: `project-management/CURRENT.md`、`changelog-progress.md`、`progress-board.md`、`tracking.csv`、`acceptance/UI-DTYPE-SOURCE-NODES.md`

- [x] **Step 1:** lake-run 用例：入湖 wav → `/pipeline?tab=run` → 选 `audio_array_spec` → 在 `lake-run-slot-audio_primary`（id 以种子为准）勾选该行 → 预检通过。`ivi_ui_stub` 文本源仍不出现在视频/图块里。

- [x] **Step 2:**

```powershell
cd hmi/frontend
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts e2e/platform-lake.spec.ts"
```

Expected: 全绿

- [x] **Step 3:** 回写进度四件套 + acceptance（A 含 editor/kernel；A-E2E 含 editor + lake）。聊天附结果表。推荐下一工单恢复 **UI-NVH-REVIEW-SAVE**（除非产品继续插队）。

- [ ] **Step 4: Commit**（仅当用户要求）

---

## Spec coverage（自检）

| Spec 节 | 任务 |
|---------|------|
| S1 删除槽位表 | T4 |
| S2 数据源节点 + 一源多文件 | T2 T4（卡内多行仍多 slot） |
| S3 开跑分块勾选 | T6 T7 T8 |
| S4 显示名 | T1 T3 T4 |
| S5 编译 slots | T2 |
| S6 只绑上方 | T2 `assert_upward_bindings` |
| S7 切片 A/B | T5 / T8 |
| 单 slot 兼容 source_ids | T6 |
| 旧配方 hydrate | T2 |
| worker 不读 output_labels | T1 并列字段 |
| 不改 DataWorks | 全局约束 |

无 TBD。`audio_primary` 等 slot id 实现时以 `seed_recipes()` 为准，测试里不要写死猜错的 id。
