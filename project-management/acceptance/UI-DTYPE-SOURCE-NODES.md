# UI-DTYPE-SOURCE-NODES · 数据源节点 + 开跑分源 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 规格：`docs/superpowers/specs/2026-09-02-datatype-source-nodes-design.md`  
> 问卷：S1 删槽位表；S2 源节点 + 一源多文件；S3 `manual_map` 分块勾选；S4 `label_only` 显示名

| 字段 | 内容 |
|------|------|
| 工单 | UI-DTYPE-SOURCE-NODES · 源槽位改为编排数据源卡 + 开跑分源勾选 |
| 日期 | 2026-09-02 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` local + Playwright preview `:4175` |
| Agent 自动化摘要 | 切片 A：editor **23/23**；kernel **19/19**；e2e editor **3/3**。切片 B：bind **9/9**；`tsc -b` ok。Task 8（2026-09-02）Playwright：**7 passed (48.2s)** = editor **3/3** + lake **4/4** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · hydrate / compile 数据源卡 + 校验（切片 A）

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

**期望结果**
- 自定义 draft upsert 仍可用
- `oms_cabin` hydrate 以数据源卡开头（slot → `card_kind=source`）
- 槽位 title 去重；`output_labels` 未知 port 被拒（不进算子 params schema）
- 绑定只允许上方节点；`parse_bag` 画面产出为连续帧

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02（切片 A）：`Ran 18 tests in 5.409s OK`
- 2026-09-02（切片 B 回归）：`Ran 23 tests in 5.565s OK`
- 2026-09-02（Task 5 切片 A 复验）：`Ran 23 tests in 4.704s OK`

#### A-2 · 内核配方回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py`

**期望结果**
- 种子配方仍通过 `validate_recipe`；未知 op / VL bbox 仍拒绝

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02（切片 A）：`Ran 15 tests in 4.850s OK`
- 2026-09-02（切片 B 回归）：`Ran 19 tests in 5.031s OK`
- 2026-09-02（Task 5 切片 A 复验）：`Ran 19 tests in 3.733s OK`

#### A-3 · 开跑 assignments（切片 B）

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py`

**期望结果**
- `oms_cabin`（多 slot）裸 `source_ids` → `ValueError` 含 `assignments`
- `audio_array_spec` / `ivi_ui_stub` 单 slot 仍可用裸 `source_ids`
- 显式 `assignments` 把 wav 映射到 `audio_primary`
- 错 kind、同一 `source_id` 分给两个 slot 被拒
- 既有采集批 / eligible_for / lineage 仍绿

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02：`Ran 9 tests in 6.037s OK`

#### A-4 · 前端类型检查

**操作步骤**
1. 在 `hmi/frontend`：`cmd /c "npx.cmd tsc -b --pretty false"`

**期望结果**
- 无错误

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02（切片 B）：`tsc -b` **OK**

---

### A-E2E · Playwright

#### A-E2E-1 · 编辑器无源槽位表单；数据源卡（切片 A）

| 脚本/Spec | `hmi/frontend/e2e/platform-dtype-editor.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cd hmi/frontend && cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

**期望结果**
- 新建页可见 `pipeline-orchestrator`；没有独立「源槽位」表单
- `pipe-add-source` 在数据源卡内追加输入行（`pipe-source-row`），不是新卡
- 编辑 `oms_cabin`：一张 `pipe-source-card`、四行；解析器「连续帧」；ASR / 编码器绑上游产物

**通过判断标准**
- 3 passed

**执行记录**
- 2026-09-02（切片 A）：`3 passed (13.4s)`
- 2026-09-02（切片 B 回归）：`3 passed`（含在 7 passed / 51.2s 中）
- 2026-09-02（Task 5 切片 A 复验）：`3 passed (13.6s)` — 覆盖：无「源槽位」标题；`pipe-add-source`→`pipe-source-row` 增而 `pipe-source-card`=1；oms_cabin card=1 / row=4（rosbag）；解析「连续帧」；ASR「ROSBAG 解析器 · .wav」；编码器「ROSBAG 解析器 · 连续帧」
- 2026-09-02（Task 8 切片 B 收工）：`3 passed`（含在 **7 passed / 48.2s** 中）

#### A-E2E-2 · 开跑按数据源分块勾选（切片 B）

| 脚本/Spec | `hmi/frontend/e2e/platform-lake.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cd hmi/frontend && cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts e2e/platform-lake.spec.ts"`

**期望结果**
- 入湖 `.wav` → `/pipeline?tab=run` → 选 `audio_array_spec` → 在 `lake-run-slot-audio_primary` 勾选该行 → 预检通过、创建运行可点
- 入湖 `.txt` → 选 `ivi_ui_stub` → `lake-run-slot-ui_media` 不出现该文本文件
- 源湖列表 / OSS 浏览 tab 仍过

**通过判断标准**
- lake 4 passed；与 editor 合计 7 passed

**执行记录**
- 2026-09-02：`7 passed (51.2s)`（editor 3 + lake 4）
- 2026-09-02（Task 8）：`7 passed (48.2s)` — editor 3 + lake 4；wav→`audio_array_spec`→`lake-run-slot-audio_primary` 预检通过；`.txt` 不出现在 `lake-run-slot-ui_media`

---

## 二、人工签字 / 主观（H · 可选）

本工单无 H。A + A-E2E 全绿即可 done。

---

## 三、不在本工单范围

- 不改 DataWorks / `local_sdk_worker` 阶段顺序
- 不 publish `audio_nvh-v2`
- 无自由拖线画布
- 产物自定义名只是显示名（S4 `label_only`）；绑定/缓存仍用 `frames` / `.wav`

---

## 四、点测结论

- [x] 切片 A · A + A-E2E — done
- [x] 切片 B · A + A-E2E — done
- [x] 工单整体 — 可标 done
