# OP-DERIVE-NVH · L2 → labels_json / y_json 客观真值推导验收

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | OP-DERIVE-NVH · `derive_nvh_labels` 从 audio_array_spec L2 写客观 NVH 标签 |
| 日期 | 2026-08-20 |
| 环境前置 | API / Web / E2E 需双端：否 |
| Agent 自动化摘要 | deriver 模块 + worker hook；unittest 3/3；**未 publish** `audio_nvh-v2`；VL label stage 仍关 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 合成 PCM 推导覆盖 auto/semi，不伪造 human

**操作步骤**
1. 运行 `py -3 hmi/backend/scripts/test_nvh_deriver.py -v`

**期望结果**
- 合成四通道 ~94.5 dB Leq：`nvh.clip.spl.leq_db_mean` 在 90–98；`level_class=high`
- 全部 `derivation=auto` 叶有值；semi 种子（`level_class` / `channel_balance_grade` / `tonal_components`）有值
- human / 无种子 semi（含 `nvh.sem.*`、`record_context`、`masking_band`、`ai_hypothesis`）**不出现**在 labels
- `_meta.taxonomy_version_code=audio_nvh-v2`，含 `deriver_version` / `derived_at`
- json_ref `_ref` 相对 run root（`audio_spec/...`）

**通过判断标准**
- `test_synthetic_auto_semi_not_human` 通过

**执行记录**
- 通过（2026-08-20）

#### A-2 · CBK1 用户样例 Leq≈94–95（样例存在时）

**操作步骤**
1. 同脚本 `test_user_sample_leq_range`（样例路径见脚本；缺失则 skip）

**期望结果**
- `nvh.clip.spl.leq_db_mean` ∈ [93, 96]
- 不写入语义 human 字段

**通过判断标准**
- 样例存在时 assert 通过；缺失时 skip 不算失败

**执行记录**
- 通过（样例存在，Leq 落入区间）

#### A-3 · 配方仍关闭 VL label stage

**操作步骤**
1. `test_label_stage_still_off`

**期望结果**
- `audio_array_spec.stages.label.enabled == false`

**通过判断标准**
- 通过

**执行记录**
- 通过

#### A-4 · 全脚本绿

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_deriver.py -v`

**期望结果**
- 3/3 OK

**执行记录**
- `3/3` 通过（2026-08-20，约 5.8s）

---

### A-E2E · Playwright / Selenium

本工单无 UI 改动（并行 UI-NVH-OVERVIEW 不冲突），无 A-E2E。

---

## 二、H · 人工签字

| 编号 | 摘要 |
|------|------|
| H-0 | 无。出口以 A 为准。勿做 HMI 在线 H-2。 |

---

## 实现摘要

| 项 | 路径 / 行为 |
|----|-------------|
| deriver | `hmi/backend/hmi/local/nvh_deriver.py` → `derive_nvh_labels` |
| hook | `local_sdk_worker._run_audio_array_spec`：L2 后写 `nvh_labels.json`；镜像成功后 `fact_clip_label` + `platform_run.y_json` |
| 派生索引 | `audio_spec/derived/*`、`third_octave_matrix.json` |
| 测试 | `hmi/backend/scripts/test_nvh_deriver.py` |
