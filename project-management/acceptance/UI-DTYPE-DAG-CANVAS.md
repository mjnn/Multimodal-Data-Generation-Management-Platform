# UI-DTYPE-DAG-CANVAS · 执行 DAG 画板 + 产物橱窗锁标签树 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 规格：`docs/superpowers/specs/2026-09-03-dtype-dag-canvas-design.md`  
> 计划：`docs/superpowers/plans/2026-09-03-dtype-dag-canvas.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-DTYPE-DAG-CANVAS · 执行 DAG 画板 + 本地按图执行 + `/w/:id` 橱窗锁死标签树 |
| 日期 | 2026-09-03 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` local + Playwright preview `:4175` |
| Agent 自动化摘要 | recipe_graph **24/24**；graph_runtime **8/8**；editor **26/26**；kernel **19/19**；`tsc -b` ok；Playwright editor **3/3 (13.3s)** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · recipe.graph 校验 / hydrate / 投影 / 表达式

**操作步骤**
1. working_directory `hmi/backend`：`py -3 scripts/test_platform_recipe_graph.py -v`

**期望结果**
- 无环、恰好一个打标器、if 必须 then+else 端口
- 禁止并行 join；允许 XOR 汇合到 label
- hydrate 不覆盖已有 graph；投影把 ASR 写入 preprocess
- 表达式白名单；拒绝 JS / 打标前 `labels.*`

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-03（Task 12）：`Ran 24 tests in 0.016s OK`

#### A-2 · 本地 graph runtime + Task 11 护栏

**操作步骤**
1. working_directory `hmi/backend`：`py -3 scripts/test_platform_graph_runtime.py -v`

**期望结果**
- if true/false 沿边执行；缺适配器报错
- `source.kind` if 允许本地跑
- **ASR/标签 if 本地仍 `RuntimeError`「本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支」，符合计划 Task 11 护栏**
- 无 graph 旧路径仍走 overlay + `plan_and_run`

**通过判断标准**
- 退出码 0
- `test_assert_blocks_asr_if` 断言文案与上列 RuntimeError 完全一致

**执行记录**
- 2026-09-03（Task 12）：`Ran 8 tests in 0.013s OK`（含 `test_assert_blocks_asr_if`）

#### A-3 · 既有 editor 套件

**操作步骤**
1. working_directory `hmi/backend`：`py -3 scripts/test_platform_datatype_editor.py -v`

**期望结果**
- 自定义 draft upsert、hydrate/compile、打标器不必钉死最后仍绿

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-03（Task 12）：`Ran 26 tests in 5.565s OK`

#### A-4 · 既有 kernel 套件

**操作步骤**
1. working_directory `hmi/backend`：`py -3 scripts/test_platform_datatype_kernel.py -v`

**期望结果**
- 种子配方仍通过 `validate_recipe`；未知 op / VL bbox 仍拒绝

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-03（Task 12）：`Ran 19 tests in 4.830s OK`

#### A-5 · 前端类型检查

**操作步骤**
1. 在 `hmi/frontend`：`cmd /c "npx.cmd tsc -b"`

**期望结果**
- 无错误

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-03（Task 12）：`tsc -b` **OK**

---

### A-E2E · Playwright

#### A-E2E-1 · 新建 DAG 画板 + if 节点（不保存残缺 if 图）+ 锁树 + draft 保存

| 脚本/Spec | `hmi/frontend/e2e/platform-dtype-editor.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cd hmi/frontend && cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

**期望结果**
- 新建页 `dag-canvas` 可见；`dag-cloud-hint` 含首句 `本地按图执行；上云只跑公共前缀。`
- `dag-node-label` 存在且无 `dag-remove-label`
- `overview-locked-labels_tree` 存在；`overview-remove-labels_tree` 为 0
- 保存 draft 成功后重新打开；再点 `palette-op-if`：`/dag-node-.*if/` 可见；`dag-cloud-lossy` 可见且文案 `图含 if 或打标后节点：上云不会执行这些分支。`
- **不保存**该无 then/else 的 if 图（否则 PUT `validate_graph` 失败）
- STFT 检查器仍可绑；`oms_cabin` 橱窗锁标签树 + 预设切换仍过

**通过判断标准**
- 3 passed

**执行记录**
- 2026-09-03（Task 12）：`3 passed (13.3s)` — 覆盖：画板 / 锁树 / 无删打标器 / hint 首句 / draft 保存；保存后再点 if（不保存）；lossy 黄警告

---

## 二、人工签字 / 主观（H · 可选）

本工单无 H。A + A-E2E 全绿即可 done。

---

## 三、不在本工单范围

- 不改 DataWorks / DPE / 不把 graph pickle 进 UDF
- 不 publish `audio_nvh-v2`
- 不抢跑 `UI-NVH-REVIEW-SAVE`
- 本地尚未拆分 `plan_and_run`：ASR/打标之后的 if 开跑仍 RuntimeError（Task 11 护栏，非本工单缺陷）

---

## 四、点测结论

- [x] A · 单元 / API / 构建 — done（24+8+26+19 + tsc）
- [x] A-E2E · Playwright editor 3/3 — done
- [x] H — 本工单无 H
- [x] 工单整体 — 可标 done
