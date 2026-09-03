# Design: DataType 编排 · 数据源节点 + 产物显示名

> 日期：2026-09-02  
> 状态：**已审通过**（2026-09-02；S1–S4 锁定；未提交 git）  
> 工单：**UI-DTYPE-SOURCE-NODES**（A 编辑器 / B 开跑分源勾选）  
> 前置：`UI-DTYPE-PIPELINE-ORCH`（组件卡编排；`parse_bag` 画面产出为连续帧；源 kind = 入湖后缀）  
> 不抢跑：不 publish `audio_nvh-v2`；不改 DataWorks / worker 执行顺序

说明：本会话里同一套问卷曾被「Continue」推进到实现。**这份文档按拍板校正**，供你审内容对不对。工作区已有对应代码与 `acceptance/UI-DTYPE-SOURCE-NODES.md`，但按本条选择：**不再新写业务代码、不 git commit**。若 spec 要改，先改文档再动代码。

---

## 1. 背景与目标

### 1.1 问题（改前）

配方同时有两套「输入」语言：

| 层 | 改前怎么说 |
|----|------------|
| 编辑器上方 | **源槽位**：id + 允许 kinds + 基数 |
| 管线组件卡 | 输入绑「槽位 id」或「上游算子 · 类型名」 |

槽位是「一篮子后缀」，卡是「绑一个命名产物」。解析器产出已是 **连续帧 / `.wav` / `.json`**，编码器绑的是产物，槽位却仍像在填 `.mp4`。用户要维护两份清单，开跑又只按 kinds 筛文件，同后缀多个逻辑源会混在一起。

### 1.2 目标

1. **数据源是编排列表里的节点**，不再有独立「源槽位」表单。
2. 算子输入只从两处选：**上方数据源节点**，或 **上方算子产物**。
3. 算子产物可设 **显示名**（下拉用中文名）；底层 port id 不变。
4. 开跑时按 **数据源名称分块勾选** 入湖文件，不再只按后缀自动塞。
5. 保存仍编译到现有 `slots` + `preprocess`/`bindings`，**worker / DataWorks 不改**。

### 1.3 非目标

- 自由拖线画布、边编辑器
- 改 DataWorks、MaxFrame、`local_sdk_worker` 阶段顺序
- 按 `emit_modalities` 裁剪真实解析产物（仍只影响编辑器绑定）
- publish `audio_nvh-v2`；UI-NVH-REVIEW-SAVE 业务
- 把 Sample 重新做成用户主路径

---

## 2. 已拍板决策

| ID | 决策点 | 选择 |
|----|--------|------|
| S1 | 槽位 UI | **删除独立「源槽位」模块**；数据源 = 编排列表中的卡 |
| S2 | 数据源形态 | **节点**，不是单独表单；可一源多文件（kinds + cardinality） |
| S3 | 开跑分配 | **按数据源名称分块勾选/分配文件**（`manual_map`）；禁止仅按后缀自动塞进同名多源 |
| S4 | 产物自定义名 | **仅显示名**（`label_only`）；绑定、缓存、`produces` 仍用 `frames` / `.wav` 等 port id |
| S5 | 执行层 | 编译回现有 `recipe.slots` + 卡 `bindings`；不改 worker / DataWorks |
| S6 | 依赖方向 | 列表从上到下；节点只能绑 **更上方** 的数据源或产物 |
| S7 | 实现切片 | **A** 编辑器（源卡 + 显示名 + hydrate/compile）；**B** 开跑分源勾选 + 预检 |

本设计 **修订** 内核 spec 的 D10：开跑不再是「按 kinds 筛完一篮子多选」，而是「按数据源节点分槽勾选」。`collection_id` 分组展示仍保留。

后续 UX（仍符合 S1/S2）：编辑器 **视觉上** 顶部一张数据源容器卡；「添加数据源」在卡内追加一行。每一行仍是一个逻辑源，编译为一个 `slots[]` 项。不要把「一张视觉卡」理解成「整个配方只有一个 slot」。

---

## 3. 编排模型

列表是唯一图：`steps[]` 有两类卡。逻辑上仍是「一个命名源 + 若干算子」：

