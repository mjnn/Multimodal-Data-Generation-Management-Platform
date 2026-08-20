# PLAT-AUDIO-AI-LABEL · audio_array_spec L6 语义 AI 打标（draft 绑定）验收

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-AUDIO-AI-LABEL · deriver 后填 `nvh.sem.*`；绑定 draft `audio_nvh-v2`；不 publish |
| 日期 | 2026-08-20 |
| 环境前置 | API / Web / E2E 需双端：否 |
| Agent 自动化摘要 | `nvh_ai_label` + recipe `stages.label`；unittest 5/5 + deriver 3/3；**未 publish**；OMS published 仍为 `label_tree_baseline` |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · merge 只写语义、不覆盖客观

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_ai_label.py -v` → `test_merge_fills_sem_keeps_objective`

**期望结果**
- `nvh.sem.*` 写入；试图 patch `nvh.clip.*` 被忽略；非法 key 不进入

**通过判断标准**
- 该用例 OK

**执行记录**
- 通过（2026-08-20）

#### A-2 · heuristic 填 L6 且不 clobber clip/ch

**操作步骤**
1. 同脚本 `test_heuristic_writes_sem_keys` + `test_end_to_end_derive_then_ai`

**期望结果**
- deriver 后无 `nvh.sem.*`；AI 后有 `noise_category` / `ai_hypothesis` 等
- 所有 `nvh.clip.*` / `nvh.ch.*` 与 deriver 输出相等
- `_meta.ai_mode=heuristic`，`taxonomy_version_code=audio_nvh-v2`

**通过判断标准**
- 两用例 OK

**执行记录**
- 通过（2026-08-20）

#### A-3 · 配方开启 label；draft 绑定；不 publish

**操作步骤**
1. `test_recipe_label_enabled` + `test_resolve_draft_taxonomy_no_publish`
2. 本机 `app.db`：`audio_nvh-v2` status=draft、78 nodes；`get_published_version` ≠ audio_nvh-v2

**期望结果**
- `audio_array_spec.stages.label.enabled=true`，model=`nvh_sem_heuristic`
- `taxonomy_version_code=audio_nvh-v2`
- resolve 返回 draft UUID；published 仍为 OMS baseline

**通过判断标准**
- 用例 OK + DB 抽查一致

**执行记录**
- 通过；published=`label_tree_baseline`；v2 draft 78 叶

#### A-4 · deriver 回归仍绿

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_deriver.py -v`

**期望结果**
- 3/3（含 CBK1 样例）；deriver 本身仍不写 human 语义（AI 在下游）

**执行记录**
- `3/3` 通过（2026-08-20）

#### A-5 · 全 AI 脚本绿

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_ai_label.py -v`

**期望结果**
- 5/5 OK

**执行记录**
- `5/5` 通过（约 2.8s）

---

### A-E2E · Playwright / Selenium

本工单无前端改动（Taxonomy Hub 已能列 draft；管线仍走 DataType 开跑），无新增 A-E2E。

---

## 二、H · 人工签字

| 编号 | 摘要 |
|------|------|
| H-0 | 无。勿做 H-2；勿在 Taxonomy Hub **发布** `audio_nvh-v2`。 |

---

## 实现摘要

| 项 | 路径 / 行为 |
|----|-------------|
| 语义 AI | `hmi/backend/hmi/local/nvh_ai_label.py` |
| 模型 | 默认 `nvh_sem_heuristic`；可选 `nvh_sem_vl`（DashScope + mel.png，无 key 回退 heuristic） |
| 配方 | `audio_array_spec.stages.label.enabled=true` |
| Worker | `_run_audio_array_spec`：deriver → fill_nvh_semantic → facts；`taxonomy_version_id`=draft v2 |
| 禁止 | `publish_version(audio_nvh-v2)` |

## 用户如何触发

1. Taxonomy Hub 可见草稿 **`audio_nvh-v2`（78 叶）** — 不要点「发布」
2. 数据类型选 **麦克风阵列频谱**（`audio_array_spec`）上传 HEAD `.dat` / 阵列包并开跑
3. 跑完后 `labels_json` / `nvh_labels.json` 含客观叶 + `nvh.sem.*`；事实表绑定 draft taxonomy UUID
4. 若要用 VL：把配方/库内 `stages.label.model` 改为 `nvh_sem_vl` 并配置 `DASHSCOPE_API_KEY`（可选 `HMI_NVH_VL_MODEL`）
