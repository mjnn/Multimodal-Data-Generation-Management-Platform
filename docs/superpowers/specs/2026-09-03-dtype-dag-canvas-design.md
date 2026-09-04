# Design: DataType 执行 DAG 画板 + 产物橱窗

> 日期：2026-09-03  
> 状态：**已审通过**（2026-09-03 会话「继续」= 批准 spec；实现计划另开）  
> 工单：**UI-DTYPE-DAG-CANVAS**（切片 A 配方图 / B 画板 / C 橱窗锁树 / D 本地图执行 / E 上云压扁警告）  
> 前置：`UI-DTYPE-SOURCE-NODES`、`UI-DTYPE-OVERVIEW-COMPOSE`  
> 插入：排在 **UI-NVH-REVIEW-SAVE** 之前  
> 不抢跑：不 publish `audio_nvh-v2`；不改 DataWorks 节点代码与 Job 顺序

本文件吸收 2026-09-03 会话六节设计。实现计划：`docs/superpowers/plans/2026-09-03-dtype-dag-canvas.md`。

取代 `2026-09-02-datatype-source-nodes-design.md` 的 **S8**（打标器钉死列表最后）。线性列表在 DAG 编辑器落地后删除 `pinLabelLast` 的「必须最后」约束。

---

## 1. 背景与目标

### 1.1 问题

编排仍是纵向卡片列表，依赖靠「排在上面」。总览拼版是展示布局，不是执行图。用户要的是 Coze / LangGraph / Airflow 那种：**选组件、连线、带 if/else**；工作空间要像总览拼版那样 **统计并展示最终产物**，其中 **标签树必出且必展示**。

今日本地 worker 用配方 overlay 后整包 `plan_and_run`（阵列音频走专用路径），读不到图，也无法按条件 skip 节点。

### 1.2 目标

1. DataType 编辑器中间改为 **DAG 画板**（组件栏 + 画布 + 检查器）。
2. 本地 worker **按图执行**；DataWorks 仍走现有线性 Job。
3. 逻辑节点为 **通用 if/else**（字段比较，含打标后的标签/信心度）。
4. `/w/:id` **就是产物橱窗**：沿用 `overview.list` / `overview.detail`；详情 **锁死标签树**。
5. 打标器 **必经、唯一，但不是图的终点**；后面可接校核、导出、再 if。

### 1.3 非目标

- 并行两路都跑再 join（ASR∥抽帧再 merge）
- 任意 JS / 正则 / 嵌套 OR 树 / 跨 clip 聚合
- 把四宫格、频谱、标签树画成 DAG 节点（方案 C）
- DataWorks / DPE / MaxFrame 按图调度；MC 不加 graph 列
- 重写 OMS SDK 内部 UDF
- UI-NVH-REVIEW-SAVE（L6 人工写回）
- 自由网格拼版；新图表引擎
- publish `audio_nvh-v2`

---

## 2. 已拍板决策

| ID | 决策点 | 选择 |
|----|--------|------|
| D1 | 画板保真度 | **真执行 DAG**：if/else 改变本地 worker 跑法 |
| D2 | 运行时范围 | **先只改本地 worker**；上云仍线性 Job |
| D3 | 逻辑原语 | **通用 if/else 表达式**（源/ASR/标签/信心度），不是只图形化 `when_kind` |
| D4 | 产物页 | **`/w/:id` = 橱窗**；布局 = 现有总览拼版；不新开产物页 |
| D5 | 条件求值 | **打标后可再接节点**；if 可以看标签。打标器不再钉死最后 |
| D6 | 方案 | **B**：本地图执行器 + 上云压扁公共前缀 |
| D7 | 汇合 | **禁止并行 join**；**允许互斥汇合**（if 两出边连同一下游，运行时只走一路） |
| D8 | 表达式 | 白名单字段 + 一层 `all`（AND）；检查器下拉，不写脚本 |
| D9 | 权威存储 | `recipe.graph` 为编辑器与本地执行权威；线性字段 **由图投影**，禁止只改 `preprocess` 反写图 |
| D10 | publish 带分支 | **允许 publish**；编辑器黄警告「上云只跑公共前缀」 |
| D11 | 画布库 | 前端 **`@xyflow/react`**（React Flow） |
| D12 | 工单顺序 | 本工单插入 **UI-NVH-REVIEW-SAVE** 之前 |

