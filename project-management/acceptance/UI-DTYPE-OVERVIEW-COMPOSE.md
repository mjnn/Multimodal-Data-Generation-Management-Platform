# UI-DTYPE-OVERVIEW-COMPOSE · 总览视图组件拼版 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-DTYPE-OVERVIEW-COMPOSE · 列表 + 详情有序组件卡 |
| 日期 | 2026-09-02 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` + Playwright preview |
| Agent 自动化摘要 | kernel **19/19**；editor **23/23**；`tsc -b` 通过；editor e2e **3/3** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 配方 hydrate / 拒存未知 widget

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py`

**期望结果**
- 种子 `oms_cabin` / `audio_array_spec` / `ivi_ui_stub` GET 规范化后带 `overview.list` / `overview.detail`
- 未知 `widget_id` 拒存
- 把详情 widget 放进 `list` 拒存
- 显式 `overview` 不被预设覆盖

**通过判断标准**
- 退出码 0；含 overview 相关用例

**执行记录**
- 2026-09-02 Agent：`Ran 19 tests in 3.860s` **OK**

#### A-2 · 编辑器 upsert 回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

**期望结果**
- 既有 upsert / 多选绑定 / parse_bag 连续帧用例仍绿

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02 Agent：`Ran 23 tests in 4.927s` **OK**

#### A-3 · 前端类型检查

**操作步骤**
1. 在 `hmi/frontend`：`npx.cmd tsc -b`

**期望结果**
- 无错误

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02 Agent：`tsc -b` **OK**

---

### A-E2E · Playwright

#### A-E2E-1 · 编辑器两套拼版 + 预设填入

| 脚本/Spec | `hmi/frontend/e2e/platform-dtype-editor.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`（PowerShell 禁止直接 `npx`）

**期望结果**
- 新建页可见 `overview-composer`
- 打开 `oms_cabin`：详情有 `overview-card-cabin_multicam`，列表有 `clip_table`，无声压列卡
- 切预设「四通道频谱时间轴」后出现 `nvh_spl_column` / `nvh_spectrum`，舱内时间轴卡消失
- 既有管线卡 / 多选绑定用例仍过

**通过判断标准**
- 3 passed

**执行记录**
- 2026-09-02 Agent：`3 passed (14.3s)` **OK**

---

## 二、人工签字 / 主观（H · 可选）

本工单无 H。运行时总览/Explorer 按卡渲染已接到配方；未单开 Playwright 点进 Clip（沿用 bootstrap 兜底）。

---

## 三、不在本工单范围

- 自由画布 / 网格 span
- DataWorks / worker 阶段顺序
- publish `audio_nvh-v2`
- UI-NVH-REVIEW-SAVE
- 源节点开跑手工分配（拍板：按数据源名称勾选文件；未做）

---

## 四、点测结论

- [x] A + A-E2E — 可标 done
