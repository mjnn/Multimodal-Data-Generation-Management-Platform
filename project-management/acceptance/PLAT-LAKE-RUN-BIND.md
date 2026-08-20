# PLAT-LAKE-RUN-BIND · 开跑选类型筛源多选自动 Sample · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 日期：2026-08-20  
> 环境前置：A 单测不需双端；A-E2E 需 HMI 后端 `:8000` + Playwright

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-LAKE-RUN-BIND |
| Agent 自动化摘要 | 配方 slots；`eligible_for` 筛源；`POST /runs` 接受 `source_ids` 自动 Sample；湖页去掉主路径「组 Sample」；采集批分组展示 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · slots + create_run_from_sources + eligible_for

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py -v`

**期望结果**
- 种子配方含 slots/products；`list_sources(eligible_for=)` 按 kind 过滤；`create_run_from_sources` 产出 sample+run

**通过判断标准**
- unittest 全绿（含 lineage 用例同文件）

**执行记录**
- 2026-08-20：`5/5` 通过

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b`

**期望结果**
- Lake 开跑 UX / API 类型无 TS 错误

**通过判断标准**
- exit code 0

**执行记录**
- 2026-08-20：通过

### A-E2E · Playwright

#### A-E2E-1 · 入湖 → 选类型 → 多选 → 预检可开跑

| 脚本/Spec | `hmi/frontend/e2e/platform-lake.spec.ts` |

**操作步骤**
1. 后端 `HMI_DATA_SOURCE=local` 监听 `127.0.0.1:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/platform-lake.spec.ts`

**期望结果**
- 刷新后源仍在且带采集批标签
- 选 `audio_array_spec` → 勾选合格源 → 预检通过 →「创建运行」可点
- `ivi_ui_stub` 过滤掉 text 源

**通过判断标准**
- Playwright `3 passed`

**执行记录**
- 2026-08-20：`3 passed`（WAV 上传须唯一内容避免 content-hash 去重）

## 二、人工签字 / 主观（H）

| 编号 | 摘要 |
|------|------|
| H-0 | 无。以 A + A-E2E 为准。 |

## 三、不在本工单范围

- UI-DTYPE-EDITOR；血缘图 UI；publish `audio_nvh-v2`；DataWorks

## 四、点测结论

- [x] A / A-E2E — 可标 done
