# PLAT-DTYPE-LAKE 验收

## A · 单元 / API / 构建（已执行）

| 编号 | 结果 | 操作步骤 | 期望结果 | 通过判断标准 | 执行记录 |
|------|------|----------|----------|--------------|----------|
| A-1 | 通过 | 运行 `py -3 hmi/backend/scripts/test_platform_datatype_lake.py -v` | 源湖 persist-only、`platform_run` 编译、image fail、`y_json` 最小回写均通过 | unittest 全绿 | `5/5` 通过（初版）；2026-08-20 复用 gap 后 `6/6` 见 `PLAT-DTYPE-LAKE-REUSE.md` |
| A-2 | 通过 | 运行 `py -3 hmi/backend/scripts/test_platform_datatype_run.py -v` | RUN 阶段回归不退化 | 回归脚本全绿 | 通过 |
| A-3 | 通过 | 运行 `node node_modules/typescript/bin/tsc -b`（`hmi/frontend`） | `/lake` 页面与路由接线无 TS 错误 | `tsc` exit code = 0 | 通过 |

## A-E2E · Playwright / Selenium（已执行）

| 编号 | 结果 | 操作步骤 | 期望结果 | 通过判断标准 | 执行记录 |
|------|------|----------|----------|--------------|----------|
| A-E2E-1 | 通过 | 运行 `node node_modules/@playwright/test/cli.js test e2e/platform-lake.spec.ts` | 登录后进入 `/lake`，text 入湖、组 Sample、选择 `ivi_ui_stub` 触发预检失败提示 | Playwright 用例通过 | 初版 `1/1`；2026-08-20 含刷新复用 `2/2`（`PLAT-DTYPE-LAKE-REUSE.md`） |

## H · 人工签字（若有）

| 编号 | 摘要 |
|------|------|
| H-0 | 无。本工单出口以 A + A-E2E 为准。 |

## 后续 gap（已闭合）

- **跨会话复用**：后端本就持久化；缺 `GET /api/platform/sources` + UI 多选 → 见 `acceptance/PLAT-DTYPE-LAKE-REUSE.md`（2026-08-20）。
