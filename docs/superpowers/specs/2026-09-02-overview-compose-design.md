# Design: DataType 总览视图 · 组件拼版

> 日期：2026-09-02  
> 状态：approved（会话拍板；实现中）  
> 工单：**UI-DTYPE-OVERVIEW-COMPOSE**（可拆 A 编辑器+配方 / B 运行时列表+详情）  
> 前置：管线编排组件卡（含数据源节点、多选绑定）  
> 不抢跑：不 publish `audio_nvh-v2`；不改 DataWorks / worker 阶段顺序

---

## 1. 背景与目标

### 1.1 问题

配方只有 `overview_view` 整页模板 id（`cabin_timeline` / `audio_nvh_timeline` / …）。编辑器是下拉；运行时 `OverviewPage` / `ClipMediaPanel` 还按 `dataTypeId === 'audio_array_spec'` 等硬切，工作区横幅只打印模板 id。无法像管线那样把「统计、检索、表列、四路时间轴、频谱、ASR」拼成自定义总览。

### 1.2 目标

1. **列表页和 Clip 详情（含校核媒体区）** 都由配方里的有序组件卡驱动。
2. 两套独立列表：`overview.list[]`、`overview.detail[]`，不混用。
3. 每张视图卡 **手动绑** 数据源或管线产物（与算子输入同一套 `bindings`）。
4. 旧 `overview_view` 变成 **预设 id**：一键填入两套卡；运行时只认卡列表。
5. v1 只包装现有面板，不新做可视化、不画自由画布。

### 1.3 非目标

- 自由画布 / 行列 span 网格
- 改 DataWorks、worker 执行顺序、真实解析产物
- publish `audio_nvh-v2`；UI-NVH-REVIEW-SAVE
- 新图表引擎；JSON 树 v1 用现成结构化 JSON / labels 浏览即可

---

## 2. 已拍板决策

| ID | 决策点 | 选择 |
|----|--------|------|
| O1 | 拼哪一层 | **列表 + 详情**（校核详情复用同一套 `overview.detail`） |
| O2 | 配方怎么存 | **两套独立有序卡** `list` / `detail` |
| O3 | 数据怎么接 | 每张卡 **手动绑** slot 或上游产物 |
| O4 | 旧模板 | 保留 `overview_view` 为 **preset id**；点选预设填两套卡，仍可改 |
| O5 | 详情布局 | **上下叠卡**（与管线一致）；不做网格 |
| O6 | 执行层 | 只影响 HMI 渲染；worker / DataWorks 不读 overview 卡 |
| O7 | 切片 | **A** 目录 + 校验 + 编辑器；**B** Overview / Explorer / 校核按卡渲染 |

---

## 3. 配方形状

```text
recipe.overview_view = "cabin_timeline"   # 预设 id，必填（兼容旧接口）
recipe.overview = {
  preset: "cabin_timeline",               # 上次点选的预设；可与 overview_view 相同
  list:   [ ViewCard, ... ],
  detail: [ ViewCard, ... ]
}

ViewCard = {
  key: string,                 # 稳定，编辑器内唯一
  widget_id: string,           # 代码注册
  bindings: {                  # port_id → 单个或数组（widget.multiple）
    [portId]: Binding | Binding[]
  }
}

Binding = { kind: "slot", slot_id } | { kind: "upstream", step_key, port_id }
```

- 未知 `widget_id` 拒存。
- 绑定形状与管线卡相同；只能指向 **该配方编排里已有的** 源卡 key 或算子产物 port。
- widget 声明的 `needs`（类型列表）必须被绑定覆盖（`needs` 为空则绑定可选）。
- `list` 为空时运行时仍渲染一张默认 `clip_table`（保证能点进 Clip）。
- `detail` 为空时详情回退：有 NVH bootstrap 则频谱，否则舱内时间轴（与今日硬切一致，仅作兜底）。

### 3.1 旧配方 hydrate

只有 `overview_view`、没有 `overview.list/detail`：按预设表填两套卡（绑定留空，编辑器打开后可再绑；运行时绑定为空的卡仍按 widget 自有数据接口拉现有 clip/run 产物，与今天一样不读 bindings）。

**v1 绑定语义：** 编辑器保存 bindings 供校验与日后按产物取数；**运行时切片 B 仍走现有 clip/run API**（时间轴、NVH bootstrap、ASR），不因缺绑定而空白。绑定主要用于：类型不兼容时编辑器灰掉 / 保存拒绝。