---

## 3. 两页分工

### 3.1 编辑器 = 执行 DAG

路径仍是 `/data-types/new`、`/data-types/:id`。替换 `PipelineOrchestrator` 纵向列表为：

- 左：组件栏（数据源 / 阶段 / if-else / 打标器 / 校核 / 导出）
- 中：可平移缩放的画布
- 右：选中节点检查器（参数、条件、绑定）

橱窗拼版区（`overview.list` / `detail`）留在同一页，**不要**画进 DAG。

### 3.2 工作空间 = 产物橱窗

`/w/:id` 列表 + Clip 详情（含校核媒体区）仍按 `recipe.overview` 有序卡渲染。不跑图、不解释 if。格子绑定图上 **已发布产物 id**。

### 3.3 衔接

打标器固定产出 `labels_tree`。其它 `op` 产物在编辑器里均可绑到橱窗。`export` **可选**：用于打标后把「本分支对外登记」写入 run 元数据；没有 `export` 时不另做发布过滤。运行时若该节点没被走到，格子走空态，不因此拒绑。

---

## 4. 节点、边、图约束

### 4.1 节点 `type`

| type | op_id | 说明 |
|------|-------|------|
| `source` | `source` | 一个逻辑源 = 一个 `slots[]` 项（与现源行 1:1） |
| `op` | 现有算子 id | 抽帧、ASR、解析、bbox、NVH、embed 等 |
| `if` | — | 一入两出：`then` / `else`；`condition` 挂在节点上 |
| `label` | `label` | **有且仅有一个**；不可删除 |
| `review` | — | 仅打标后；不调 SDK；该 clip 写 `review_status=pending_review` |
| `export` | — | 仅打标后、可选；把本分支产物 id 写入 run 元数据 |

没有适配器的 `op_id` 禁止投放（组件栏不展示）。

### 4.2 打标器

1. 配方必须有且仅有一个 `label` 节点。
2. 从每个 **必选** `source` 出发，都存在一条有向路径经过该打标器。
3. 开跑勾选了某可选源时，该源也必须能走到打标器，否则该次 run 失败。
4. 打标器可以有后继（`review` / `export` / `if`）。
5. `review` / `export` 不得出现在打标器之前（沿边倒推不可达打标器）。

### 4.3 if/else

- 入端口 1 个，出端口名固定 `then`、`else`。
- 运行时只激活一条出边；`else` 未连线 = 该侧什么都不做。
- 禁止两路都执行再 merge。
- 允许 `then` 与 `else` 都连到同一节点（互斥汇合，尤其是共用打标器）。

示例：

```text
源 ──► ASR ──► if ──then──► 抽帧 ──┐
                 └──else──────────┴──► 打标器 ──► 校核
                                      └──► if(标签) ──then──► 导出A
                                                     └──else──► 导出B
```

### 4.4 边

```text
edge = { id, source, source_port, target, target_port }
```

数据边：上游产物 port → 下游输入。if 出边额外表示控制流。禁止环。绑定改为「沿边可达」，不再要求列表下标更小。

### 4.5 旧配方 hydrate

无 `graph` 时，按现有卡片顺序生成 **一条链**（源 → preprocess ops → embed（若开）→ label），补默认 `position`。只在编辑器打开时于内存生成；用户保存后才落 `graph`。未打开的 DataType 不自动改库。

**`ivi_ui_stub`：** 今日 `stages.label.enabled=false`。切片 A 起种子改为 **带打标器且 `label.enabled=true`**（占位 taxonomy，不宣称 IVI 业务打标完成）。与「标签树必出」对齐。后端启动覆盖种子后需重启才能看到。

---

## 5. 表达式与本地执行

### 5.1 求值时机

