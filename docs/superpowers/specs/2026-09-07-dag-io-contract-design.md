# Design: DAG 节点 I/O 契约

> 日期：2026-09-07  
> 状态：implemented（2026-09-07；acceptance/PLAT-DAG-IO-CONTRACT.md）  
> 工单：**PLAT-DAG-IO-CONTRACT**  
> 前置：PLAT-CAPABILITY-KERNEL  
> 不抢跑：不 publish `audio_nvh-v2`；不改 DataWorks / DPE 节点或 Job 顺序

编排图画的连线与期望产出，必须等于本地 kernel 真正吃进去、交出来的东西。禁止 SDK 因磁盘上「碰巧有 wav」就多喂一路模态。

---

## 1. 目的

用户要的不是「给打标器打一个 wav 开关」，而是整张图成为**封闭 I/O 契约**：

1. **每个节点的输入**只能来自上游节点声明的输出端口，或数据源槽位。
2. **每个组件有最小输入**。选中/连上的输入不够最小集时，节点卡片左上角**黄叹号**（提示，不拦保存）。
3. **编排时声明期望输出**；提供节点试跑（运行到某节点；解析/变换真跑，AI 默认只验输入，可选手动含 AI），用来发现实际产物对不上期望。
4. **全量执行只消耗已绑定输入**。若上游声明了某产物却没交出来，**在上游节点失败**，不要让下游静默少吃或多吃。

成功标准（舱内 rosbag + Omni 打标）：同一 bag、打标器绑 `.wav` 与不绑 `.wav`，Omni 实际是否带 `input_audio` 必须不同；解析节点若勾了 `.wav` 却没写出音频，失败记在解析节点。

---

## 2. 非目标

- 改 DataWorks / DPE / 云端 Job 顺序
- 一组件一个 PyPI 包
- publish `audio_nvh-v2`
- 把温度 / `max_tokens` 打进 Omni
- 并行 join
- 拦保存（黄叹号不是红色硬错误）
- 试跑写入 `dim_clip.active_run_id` 或 `fact_clip_label`（探针隔离）

---

## 3. 已拍板

| ID | 决策 | 选择 |
|----|------|------|
| D1 | 架构 | **独立 I/O 契约层** `io_contract.py`，catalog / 编辑器 / kernel / 探针共用。不逐个 adapter 打补丁。 |
| D2 | 试跑 | **混合**：解析/变换真跑并对产物；`label` / `embed` / `transcribe` / `detect_bbox` 默认只验绑定输入是否到位；检查器可开「含 AI 真跑」。 |
| D3 | 黄叹号 | 编排期提示；**不拦保存**。全量跑或试跑时，最小输入不足 → **该节点**失败。 |
| D4 | 多出来的磁盘文件 | 允许（例如 parse 仍可能写出未声明的 wav）。**下游不得使用未绑定产物**。缺的是**已声明**产物 → 生产者失败。 |
| D5 | 运行单个 vs 运行到某节点 | 都是 `until_key`：执行该节点的祖先 + 该节点。单个节点不能在没有上游产物时凭空跑。 |
| D6 | 范围 | 仅本地 `execute_recipe_graph`。无 graph 的旧整包 `plan_and_run` 不改。 |

---

## 4. 契约模型

### 4.1 Catalog

每个 `input_ports[]` 增加 `min_count`（缺省 `1`；`multiple` 端口表示至少 N 条绑定，多出来的是可选增强）。

| op_id | 最小输入 | 可选增强（须来自上游/源） |
|-------|----------|---------------------------|
| parse_bag | `in` ×1（`.bag`） | — |
| extract_frames | `in` ×1 视频 | 多路视频 |
| encode_preview | `in` ×1 frames | — |
| transcribe | `in` ×1 音频 | — |
| detect_bbox | `in` ×1 画面 | 多路 |
| label / embed | `in` ×1 `labelable` | 额外 `.wav` / `asr_jsonl` / `bboxes_jsonl` / frames… |
| json_extract / text_to_json | `in` ×1 | — |
| label_tree_input | `in` `min_count=0`；**至少一条 assignment** | 上游取值 |
| NVH 谱/SPL / parse_head_dat | `in` ×1 | 多路音频 |
| source / if / review / export | 无最小输入端口 | — |

