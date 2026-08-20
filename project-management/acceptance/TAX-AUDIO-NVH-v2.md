# TAX-AUDIO-NVH-v2 · 声压/噪音真值标签体系（全量）验收

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | TAX-AUDIO-NVH-v2 · HEAD 四通道声压/噪音真值 taxonomy 全量 78 叶 |
| 日期 | 2026-08-20 |
| 环境前置 | API / Web / E2E 需双端：否 |
| Agent 自动化摘要 | YAML 78 节点 + draft `audio_nvh-v2` seed；**未发布**（避免归档 OMS published） |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 节点规格与 YAML 导入形状

**操作步骤**
1. 运行 `py -3 hmi/backend/scripts/test_audio_nvh_v2.py -v`

**期望结果**
- 78 个唯一 `nvh.*` 叶节点；分层 8/10/6/8/12/8/6/10/10
- `shared/config/audio_nvh_taxonomy.yaml` 的 `version=audio_nvh-v2` 且 `label_count=78` 可被 `parse_taxonomy_yaml` 导入

**通过判断标准**
- unittest 全绿

**执行记录**
- `3/3` 通过（2026-08-20）

#### A-2 · 平台 seed 写入 draft（不发布）

**操作步骤**
1. 临时 `APP_DB` 上 `ensure_schema()`
2. 查询 `label_taxonomy_version` / `count_nodes`

**期望结果**
- `audio_nvh-v1` 仍为 3 个 domain 占位 draft
- `audio_nvh-v2` 为 **draft**，78 节点
- 不调用 `publish_version`，不归档 OMS published

**通过判断标准**
- `test_seed_inserts_v2_draft` 通过

**执行记录**
- 通过

#### A-3 · 内核回归

**操作步骤**
1. 运行 `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py -q`

**期望结果**
- `audio_array_spec` 仍绑定 `taxonomy_id=audio_nvh`；label/embed 仍关闭

**通过判断标准**
- 脚本 exit 0

**执行记录**
- 通过（2026-08-20）

---

### A-E2E · Playwright / Selenium

本工单无 UI 改动，无 A-E2E。

---

## 二、H · 人工签字

| 编号 | 摘要 |
|------|------|
| H-0 | 无。出口以 A 为准。 |

---

## 拍板记录（相对设计评审）

| 项 | 选择 |
|----|------|
| 范围 | 全量 v2（78 叶），非 lite |
| 声压分档 | 固定 70 / 85 / 100 dB |
| 语义树 | 13 顶类 + powertrain 子类 |
| json_ref | 相对 `runs/{run_id}/` |
| VL | 首版不启用；`nvh.sem.ai_hypothesis` 预留 semi |
