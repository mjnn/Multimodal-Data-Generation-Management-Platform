# PLAT-DTYPE-LAKE · 源湖持久化复用 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 日期：2026-08-20  
> 环境前置：A 单测不需双端；A-E2E 需 HMI 后端 `:8000`（含 `GET /api/platform/sources`）+ Playwright preview

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-DTYPE-LAKE（gap：跨会话复用已入库 Source） |
| Agent 自动化摘要 | 源本就落 SQLite+磁盘；补 list API + UI 多选；单测 6/6；e2e 2/2 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · list_sources + 复用组 Sample

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_lake.py -v`

**期望结果**
- `put_source` 持久化；`list_sources` 返回历史源；`create_sample` 可引用已有 `source_id`

**通过判断标准**
- unittest 全绿

**执行记录**
- 2026-08-20：`6/6` 通过（含 `test_list_sources_returns_persisted_across_calls`）

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b`

**期望结果**
- `/lake` 多选表 + `listPlatformSources` 无 TS 错误

**通过判断标准**
- exit code 0

**执行记录**
- 2026-08-20：通过

### A-E2E · Playwright

#### A-E2E-1 · 入湖预检 + 刷新后复用

| 脚本/Spec | `hmi/frontend/e2e/platform-lake.spec.ts` |

**操作步骤**
1. 后端 `HMI_DATA_SOURCE=local` 监听 `127.0.0.1:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/platform-lake.spec.ts`

**期望结果**
- 上传 text → 组 Sample → ivi 预检失败提示
- 上传唯一文件名 → reload → 表中仍可见 → 勾选组 Sample

**通过判断标准**
- Playwright 2/2 通过

**执行记录**
- 2026-08-20：`2 passed`

## 二、人工签字 / 主观（H）

| 编号 | 摘要 |
|------|------|
| H-0 | 无。以 A + A-E2E 为准。 |

## 三、不在本工单范围

- 勿 publish taxonomy / `audio_nvh-v2`
- 勿改 DataWorks / AI-label 无关文件

## 四、点测结论

- [x] A / A-E2E — 可标 done（本 gap 闭合）
