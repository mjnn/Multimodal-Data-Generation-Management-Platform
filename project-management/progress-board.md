# 进度看板

> 最后更新：2026-09-07

## Todo

| ID | 标题 | 里程碑 |
|----|------|--------|
| M7.5-E2E | Parquet 全链 zip E2E（**推荐下一 / 可选**） | M7.5 |
| M9.3-H-2 | HMI 在线主观（**暂停不排期**） | M9 |

## Doing

| ID | 标题 | 备注 |
|----|------|------|
| 平台内核重构 | DataType 底座 | run 分支已并列生效；勿 publish audio_nvh-v2 |

## Done

| ID | 标题 | 完成日 |
|----|------|--------|
| **PLAT-RUN-BRANCHES** | 同一 clip 每次 run 并列生效 | 2026-09-07 |
| **PLAT-DAG-IO-CONTRACT** | DAG 输入封闭 + 黄叹号 + 节点试跑 | 2026-09-07 |
| **PLAT-CAPABILITY-KERNEL** | DAG kernel：阵列 NVH + `text_to_json` | 2026-09-07 |
| **UI-NVH-REVIEW-SAVE** | 语义 L6 人工写回 facts + nvh_labels.json；e2e tree 2/2 | 2026-09-04 |
| **FIX-ENCODE-FFMPEG** | Windows 无 PATH ffmpeg 时 encode_preview 用捆绑二进制 | 2026-09-04 |
| **UI-DTYPE-DAG-CANVAS** | 执行 DAG 画板 + 本地 graph runtime + 橱窗锁标签树；e2e editor 3/3 | 2026-09-03 |
| **UI-DTYPE-SOURCE-NODES** | 数据源节点 + 开跑分源；2026-09-03 polish：打标器固定最后，e2e editor 3/3 | 2026-09-03 |
| **UI-DTYPE-OVERVIEW-COMPOSE** | 总览列表 + 详情组件拼版 | 2026-09-02 |
| **UI-DTYPE-PIPELINE-ORCH** | DataType 管线编排（SDK 组件卡） | 2026-09-02 |
| **FIX-SPA-PREFIX** | 直连 :8012 子路径空白页（剥 UI 前缀） | 2026-08-28 |
| **DOC-INTRANET-CICD** | 域内堡垒机 + docker save/load/run 交接 | 2026-08-27 |
| **DOC-HANDOVER** | 交接 Wiki、架构图、Agent 技能包、压缩包脚本 | 2026-08-25 |
| **PLAT-AUDIO-AST-LABEL** | AudioSet AST 映射 category/sources | 2026-08-21 |
| **UI-DTYPE-EDITOR** | 新建/编辑 DataType（槽位·预处理·产物·能力开关） | 2026-08-20 |
| **UI-LAKE-OSS-IA** | 源湖入库+OSS；开跑进管线管理 | 2026-08-20 |
| **DOC-DTYPE-SLOTS** | Sample 内部化 / slots / collection / lineage 规格 | 2026-08-20 |
| **PLAT-LAKE-RUN-BIND** | 选类型筛源多选 → 自动 Sample+Run | 2026-08-20 |
| **PLAT-PRODUCT-LINEAGE** | product 血缘 API + worker 写入 | 2026-08-20 |
| **PLAT-DTYPE-LAKE-REUSE** | 列表/多选复用已入库 Source 组 Sample | 2026-08-20 |
| **ISOLATE-DTYPE-CLIPS** | OMS 总览排除 audio/IVI typed clip | 2026-08-20 |
| **PLAT-AUDIO-AI-LABEL** | audio L6 语义 AI（heuristic/可选 VL）+ draft 绑定 | 2026-08-20 |
| **UI-NVH-OVERVIEW** | 纯音频总览/探索/校核 = 四通道频谱时间轴 + typed 列表 | 2026-08-20 |
| **OP-DERIVE-NVH** | L2 → `labels_json` / `y_json` 客观真值推导 | 2026-08-20 |
| **TAX-AUDIO-NVH-v2** | HEAD 四通道声压/噪音真值 taxonomy 全量 78 叶 | 2026-08-20 |
| **PLAT-DTYPE-LAKE** | 源湖入库 UI（与类型解绑的上传/组样本） | 2026-08-18 |
| **PLAT-DTYPE-RUN** | 管线开跑接到 DataType 预检 | 2026-08-18 |
| **PLAT-DTYPE-KERNEL** | 源湖 + DataType 配方 + OMS/IVI 工作区 | 2026-08-18（H-1 已签） |
| **HMI-BBOX-OVERLAY** | 可编辑 BBox 叠加层（bboxes.jsonl） | 2026-08-14 |
| **HMI-SDK-MODALITY** | 原始媒体上传 + Planner 模态编排（local） | 2026-08-12 |
| **HMI-SDK-BBOX** | 本地 BBox 参数 + infer_full + Plain/BBox + enum_tree | 2026-08-12 |
| **HMI-TEST-MODE** | 测试模式开关 + 重置测试数据（云端清 OSS+MC） | 2026-08-11 |
| **M9.3-A-C-2** | hybrid 4-bag verify 18/18 + meta repair | 2026-08-10 |
| **M8.5+** | 派生向导平衡+标签裁剪 UI | 2026-07-31 |
| **M10.10** | Hub diff/impact/lineage UI polish | 2026-07-31 |
| **M9.2** | PostgreSQL 迁移路径 (docs) | 2026-07-31 |
| **M7.8** | 导出顾问 | 2026-07-31 |
| **M9** | 部署与治理 | 2026-07-31 |

## Blocked

| ID | 标题 | 阻塞原因 |
|----|------|----------|
| — | — | — |
