---
name: rosbag-platform-kernel
description: >
  开发或修改本仓库平台内核时使用：DataType 配方、源湖 platform_source、内部 Sample、
  开跑绑定、产物 cache/lineage、内置 oms_cabin / audio_array_spec / ivi_ui_stub / audio_defect。
  不适用于：改 DataWorks 节点、OMS SDK extract/label 阶段本身、纯 Taxonomy Hub 文案、
  云端 MC DDL。
---

# 平台内核（DataType）

规格：`docs/superpowers/specs/2026-08-18-platform-datatype-kernel-design.md`。  
代码：`hmi/backend/hmi/platform/`。前端：`DataTypeHomePage` / `DataTypeEditorPage`（管线编排组件卡） / `LakeManagePage` / `PipelineManagePage`。

## Gotchas

1. **在 UI 上「组 Sample」当主路径** — 产品已内部化 Sample。**纠正：主路径是管线管理多选源 → `create_run_from_sources`。**
2. **publish `audio_nvh-v2`** — 会 archive OMS published 树。**纠正：阵列树保持 draft；CURRENT 禁止 publish。**
3. **源湖 POST 打到 cloud 模式** — API 会拒绝。**纠正：入库只在 local；云端走 OSS/DataWorks。**
4. **检索不带 DataType 工作区** — 会混 OMS 与 NVH clip。**纠正：先进 `/w/:dataTypeId`，`search_scope` 隔离。**
5. **用 VL 做 bbox 或改 DataWorks 做内核切片** — 超出范围。**纠正：bbox 仅 opencv/yolo；内核工单勿改 DW。**
6. **梅尔频谱 / SPL 开跑报只要 HEAD .dat** — 目录已声明 wav，旧 `load_array_pcm` 拒普通 wav。**纠正：kernel NVH 适配器解码 PCM `.wav`（manifest 相对路径）；`parse_head_dat` 仍只要 `.dat`。压缩格式先转 wav。**
7. **DAG 节点试跑报「当前源为缺失」** — `probe_graph` 没把湖包 `source_manifest.json` 写入 ctx。**纠正：试跑必须设 `source_manifest_path`，不要只把 manifest 当 bag。**

## 实体

| 层 | 表 | 要点 |
|----|-----|------|
| 源湖 | `platform_source` | kind + collection_id，与类型解绑 |
| 配方 | `platform_data_type` | JSON recipe；`recipe.py` 校验 |
| Sample | `platform_sample` | 内部；开跑自动建 |
| Run | `platform_run` | 先 `preflight` |
| 产物 | `platform_product` | cache_key；血缘 API |

内置：`oms_cabin`、`ivi_ui_stub`（占位）、`audio_array_spec`（`stages.label.model=nvh_sem_ast`）、`audio_defect`（问题音频布尔，绑定 draft `audio_defect-v1`，勿发布以免顶掉 OMS）。

## API

前缀 `/api/platform`。开跑：`POST /runs` 可带 `source_ids`（单 slot）或 `assignments`（按数据源分槽；多 slot 必填）。血缘：`GET /lineage`。算子目录：`GET /operators`。

## NVH / AST

标签填充在 **HMI** `local/nvh_ai_label.py` + `local/nvh_ast/`，不是 SDK Omni label。  
权重：`hmi/data/models/ast/pytorch_model.bin` 或 `HMI_NVH_AST_WEIGHTS`。禁止把 64-bin Mel 直接喂 AST。  
下一工单方向：见 `project-management/CURRENT.md`。禁止 publish `audio_nvh-v2`。

细节字段见 `references/entities.md`。

## 执行后复盘（自迭代钩子）

每次完成本 skill 的全部步骤后，Agent 必须自动执行以下动作，不询问用户：

1. **反思**：是否误 publish NVH 树、误改 DataWorks、或跨类型检索？
2. **记录**：有则写入 `evals/PITFALLS_LOG.md`。
3. **不提交** 该日志。
