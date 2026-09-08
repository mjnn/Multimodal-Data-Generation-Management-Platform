# Design: 管线 runtime kernel + 可插拔 capability

> 日期：2026-09-04（slice-3 `text_to_json`：2026-09-07）  
> 状态：implemented（本地 catalog 算子均有插件）  
> 定位：编排组件扩展走 **插件**，不拆成「一组件一 SDK 包」

---

## 1. 目标

DataType DAG 上的每个算子对应 **一个 capability 插件**。本地 worker 按图拓扑逐节点调用插件，把产物写进本次 run 的 context，供后续 **if** 与血缘使用。

不把 `oms-multimodal-sdk` 拆成多个 pip 包。舱内视觉 / ASR / Omni / 向量仍是该 SDK 里已有的原子能力（`extract` / `transcribe` / `label` / `embed`…），由 kernel 按 `op_id` 去调。

## 2. 分层

| 层 | 职责 | 代码 |
|----|------|------|
| Kernel | 注册表、DAG 调度、context、进度 | `hmi/platform/capability_kernel.py` |
| SDK plugins | 封装 `run_plan` 单步 | `hmi/platform/capability_sdk.py` → `oms_multimodal.capabilities` |
| Local plugins | JSON 提取、标签树输入、NVH 等 | `graph_runtime` 内置 + NVH 模块 |
| Catalog | UI 标题 / ports / params | `operators.py`（不执行） |
| Cloud | 仍一条 Driver；**本切片不改 DataWorks** | `pipeline/dataworks/` |

## 3. 插件契约

```text
op_id → { backend: sdk|local|control, sdk_capability?, writes: [ctx keys] }
run(node, ctx) → patch dict 合并进 ctx
```

- `sdk`：`parse_bag`→`extract`，`extract_frames`→`ingest_sources`，`encode_preview`→`encode_preview`（并 `preview`），`transcribe`→`transcribe`，`detect_bbox`→`annotate_bbox`，`label`→`label`（`nvh_sem_*` 走本地 NVH），`embed`→`embed`
- `local`：`json_extract`、`label_tree_input`、`text_to_json`（`graph_runtime`）；NVH：`parse_head_dat` / STFT / Mel / 1/3 倍频程 / SPL（`capability_nvh.py`）；未登记适配器的 local 插件失败（`capability 未实现`）
- `control`：source / if / review / export（解释器内置）

无 graph 的旧配方仍走 `plan_and_run`。无 graph 的 `audio_array_spec` 仍走专用路径。

## 4. 第一切片（已完成）

1. 注册表 + SDK 单步适配器，transcribe/label 写 `ctx.asr` / `ctx.labels`
2. worker：有 graph 且非阵列类型 → `execute_graph` + 插件，不再整包 `plan_and_run`
3. 去掉「ASR/打标之后不能 if」护栏
4. 进度：优先读 `pipeline_step.dag:{node_key}`，不再把整段 `sdk_infer` 糊在第一个节点

## 4b. 第二切片（阵列）

1. 有 `recipe.graph` 的 `audio_array_spec` → `execute_recipe_graph` + 本地 NVH 插件
2. 频谱插件复用 `analyze_pcm_pa`（一次计算，后续节点读产物）
3. `spl_timeline` 后 deriver；`label`（`nvh_sem_*`）填 L6 并写 `nvh_labels.json`
4. worker 发布仍走 NVH 产物拷贝 / OSS / `apply_nvh_labels_to_facts`，不走舱内 `import_real_data_clips`

## 4c. 第三切片（`text_to_json`）

1. 本地插件读源湖 `source_manifest` 的 `text` / `text_path`（相对路径相对清单目录）
2. `schema_id=generic_json` → `json.loads`；`generic_text` → `{"raw": text}`；未知 schema / 非法 JSON / 找不到文件均失败
3. 写入 `ctx.structured_json`；有 `run_dir` 时落 `structured.json`，供下游 `json_extract` / `json_tree`

## 5. 非目标

- 一组件一个 PyPI 包
- 改 DataWorks / DPE 节点
- publish `audio_nvh-v2`
- 温度 / max_tokens 打进 Omni（SDK 仍无钩子）
