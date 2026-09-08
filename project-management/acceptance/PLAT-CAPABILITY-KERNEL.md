# PLAT-CAPABILITY-KERNEL · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-CAPABILITY-KERNEL · DAG 逐节点 capability（slice-2 阵列 + slice-3 `text_to_json`） |
| 日期 | 2026-09-07 |
| 环境前置 | 本切片无 UI；不需双端 |
| Agent 自动化摘要 | kernel 10/10；graph_runtime 9/9；progress_steps 9/9；catalog_ops 9/9 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 阵列种子图走 kernel 本地插件

**操作步骤**
1. `py -3 hmi/backend/scripts/test_capability_kernel.py`

**期望结果**
- `test_audio_array_seed_graph_runs_on_kernel` 写出 `pcm_pa.npy`、`audio_spec/VL/{mel,stft,third_octave,spl}`、`nvh_labels.json`

**通过判断标准**
- 退出码 0

**执行记录**（Agent 收工填）
- 2026-09-04：slice-2 `Ran 5 tests in 1.886s` OK
- 2026-09-07：slice-3 并入后 `Ran 10 tests in 1.781s` OK

#### A-2 · 既有 kernel / runtime 回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_graph_runtime.py`
2. `py -3 hmi/backend/scripts/test_platform_progress_steps.py`
3. `py -3 hmi/backend/scripts/test_platform_catalog_ops.py`

**期望结果**
- graph_runtime 9/9；progress_steps 9/9；catalog_ops 9/9

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-04：graph_runtime + progress_steps 均 OK
- 2026-09-07：三套均 OK

#### A-3 · `text_to_json` 本地插件

**操作步骤**
1. `py -3 hmi/backend/scripts/test_capability_kernel.py`

**期望结果**
- `generic_json` 从 manifest 读出 `ctx.structured_json` 并写 `structured.json`
- `generic_text` 包一层 `{"raw": ...}`
- 非法 JSON / 未知 `schema_id` 失败（非空成功）
- 下游 `json_extract` 能读 `structured_json`
- 未登记 local 插件仍报 `capability 未实现`

**通过判断标准**
- 上述用例通过；退出码 0

**执行记录**
- 2026-09-07：`test_text_to_json_*` + `test_unimplemented_local_capability_fails` OK

### A-E2E · Playwright / Selenium

本工单无 UI 改动（`schema_id` 检查器已有；阵列编辑器 DAG 已在 UI-DTYPE-DAG-CANVAS 覆盖）。

---

## 二、人工签字 / 主观（H · 可选）

无。

---

## 三、不在本工单范围

- DataWorks / DPE
- publish `audio_nvh-v2`
- 宣称 IVI 业务打标已完成（IVI 配方仍是抽帧 + bbox + label）

---

## 四、点测结论

- [x] A 全绿；无 A-E2E / 无 H — 工单 **done**