if 被走到时才求值。`condition` 引用的字段必须能由 **已执行上游** 提供；保存时按字段目录 × 上游产物校验，缺依赖拒存。

- 打标前：`source.*`、解析产物、ASR。
- 打标后：另允许 `labels.*`、`label.avg_confidence`。

字段缺失（没跑 ASR、标签无该 key）→ 条件为假 → 走 `else`。不因此失败整次 run。

### 5.2 形状

一层 AND，无嵌套 OR：

```json
{
  "all": [
    { "field": "source.kind", "op": "in", "value": ["rosbag", "video"] },
    { "field": "asr.avg_confidence", "op": "gte", "value": 0.6 }
  ]
}
```

`all` 为空或缺省视为永真（走 `then`）。检查器只下拉字段与算子。

| 项 | v1 白名单 |
|----|-----------|
| 字段 | `source.kind`、`source.slot_id`、`asr.avg_confidence`、`asr.has_text`、`label.avg_confidence`、`labels.<点路径>` |
| 算子 | `eq` `neq` `gt` `gte` `lt` `lte` `in` `not_in` `exists` `not_exists` |

`labels.<点路径>` 相对该 clip 的 `labels_json` 对象；实现时用已有 JSON 取值，禁止 `eval`。

### 5.3 调度（本地 `graph_runtime`）

新模块（建议 `hmi/platform/graph_runtime.py`），仅 `data_source=local` 的 worker 调用。

1. 从 `source` 节点开始，**只沿将执行的边** 前进。
2. if 求值后只激活 `then` 或 `else`。
3. 互斥汇合：下游在第一条到达的入边上执行。
4. 未走到的节点不跑、不写产物。
5. 打标器必须被走到，否则 run 失败（保存校验本应拦住必选源）。

每个完成的节点把产物写入本次 run 的 context，供后续 if 与橱窗空态判断。`pipeline_run` 步骤按节点 `key` 记 `running` / `success` / `skipped`。

无 `graph` 的配方：**不走解释器**，行为与今日 overlay + `plan_and_run`（或阵列专用路径）等价。

### 5.4 适配器

解释器按 `op_id` 调 **已有** 本地能力，不重写 SDK 内核。

- 今日舱内整包 `plan_and_run`：图上连续的 OMS 能力可仍一次调用，但 **if 插在 ASR 与打标之间** 时必须拆开（先 ASR 写 context，再求值，再决定是否打标/bbox/embed）。
- 映射不到适配器的节点：组件栏不提供；若旧数据出现则 run 失败并写明缺少适配器。
- **校核**：路径上有 `review` 则该 clip 的 `review_status=pending_review`（与现有校核队列同一字段）；run 状态仍走现有 `labeled` / `completed`。无 `review` 节点则不在本工单改校核字段（保持今日写入）。
- **导出**：可选登记；文件仍由上游节点写出。`labels_tree` 无需导出节点。

不在 v1 把 DataWorks Job 拆成图。

---

## 6. `recipe.graph` 与线性投影

### 6.1 图形状

```text
recipe.graph = {
  nodes: [
    { key, type, op_id?, title, params, position: {x, y}, condition? }
  ],
  edges: [
    { id, source, source_port, target, target_port }
  ]
}
```

`position` 仅画布使用。节点 `key` 稳定；橱窗与算子绑定仍可用 `slot` / `upstream.step_key`。

`validate_recipe`：无 `graph` 仍合法。有 `graph` 则校验第 4 节全部图约束 + 第 5.2 节条件字段。

### 6.2 投影（保存时由图写出，供云与旧 API）

| 线性字段 | 规则 |
|----------|------|
| `slots` | 全部 `source` 节点 |
| `preprocess` | 打标前、且 **两条 if 边都会走到** 的 `op`（公共前缀）；`when_kind` 仅当能从源 kinds 唯一推出时填写 |
| `stages.label.enabled` | 有 `label` 节点 → true |
| `stages.embed.enabled` | embed 在公共前缀上（不在单一 if 死支） |
| `bbox.enabled` | `detect_bbox` 在公共前缀上 |

