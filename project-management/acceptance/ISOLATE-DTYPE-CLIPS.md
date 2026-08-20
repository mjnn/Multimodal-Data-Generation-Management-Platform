# ISOLATE-DTYPE-CLIPS · OMS 总览隔离非 OMS 类型 clip · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | ISOLATE-DTYPE-CLIPS · OMS overview 不泄露 `audio_array_spec` / `ivi_ui_stub` |
| 日期 | 2026-08-20 |
| 环境前置 | 本地 `HMI_DATA_SOURCE=local`；A 不需双端 |
| Agent 自动化摘要 | 根因：`oms_cabin` 走未过滤 `list_clips_light()`；已按 `pipeline_execution.data_type_id` 隔离；A 5/5 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 双向隔离（OMS ↔ audio / IVI）

**操作步骤**
1. `py -3 hmi/backend/scripts/test_audio_nvh_view.py -v`

**期望结果**
- `list_clips_light` / `list_clips_light_for_data_type('oms_cabin')`：**不含** `audio_array_spec`、`ivi_ui_stub` active 执行的 clip；**含** legacy（`data_type_id` NULL）与显式 `oms_cabin`
- `list_clips_light_for_data_type('audio_array_spec')` 仍只含麦克风阵列 clip

**通过判断标准**
- unittest 全绿（含 `test_oms_excludes_audio_and_ivi`）

**执行记录**
- 通过（2026-08-20）：`5/5`

---

### A-E2E · Playwright / Selenium

本工单无新增 A-E2E（列表过滤为 API 层；前端 cache key 已含 `dataTypeId`，并 bump `hmi-overview-cache-v3`）。

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · UI 目视（可选）

进入 `/w/audio_array_spec` 确认麦克风阵列 clip 可见 → 切 `/w/oms_cabin` 总览不再出现同批阵列 clip。硬刷新一次即可（v3 缓存）。

---

## 三、不在本工单范围

- DataWorks / 云端 clip 列表
- 语义写回 UI-NVH-REVIEW-SAVE
- publish `audio_nvh-v2`

---

## 四、点测结论

- [x] A 全绿 — 可标 done
- [ ] H-1 可选