### 3.2 校验

`validate_recipe`：

1. `overview_view` 仍须 ∈ 预设 id 集合。
2. 若存在 `overview`：必须是 object；`list`/`detail` 为数组；每张卡 `key`、`widget_id` 必填；`widget_id` ∈ 目录且 `surface` 匹配所在数组。
3. `bindings` 值是 object 或 list of object，`kind` ∈ slot|upstream。
4. 写出规范化 `overview`（缺则按预设补全后再写回，这样 GET 配方始终带卡列表）。

---

## 4. 组件目录（v1）

`surface`: `list` | `detail`。`needs`: 兼容类型（OR）；空 = 不强制绑。

| widget_id | surface | 标题 | needs | 运行时（现有组件） |
|-----------|---------|------|-------|-------------------|
| `clip_metrics` | list | Clip 统计 | — | `OverviewClipPieChart` + `OverviewClipMetricsGrid` |
| `label_search` | list | 标签/ASR 检索 | `asr_jsonl` / `labels_tree` | `OverviewClipSearchPanel` |
| `clip_table` | list | Clip 表 | — | 现有 Table（状态/校核/时长） |
| `nvh_spl_column` | list | 声压摘要列 | `spl_jsonl` / `.wav` | 表上 SPL 列 |
| `cabin_multicam` | detail | 舱内多路时间轴 | `frames` / `preview_mp4` | `ClipTimelinePanel` |
| `nvh_spectrum` | detail | 四通道频谱时间轴 | `mel_matrix` / `spl_jsonl` / `.wav` | `AudioNvhTimelinePanel` |
| `asr_panel` | detail | ASR 文本 | `asr_jsonl` | Explorer/校核 ASR 区 |
| `frame_gallery_bbox` | detail | 帧画廊 + BBox | `frames` / `bboxes_jsonl` | `ClipTimelinePanel`（bbox 开） |
| `json_tree` | detail | JSON 结构 | `structured_json` / `.json` | 只读 JSON（labels 或结构化产物） |

### 4.1 预设 → 卡

| preset (`overview_view`) | list | detail |
|--------------------------|------|--------|
| `cabin_timeline` | clip_metrics, label_search, clip_table | cabin_multicam, asr_panel |
| `audio_nvh_timeline` | clip_metrics, nvh_spl_column, clip_table | nvh_spectrum |
| `audio_spec_asr` | clip_metrics, clip_table | nvh_spectrum, asr_panel |
| `frame_gallery_bbox` | clip_metrics, clip_table | frame_gallery_bbox |
| `json_tree` | clip_metrics, clip_table | json_tree |

---

## 5. 编辑器

基本信息里 **去掉单独的总览下拉作为唯一配置**。改为：

1. 「从预设填入」Select（写 `overview_view` + 重置两套卡）。
2. **总览列表**、**Clip 详情** 两个拼版区：左侧/上方为该 surface 的 widget 目录，右侧为有序卡（可折叠、可拖动，复用管线卡壳）。
3. 每张卡：绑定下拉（数据源或管线产物，规则与 `bindingOptions` 相同）；`needs` 空则隐藏绑定。

保存：`buildRecipe` 带上 `overview`；`compileSteps` 不管视图卡。

---

## 6. 运行时

- `DataTypeWorkspaceContext` 附带当前 `recipe`（layout 已加载）。
- **OverviewPage**：不再 `dataTypeId === 'audio_array_spec'`；按 `overview.list` 顺序渲染。`clip_table` 为表宿主；`nvh_spl_column` 只在表存在时加列。
- **ClipExplorerPage / ReviewClipMediaPanel**：按 `overview.detail` 叠卡，取代 `mediaMode` 硬切。无 detail 卡时走 3.1 兜底。
- 横幅：显示预设标题 + 「自定义」若卡与预设不完全相同。

---

## 7. 测试

- 单测：未知 widget 拒存；预设 hydrate；surface 放错数组拒存；种子 GET 后带 `overview.list/detail`。
- Playwright：编辑器可见两个拼版区；oms_cabin 详情含舱内时间轴卡；切预设填入 NVH 后列表出现声压列卡。
- 不测真实 Omni/AST 推理。

---

## 8. 验收工单

`project-management/acceptance/UI-DTYPE-OVERVIEW-COMPOSE.md`（A / A-E2E）。切片 A 可先写 A 节；B 补运行时 E2E。