**公共前缀** = 从源到打标器之间、不经过 if 分流即可到达的节点。只在 `then` 或只在 `else` 上的 op **不进入** `preprocess`。

### 6.3 上云压扁

DataWorks 只读投影后的线性字段。丢失：整段 if/else、打标后校核/导出、仅单侧分支上的 ASR/bbox 等。

编辑器在保存区固定文案：**本地按图执行；上云只跑公共前缀。** 图含 if 或打标后节点时黄警告；**不阻止** draft 保存与 publish（D10）。

禁止：把图 pickle 进 DPE；双写两套可独立编辑的编排。

---

## 7. 产物橱窗

沿用 `2026-09-02-overview-compose-design.md` 的 `overview.list` / `detail` 有序卡。v1 仍上下叠卡，不做自由网格。

### 7.1 产物 id

| 产物 id | 默认来自 | 橱窗 |
|---------|----------|------|
| `labels_tree` | `label` 节点（固定产出） | **必绑、必展示** |
| `asr_jsonl` | ASR | 可选 |
| `frames` / `preview_mp4` | 抽帧 / 预览 | 可选 |
| `mel_matrix` / `spl_jsonl` | NVH | 可选 |
| `bboxes_jsonl` | bbox | 可选 |

if 导致本次 run 未走到对应节点：该格空态「本次未产出」，页面不崩。

### 7.2 锁死标签树

- widget_id：`labels_tree`（`surface=detail`，`needs=labels_tree`）。可从现有 `json_tree` 专化，但 **id 必须是 `labels_tree`**，以便锁死逻辑识别。
- `overview.detail` **永远**含这一张卡：不能删、不能换 widget、不能解绑。排序可改；**默认插在详情区最前**。
- 列表不强制再放一棵树；`label_search` 仍可选。
- 无打标器的图拒存，故不会出现橱窗要树、图上无打标。

无 `graph` 的旧配方打开编辑器时：若 `overview.detail` 没有 `widget_id=labels_tree` 的卡，**自动插入**锁死卡，不覆盖用户其它详情卡。预设「从模板填入」之后同样补洞。

### 7.3 绑定

橱窗绑定下拉 = 图上声明的产物 id + 数据源。`compile` / `graph_runtime` **不读** overview 卡；overview **不写** graph。

运行时 `/w/:id` 仍走现有 clip/run API。绑定用于类型校验与空态；v1 不另做取数总线。`labels_tree` 读该 clip 当前 run 的 `labels_json`。

---

## 8. 切片、测试、风险

| 切片 | 内容 | 完成标志 |
|------|------|----------|
| **A** | `graph` 校验、hydrate 链、投影线性字段、ivi 种子补打标器 | 内核单测 |
| **B** | xyflow 画板；投放/连线/检查器；打标器不可删；if 两出边 | 编辑器单测 + Playwright |
| **C** | 详情锁死 `labels_tree`；绑定已发布产物；空态 | 编辑器 + `/w/:id` |
| **D** | `graph_runtime`；AND 条件；review/export 登记 | worker 单测（假 op，不跑真 Omni） |
| **E** | 压扁规则单测；编辑器黄警告 | 不跑 DataWorks |

A→B→C 可先合：图画得出、保存得进；无 graph 仍走旧执行。**D 才是真按图跑**。E 可与 D 并行。

Playwright 至少：画布可投放 if 与打标器；删不掉打标器；详情区存在锁死 `labels_tree`。

风险：舱内 `plan_and_run` 整包与「ASR 后 if」冲突——D 必须拆适配器，否则禁止在该位置投放 if（组件栏/保存校验提示）。种子覆盖依赖 **后端重启**。

---

## 9. 验收工单

`project-management/acceptance/UI-DTYPE-DAG-CANVAS.md`（实现时按切片写 **A / A-E2E / H**）。未实现前不建空验收文件。

CURRENT 推荐下一工单为本 ID；勿抢跑 UI-NVH-REVIEW-SAVE，直至本工单 D 切片有验收或用户改口。
