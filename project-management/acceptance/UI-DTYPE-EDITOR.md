# UI-DTYPE-EDITOR · 新建 / 编辑 DataType 配方表单 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-DTYPE-EDITOR · 槽位 / 预处理 / 产物 / 管线能力表单 |
| 日期 | 2026-08-20 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` + Playwright preview |
| Agent 自动化摘要 | `test_platform_datatype_editor.py` **2/2**；`tsc -b` 通过；`platform-dtype-editor.spec.ts` **2/2** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 自定义配方 upsert + 未知算子拒绝

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_editor.py -v`

**期望结果**
- 可写入含 slots / preprocess / products / stages / bbox 的 draft
- 未知 `op_id` 抛 `ValueError`

**通过判断标准**
- 退出码 0；2 tests ok

**执行记录**
- 2026-08-20：`Ran 2 tests … OK`

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b`

**期望结果**
- 无错误

**执行记录**
- 2026-08-20：通过

---

### A-E2E · Playwright

#### A-E2E-1 · 管理员新建 draft 配方

**操作步骤**
1. 后端 `HMI_DATA_SOURCE=local` 监听 `127.0.0.1:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/platform-dtype-editor.spec.ts`

**期望结果**
- 首页「新建数据类型」→ 填 id/title/purpose → 加预处理 → 保存 → 列表出现 draft 卡片
- 「编辑」oms_cabin：id 只读且值为 `oms_cabin`

**通过判断标准**
- 2 passed

**执行记录**
- 2026-08-20：`2 passed (10.3s)`

---

## 二、人工签字

| H-0 | 无。以 A + A-E2E 为准。 |

---

## 三、交付物

| 路径 | 说明 |
|------|------|
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | 配方编辑器 |
| `hmi/frontend/src/pages/DataTypeHomePage.tsx` | 新建 / 编辑入口 |
| `hmi/frontend/src/App.tsx` | `/data-types/new` · `/data-types/:id/edit`（admin） |
| `PUT /api/platform/data-types/{id}` | 既有；前端 `api.putDataType` |
| `GET /api/platform/operators` | 算子 + 视图目录 |

**约束**：勿 publish `audio_nvh-v2` 标签树；新算子仍须发版注册，表单只组合已有能力。