`output_ports` 是**可声明**的产物。节点 `produces`（parse_bag 即 `params.emit_modalities`）是**本次期望输出**，必须是 output_ports 的子集。未设置时：单出口算子 = 该端口；`parse_bag` 默认三模态。

### 4.2 绑定封闭

节点输入绑定（画布边优先，检查器 `bindings` 补齐）必须满足：

- `kind=slot` → 图上存在该 source 槽，且槽 `kinds` 与端口 types 兼容（`type_compatible`）。
- `kind=upstream` → 上游节点的 **effective produces** 含该 `port_id`（或兼容类型）。禁止绑上游没声明的端口。

诊断码：

| code | 黄叹号文案 |
|------|------------|
| `min_input` | 最少需要 N 路「端口名」，当前 M 路 |
| `unbound_kind` | 输入不在上游产物或数据源内：… |
| `empty_assignments` | 标签树输入还没有条目 |
| `bad_produces` | 期望输出不在组件可输出列表内 |

保存仍成功。`diagnose_graph(graph)` 纯函数，前后端规则一致（后端权威；前端用同一结构渲染）。

### 4.3 运行时消费

插件看到的输入 = **绑定集合**，不是 `run_dir` 里所有文件。

打标器（Omni `default`）：

- 绑定含音频类型（`.wav` / 其它 `AUDIO_EXTS` / `pcm_pa_wavs`）→ 允许 `clip.audio` 进 Omni。
- 否则 **去掉** `clip.audio`（即使 `audio.wav` 在磁盘上）。
- `asr_jsonl` 未绑定 → `merge_asr_file=False`。
- `bboxes_jsonl` 未绑定 → `include_bbox_context=False`（与「把 BBox 写入提示词」AND）。

`parse_bag`：生产者检查按 `emit_modalities`；不要求 SDK 少抽未勾选模态，但未勾选的模态不得进入下游绑定。

向量化同样：未绑定音频则不要把 audio 当融合输入（能在 HMI 侧剥 clip.audio 就剥）。

### 4.4 生产者验收

节点 adapter **成功返回之后**、标 success 之前：对 `effective_produces(node)` 逐项查产物。缺一项：

```text
节点 {key} 未按期望输出: {.wav}
```

记在该节点的 `dag:{key}` = failed。下游不跑。

产物探针（`run_dir` + ctx）：

| produce | 存在条件 |
|---------|----------|
| frames | `clips_index.jsonl` 存在且非空 |
| .wav | index 里 `audio_path` 指向现存文件，或 `run_dir` 下存在 `.wav` |
| .json | index 含 events/json 或 `run_dir` 下存在 clip 级 `.json`（非 `source_manifest.json`） |
| asr_jsonl | `asr.jsonl` 非空 |
| bboxes_jsonl | `bboxes.jsonl` 存在 |
| labels_tree | `labels.jsonl` 或 ctx `labels_tree` |
| embeddings | `fusion_embeddings.jsonl` |
| preview_mp4 | `preview/clip_preview_*.mp4` 或 ctx preview |
| structured_json | `structured.json` 或 ctx |
| json_value | ctx 该节点或 `json_extract.value` |
| NVH 矩阵/SPL | 现有 NVH 产物路径或 ctx writes |

### 4.5 图执行扩展

`execute_graph(..., until_key=None, require_label=True, include_ai=True)`：

- `until_key`：只调度该节点及其祖先；跑完 until 后停止。
- `require_label`：全量跑保持现状（必须执行打标器）。探针 `until_key` 时为 False。
- `include_ai=False`：AI 集合 `{label, embed, transcribe, detect_bbox}` **不调用插件**，只做最小输入 + 绑定封闭检查；解析/变换照常跑。

