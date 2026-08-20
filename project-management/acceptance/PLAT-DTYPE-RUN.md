# PLAT-DTYPE-RUN · 管线开跑接到 DataType 预检 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-DTYPE-RUN · 选 published 类型 → 预检 → 入队现有 SDK |
| 日期 | 2026-08-18 |
| 环境前置 | A 不需双端；A-E2E 需 HMI 后端 8000 + Playwright preview |
| Agent 自动化摘要 | `test_platform_datatype_run.py` 8/8；kernel 15/15 回归；前端 `tsc -b` 通过 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 预检拒绝 / 配方叠加 / 双类型 y 不覆盖

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_run.py -v`
2. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py -v`

**期望结果**
- 无 `data_type_id`、仅文本开 `oms_cabin`、仅 bag 开 `ivi_ui_stub` → 预检失败且带 `missing`
- `.bag` + `oms_cabin`、`.mp4` + `ivi_ui_stub` → 预检通过
- IVI overlay：`need_label=False` 且强制 `bbox_enabled` + `opencv`
- OMS overlay：bbox 仍跟全局设置；label/embed 开启
- 同一 Sample 两条 Run（OMS / IVI）y 互不覆盖

**通过判断标准**
- run 脚本 8 tests OK；kernel 15 tests OK

**执行记录**
- 2026-08-18：`Ran 8 tests … OK`；`Ran 15 tests … OK`

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b`

**期望结果**
- 退出码 0

**执行记录**
- 2026-08-18：通过

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · 管线上传页必须选择数据类型

| 脚本/Spec | `hmi/frontend/e2e/pipeline-datatype-run.spec.ts` |

**操作步骤**
1. 后端监听 `127.0.0.1:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/pipeline-datatype-run.spec.ts`

**期望结果**
- `/pipeline?tab=upload` 出现「开跑数据类型」
- 下拉含舱内 OMS 与车机 UI

**通过判断标准**
- spec 通过

**执行记录**
- 2026-08-18：`1 passed`（`e2e/pipeline-datatype-run.spec.ts`；顺带修正 `e2e/helpers/auth.ts` 登录框 placeholder 为「用户名」）

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · IVI 开跑不混入 OMS 打标

**操作步骤**
1. 管线管理选 `ivi_ui_stub`，暂存一个视频（不要 bag）
2. 确认执行参数里打标显示「关闭（配方）」、BBox 强制
3. 入队后队列行带 `ivi_ui_stub`；不要用同一 run 去 OMS 工作区找 IVI 标签

**期望结果**
- 预检通过才入队；IVI 不调用 Omni 打标

**通过判断标准**
- 产品负责人签字