```text
[数据源] 舱内阵列     kinds=.wav  4..4
[数据源] 舱内 bag     kinds=.bag  1..1
[算子]   ROSBAG 解析器  in ← 舱内 bag
         产出：连续帧（显示名「舱内连续帧」）、.wav、.json
[算子]   音频 ASR      in ← ROSBAG 解析器 · .wav
[算子]   视频编码器    in ← ROSBAG 解析器 · 舱内连续帧
```

编辑器呈现：上述两条数据源可以同处一张容器卡的两行（`pipe-source-row`），算子卡仍各自一张、可折叠拖拽排序。

### 3.1 数据源（逻辑源 = 一行 / 一个 slot）

| 字段 | 说明 |
|------|------|
| `key` | 稳定 id，编译为 `slots[].id` |
| `card_kind` | `"source"` |
| `title` | 显示名（开跑分块标题、算子输入下拉） |
| `kinds` | 入湖文件后缀列表（槽内 OR），非泛型 video/audio |
| `cardinality_min` / `cardinality_max` | 该源要装多少个文件 |
| `required` | 缺则预检失败 |

一个逻辑源可多文件。四路 `.wav` = **一行**、`kinds=['.wav']`、min=max=4。不要为每个文件建一行，除非业务上就是独立源。

`oms_cabin` 四个 slot（rosbag / video / image / audio）= 容器卡内 **四行**，编译仍是四个 slot。

产出：单端口，port id = `key`，类型 = `kinds`（下游用 `type_compatible` 匹配）。

### 3.2 算子卡

与现组件卡相同，另加：

| 字段 | 说明 |
|------|------|
| `output_labels` | `Record<port_id, string>`，只影响 UI 文案 |

未填显示名时：`typeLabel(port_id)`（`frames` →「连续帧」）。

输入下拉选项：

1. 上方数据源：标签 = `title`（如「舱内阵列」）
2. 上方算子产物：标签 = `{算子 title} · {output_label 或 typeLabel}`

类型不兼容的选项不出现。多输入算子（打标器 / 向量化器等）用多选；单输入仍单选。

### 3.3 校验（保存拒绝）

- 数据源 `title` 非空、同配方内不重复（大小写不敏感）
- `kinds` 非空且均属于 catalog `source_kinds`
- 算子绑定的数据源 / 上游卡必须出现在 **该卡之上**
- `output_labels` 的 key 必须是该算子当前 `produces` / 端口 id
- 仍拒绝：未知 `op_id`、stage 算子写入 `preprocess`、未知 params key、`bbox.detector=vl`

---

## 4. 配方 JSON（对外仍是 slots）

`PUT /api/platform/data-types/{id}` 的持久化形状不新增顶层表。

**编译（编辑器 → 配方）**

- 每个逻辑源（`card_kind=source` 行）→ `slots[]`：`id=key`，`title`，`kinds`，基数，`required`；`role` 可省略或写 `input`
- `require_any_kinds`：每个 **required** 数据源的每种 suffix **单独一组**（与种子 `singleton_kind_groups` 相同）。现网 `preflight()` 把一组当成 **AND**；若写成 `[[.wav,.mp3,…]]`，保存后单文件会预检失败。组与组之间仍是 OR。
- 算子卡 → 现有 `preprocess` / `stages` / `bbox`
- 绑定数据源：`bindings.in = { kind: "slot", slot_id: source.key }`
- 绑定上游产物：`{ kind: "upstream", step_key, port_id }`（port_id 仍是 `frames`，不是显示名）

**`output_labels` 存放（S4 已拍板）**

不要写入 `params`（`param_keys_for_op` 会拒未知 key，worker 也不该看见）。挂在 preprocess 条目上，与 `params` **并列**：

```json
{
  "op_id": "parse_bag",
  "when_kind": ".bag",
  "produces": ["frames", ".wav", ".json"],
  "output_labels": { "frames": "舱内连续帧" },
  "bindings": { "in": { "kind": "slot", "slot_id": "rosbag" } }
}
```

`validate_recipe` 允许该字段。worker / overlay **禁止**因该字段失败。

**Hydrate（配方 → 编辑器）**

- 每个 slot → 一条逻辑源行，`title` 缺省为 `id`
- 旧配方无 source 卡、只有 slots：打开编辑器即看到对应行（不丢槽位）
- `oms_cabin` 四个 slot → 容器卡内四行 + 原算子卡；数据源行排在消费它们的算子之前

