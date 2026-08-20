# PLAT-DTYPE-KERNEL · 平台数据类型内核第一切片 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-DTYPE-KERNEL · 源湖 + 配方 + OMS/IVI 工作区 |
| 日期 | 2026-08-18 |
| 环境前置 | 单元测试不需双端；A-E2E 需 HMI 后端 8000 + Playwright preview |
| Agent 自动化摘要 | `test_platform_datatype_kernel.py` 15/15；前端 `tsc -b` 通过 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 配方校验 / 预检 / 双类型 Run / 缓存键 / 工作区隔离

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py -v`

**期望结果**
- 缺 taxonomy / 未知算子 / 未知视图 / `vl` 检测器被拒
- 仅文本开 `oms_cabin` 预检失败；仅图片开 `ivi_ui_stub` 通过
- 同一 Sample 两条 Run、两棵树、y 不覆盖
- Product 第二次 lookup `skipped=True`
- 未知 `data_type_id` → 404；缺省回落到 `oms_cabin`（兼容旧 `/api/clips`）

**通过判断标准**
- 15 tests OK

**执行记录**
- 2026-08-18：`Ran 15 tests … OK`

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b`

**期望结果**
- 退出码 0

**执行记录**
- 2026-08-18：通过

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · 数据类型列表进入 OMS / IVI 工作区

| 脚本/Spec | `hmi/frontend/e2e/datatype-workspace.spec.ts` |

**操作步骤**
1. 后端监听 `127.0.0.1:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/datatype-workspace.spec.ts`

**期望结果**
- `/` 出现舱内 OMS 与车机 UI 卡片
- 进入 IVI 工作区 banner 含「车机 UI」且 URL 含 `ivi_ui_stub`
- 进入 OMS 工作区 banner 含「舱内 OMS」

**通过判断标准**
- spec 通过

**执行记录**
- 2026-08-18：见收工记录（依赖本地 8000 与 preview）

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 工作区手感

**操作步骤**
1. 登录 HMI，从数据类型列表分别进入 OMS 与 IVI
2. OMS 总览应仍能列出既有 clip；IVI 总览应为空列表而非混入 OMS 标签

**期望结果**
- 换类型等于换频道

**通过判断标准**
- 人确认两频道不混标签

**执行记录**
- 2026-08-18：用户确认 H-1 已测完（本地 HMI，OMS=/w/oms_cabin，IVI=/w/ivi_ui_stub）

---

## 三、不在本工单范围

- 完整车机 UI 业务与专用检测模型
- DataWorks / MC `data_type_id` 列
- 新预处理算子（CAN/LIN 解析器）
- VL bbox