---

## 5. API / UI

### 5.1 `POST /api/platform/graph/diagnose`

Body：`{ graph }` 或已存 `data_type_id`。  
Return：`{ nodes: { key: { level: "warn"|"ok", codes: [], message } } }`。

编辑器可本地算（避免每动一次边就打 API）；探针与单测走后端。

### 5.2 `POST /api/platform/runs/probe`（仅 local）

```json
{
  "data_type_id": "test",
  "graph": {},
  "until_key": "op-parse_bag-…",
  "include_ai": false,
  "source_ids": ["…"],
  "assignments": []
}
```

- 用与开跑相同的源绑定解析 bag/清单。
- 独立工作目录；**不**写 facts、**不**切 `active_run_id`、**不**进管线队列列表（或 status=`probe` 且橱窗忽略）。
- 返回：`ok`、`run` 节点状态、`produces_expected`、`produces_found`、`missing`、`consume`（打标：`include_audio` 等）、`error`（含失败节点 key）。

缺 `source_ids`：只返回 diagnose，`ok=false`，`error=需要数据源才能试跑`。

### 5.3 画板

- 节点卡片左上角：`level=warn` 时黄叹号（`data-testid="dag-io-warn-{key}"`），title=message。
- 检查器：期望输出（parse_bag 已有 `emit_modalities`；单出口算子只读展示端口名）。
- 检查器底部试跑：选源（复用源湖 eligible 列表）+「运行到此节点」+「含 AI 真跑」。结果展示 expected/found/error。

---

## 6. 代码落点

| 层 | 文件 |
|----|------|
| 契约 | `hmi/backend/hmi/platform/io_contract.py` **新建** |
| Catalog | `operators.py` `_port(..., min_count=)` |
| 调度 | `graph_runtime.execute_graph`、`capability_kernel.execute_recipe_graph` |
| 消费 | `capability_sdk.run_sdk_node`（label/embed 按绑定剥音频/ASR/bbox） |
| SDK 挂钩 | `piplinesdk/.../capabilities/stages.py`：`merge_asr_file` / `include_audio` 从 params 传入；**默认保持现状**（未传则与今天一致）。不改 `pipeline/dataworks/` |
| API | `platform/router.py` diagnose + probe |
| Worker | 全量跑走契约 wrap；探针独立入口，不经过队列 ingest |
| UI | `PipelineDagCanvas.tsx` 叹号；`DagNodeInspector.tsx` 期望输出 + 试跑；`utils/ioContract.ts` |
| 测试 | `scripts/test_io_contract.py`；kernel 回归；e2e `platform-dtype-editor.spec.ts` 黄叹号 |

剥音频优先在 HMI 于 `run_plan(label)` 之前改 clips_index / 传 params，避免 Omni 看到 `clip.audio`。`stages.py` 增加 `include_audio`（默认 True）作为第二道闸。

---

## 7. 验收

**A**

1. `diagnose_graph`：label 零输入 → `min_input`；绑上游未声明的 `.wav` → `unbound_kind`。
2. 全量：label 未绑 wav 时 `include_audio=False`，即便 run_dir 有 `audio.wav`。
3. parse 期望 `.wav` 且探针伪造无 wav → 失败节点是 parse_bag。
4. `until_key=parse` + `include_ai=False` 不调用 label，且不报「AI打标器未执行」。
5. kernel 原有 10 项 + graph_runtime / recipe_graph 回归通过。

**A-E2E**

1. 新建类型、打标器未连源：卡片 `dag-io-warn-*` 可见。
2. 连上 parse_bag 输出后叹号消失（最小输入满足）。
3. 检查器有「运行到此节点」（可无源时提示需要数据源）。

**H**：无。

---

## 8. 进度

回写 `CURRENT.md` / tracking / board / changelog / `acceptance/PLAT-DAG-IO-CONTRACT.md`。