---

## 5. 开跑绑定（切片 B）

`POST /api/platform/runs`（及 `/runs/preflight`）在 `source_ids` 之外增加：

```json
{
  "data_type_id": "audio_array_spec",
  "assignments": [
    { "slot_id": "audio_primary", "source_ids": ["sha256:…"] }
  ]
}
```

种子 slot id 以 `seed_recipes()` 为准：`audio_array_spec` → `audio_primary`；`ivi_ui_stub` → `ui_media`；`oms_cabin` → `rosbag` / `video` / `image` / `audio`。

规则：

- 每个 **required** 数据源必须出现在 `assignments` 里
- 每个 `source_id` 的 kind（文件后缀）必须落在该 slot 的 `kinds` 内
- 已出现的 assignment 数量满足 min/max；**可选** slot 未出现则视为 0 个文件（不按 min=1 失败）
- 同一 `source_id` 不得分给两个 slot
- 服务端仍 `create_sample` + `create_run`；Sample 的源列表 = assignment 去重后的并集

**UI（管线管理 → 源湖开跑）**

1. 选 DataType
2. 每个逻辑源一块 `data-testid="lake-run-slot-{id}"`：标题 = `title`，副文案 = kinds × 基数
3. 该块内列出 **kind 合格** 的湖源（可按采集批分组）；用户勾选
4. 预检按块失败（「舱内阵列：需要 4 个 .wav，已选 2」），不静默
5. 全部 required 块合法后才能开跑
6. 已勾进 A 块的文件在 B 块禁用

不再提供「全表多选再按后缀自动分槽」作为主路径。旧 API 仅 `source_ids`、无 `assignments`：若配方只有 **一个** 数据源，可把 `source_ids` 视为对该 slot 的 assignment；多个数据源则 **400**，要求 `assignments`。

---

## 6. 错误与边界

| 情况 | 行为 |
|------|------|
| 保存时绑定指到下方节点 | 400，指出卡 title |
| 显示名与另一产物显示名撞车 | 允许（下拉用「算子 · 名」区分）；数据源 **title** 不允许撞车 |
| 开跑文件 kind 不匹配该块 | 该块预检失败 |
| 图片源进执行 | 保持现状：编入可预检通过的类型，worker 仍可能 fail（不在本设计扩大执行能力） |
| 种子配方 | hydrate 出数据源行；未点保存前 DB 仍是原 slots |

---

## 7. 测试与验收

### A（编辑器）

- 单元：slot ↔ 数据源行 round-trip；`output_labels` 不进算子 params schema 仍能 validate；绑定只允许上方节点
- `tsc -b`（Windows：`npx.cmd` / `cmd /c`，禁止直接 `npm`）
- Playwright：没有独立「源槽位」标题；`pipe-add-source` 追加 `pipe-source-row`；`oms_cabin` 一张 `pipe-source-card`、四行；解析器芯片「连续帧」

### B（开跑）

- 单元：`assignments` 校验；单 slot 兼容裸 `source_ids`；多 slot 无 assignment → 400；错 kind / 同一 id 两槽被拒
- Playwright：`audio_array_spec` 在 `lake-run-slot-audio_primary` 勾选 `.wav` 后预检通过；`ivi_ui_stub` 的 `lake-run-slot-ui_media` 不出现 `.txt`

无 H。A + A-E2E 全绿可标对应切片 done。

---

## 8. 与其它工单

| 工单 | 关系 |
|------|------|
| UI-NVH-REVIEW-SAVE | CURRENT **推荐下一**；本工单不抢跑语义写回 |
| UI-DTYPE-PIPELINE-ORCH | 本设计的编辑器底座；不回退组件卡 |
| UI-DTYPE-OVERVIEW-COMPOSE | 总览拼版；与源节点正交 |
| PLAT-LAKE-RUN-BIND | 切片 B 修订其 UX（分源勾选） |

权威链仍是：PRD > 本 spec（本主题）> 内核 spec D10 旧句 > CURRENT 摘要。

实现计划（若审过需要对照）：`docs/superpowers/plans/2026-09-02-datatype-source-nodes.md`。
