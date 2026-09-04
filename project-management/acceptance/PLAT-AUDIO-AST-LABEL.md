# PLAT-AUDIO-AST-LABEL · AudioSet AST 填 L6 category/sources 验收

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-AUDIO-AST-LABEL · YuanGongND AST + 现有 `pytorch_model.bin` 映射 AudioSet top-k → `nvh.sem.noise_category` / `noise_sources` |
| 日期 | 2026-08-21 |
| 环境前置 | API / Web / E2E 需双端：否 |
| Agent 自动化摘要 | `test_nvh_ast_label.py` **7/7**；相关 NVH 测试全绿；HF 权重 remap `strict_load OK`（155/155）；合成 PCM 可出 527 维 sigmoid；**未 publish** `audio_nvh-v2` |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · AudioSet 527 名与映射

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_ast_label.py -v` → `TestAudiosetNvhMap`

**期望结果**
- index 0=`Speech`，343=`Engine`
- Engine/Idling 映射 `category=engine`、`sources` 含 `engine`；Dog 不参与 category
- 仅 Dog 时 `mapped=false`、`noise_category=None`

**通过判断标准**
- 3 用例 OK

**执行记录**
- 通过（2026-08-21）

#### A-2 · HF → Gong qkv remap

**操作步骤**
1. 同脚本 `test_concat_qkv_and_rename`

**期望结果**
- q/k/v concat dim0 → `v.blocks.0.attn.qkv.weight` shape (24,8)；`classifier.dense` → `mlp_head.1.weight`

**通过判断标准**
- 用例 OK

**执行记录**
- 通过（2026-08-21）

#### A-3 · fill 只覆盖 category/sources，等级仍 heuristic

**操作步骤**
1. `test_ast_overrides_category_keeps_heuristic_grade` + `test_missing_infer_falls_back_heuristic` + `test_recipe_uses_ast_model`

**期望结果**
- mock Engine → `noise_category=engine`；`quality_grade=C`（heuristic）；clip 键不变；hypothesis 含 `Engine=`
- infer 返回 None → `ai_mode=heuristic_fallback`
- seed `audio_array_spec.stages.label.model=nvh_sem_ast`

**通过判断标准**
- 3 用例 OK

**执行记录**
- 通过（2026-08-21）

#### A-4 · 既有 NVH 回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_ai_label.py -v`
2. `py -3 hmi/backend/scripts/test_nvh_deriver.py -v`
3. `py -3 hmi/backend/scripts/test_audio_array_spec.py -v`

**期望结果**
- 分别为 5/5、3/3、3/3

**执行记录**
- 通过（2026-08-21）

#### A-5 · 真实权重可 strict load

**操作步骤**
1. 将 `pytorch_model.bin` 放到 `hmi/data/models/ast/`（gitignore）
2. remap + `ASTModel.load_state_dict(..., strict=True)`

**期望结果**
- missing=0 unexpected=0

**执行记录**
- 通过：`model_keys 155 remapped 155`；`strict_load OK`（2026-08-21）

---

### A-E2E · Playwright / Selenium

本工单无 UI 改动，无 A-E2E。

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 真实 HEAD 阵列开跑看 hypothesis

重启后端后对 `audio_array_spec` 开跑一条 HEAD `.dat`，Clip 标签中 `nvh.sem.ai_hypothesis` 应含 `ast:nvh_sem_ast top5:` 与分数；`quality_grade` 仍像 heuristic。缺 `torchaudio` 或权重时回退 heuristic。

---

## 三、不在本工单范围

- publish `audio_nvh-v2`
- DataWorks / MC
- AST 微调
- 用 AST 填 `quality_grade` / spec / annoyance
- 打开 embed 阶段
- 把 330MB 权重复制进 git

---

## 四、点测结论

- [x] A 全绿；无 A-E2E；H-1 可选
- 可标 done（权重需本机 `hmi/data/models/ast/pytorch_model.bin` 或 `HMI_NVH_AST_WEIGHTS`）
