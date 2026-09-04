# 架构图全集

> 交接日：2026-08-25。与 [`HANDOVER.md`](HANDOVER.md)、[`WIKI.md`](WIKI.md) 配套。  
> 图中路径以仓库根为基准。实现以代码为准；冲突时以 PRD / CURRENT 为准。

---

## 1. 系统总览

平台分四层：**摄入 → 处理 → 存储 → 产品**。新数据默认走 SDK v1；HMI 用 DataType 配方把「舱内 OMS / 阵列 NVH / IVI 占位」隔开。

```mermaid
flowchart TB
  subgraph ingest [摄入]
    BAG[ROS bag / 音视频 / HEAD.dat]
    UP[HMI 源湖上传 或 OSS rosbags/]
  end

  subgraph process [处理]
    WORKER[HMI local_sdk_worker<br/>oms_cabin / audio_array_spec]
    SDK[oms-multimodal-sdk<br/>extract bbox encode asr preview label embed]
    DW[DataWorks sdk_pipeline_driver<br/>DPE extract+preview · Driver AI]
    LEG[Legacy Job0–4<br/>仅维护]
  end

  subgraph storage [存储]
    OSS[OSS<br/>rosbags/ · clips/.../runs/... · dispatch]
    MC_SDK[MC aig_sdk__*]
    MC_LEG[MC aig_rosbag__* 遗留]
    APP[(hmi/data/app.db<br/>用户 Taxonomy 校核 Dataset 平台表)]
    LOCAL[(hmi_runtime hmi.db<br/>+ artifacts/ + oss/)]
  end

  subgraph product [产品 HMI]
    BE[FastAPI :8000]
    FE[React Vite :5173]
  end

  BAG --> UP
  UP --> WORKER
  UP --> OSS
  WORKER --> SDK
  SDK --> LOCAL
  OSS --> DW
  DW --> OSS
  DW --> MC_SDK
  OSS --> LEG
  LEG --> MC_LEG
  LOCAL --> APP
  APP --> BE
  LOCAL --> BE
  MC_SDK --> BE
  MC_LEG --> BE
  OSS --> BE
  BE --> FE
```

---

## 2. 平台内核（DataType）

三层底座 + 内部 Sample。UI 主路径：**源湖入库 → 管线管理多选开跑**（自动 `create_sample` + `create_run`），不手搓 Sample。

```mermaid
flowchart LR
  subgraph lake [源湖]
    S[platform_source<br/>kind + collection_id<br/>与类型解绑]
  end

  subgraph recipe [数据类型配方]
    DT[platform_data_type<br/>slots / preprocess / products<br/>stages.label·embed / bbox / taxonomy]
  end

  subgraph run [开跑]
    SM[platform_sample 内部]
    R[platform_run]
    PF[preflight kinds/slots]
  end

  subgraph cache [产物缓存]
    P[platform_product<br/>cache_key = input_ids + op_id + params]
    L[lineage API]
  end

  S --> PF
  DT --> PF
  PF --> SM --> R
  R --> P
  P --> L
```

### 2.1 内置配方

| id | taxonomy | 总览视图 | label | 说明 |
|----|----------|----------|-------|------|
| `oms_cabin` | oms | cabin_timeline | SDK default | 真多模舱内 |
| `ivi_ui_stub` | ivi_ui_stub | frame_gallery_bbox | off | **占位**，勿宣称已完成 |
| `audio_array_spec` | audio_nvh（**draft** `audio_nvh-v2`） | audio_nvh_timeline | **nvh_sem_ast** | 阵列频谱 + AST L6 |

**勿 publish `audio_nvh-v2`。**

### 2.2 开跑绑定

```mermaid
sequenceDiagram
  actor U as 用户
  participant FE as PipelineManagePage
  participant API as POST /api/platform/runs
  participant Store as platform/store
  participant Worker as local_sdk_worker

  U->>FE: 选 DataType + 多选源
  FE->>API: source_ids + data_type_id
  API->>Store: preflight
  Store->>Store: create_sample + create_run
  API-->>FE: run_id
  Worker->>Worker: oms_cabin → SDK<br/>或 audio_array_spec → STFT/Mel/AST
  Worker->>Store: lookup_or_record_product
```

代码：`hmi/backend/hmi/platform/`（`router.py` / `store.py` / `recipe.py` / `run_bind.py`）。

---

## 3. SDK v1 阶段与产物

```mermaid
flowchart LR
  BAG[bag] --> IN[ingest]
  IN --> EX[extract]
  EX --> BB[bbox 可选]
  BB --> EN[encode]
  EN --> ASR[asr]
  ASR --> PV[preview]
  PV --> LB[label]
  LB --> EM[embed]
  EM --> UP[upload]
  UP --> MC[mc_write Driver]
  MC --> DP[dispatch Driver]
```

OSS 树（**新 run 禁止** `parsed/` `aligned/` `ai/`）：

```text
clips/{clip_id}/runs/{run_id}/
├── run.json                 # layout_version: sdk_v1
├── labels.jsonl
├── fusion_embeddings.jsonl
├── clip_videos.jsonl
├── asr.jsonl
├── bboxes.jsonl             # 可选
├── preview/
│   ├── manifest.json
│   ├── clip_preview_camera*.mp4
│   └── audio.wav
└── _sdk_work/               # 中间态，非节点间 IPC
```

`clip_id = sha256:{bag 内容 hex}`（`shared/clip_id.py`）。`run_id` = UUID。

---

## 4. 云端：单 Driver hybrid（生产）

粘贴文件：`pipeline/dataworks/bundled/sdk_pipeline_driver_node.py`。

```mermaid
flowchart TB
  subgraph driver [Driver PyODPS 节点]
    DISC[discover 扫 rosbags/]
    HASH[DPE apply_chunk 算 bag hash]
    EXPV[DPE apply_chunk extract+preview]
    AI[MaxFrame AI asr/label/embed<br/>ai_media_mode=oss_url]
    WR[写 run.json + aig_sdk__ + dispatch]
  end

  subgraph dpe [DPE Worker 镜像]
    MOUNT[@with_fs_mount OSS]
    ROS[rosbags + ffmpeg + SDK dpe extra]
  end

  OSS_BAG[OSS rosbags/*.bag 原地读 不拷贝] --> HASH
  HASH --> EXPV
  EXPV --> AI
  AI --> WR
  WR --> OSS_RUN[OSS clips/.../runs/]
  WR --> MC[aig_sdk__*]
  WR --> MAN[pipeline/dispatch/latest.json]
  dpe --> EXPV
```

| 禁止 | 替代 |
|------|------|
| DPE UDF 里 `@dataclass` / 自定义 class | dict / list / 内置类型 |
| bag 从 incoming 拷到 clips/raw | `rosbags/` + `bag_oss_key` |
| PyODPS 节点输出参数传 clip_id | OSS dispatch manifest |
| 把业务 `.py` COPY 进镜像再 subprocess | 节点粘贴整文件 |
| 新功能走 Job1–4 多节点 SDK | 单 Driver；多节点仅应急 |

提交前：`py -3 pipeline/scripts/check_dpe_nodes.py`。

---

## 5. HMI 双数据源

```mermaid
flowchart TB
  UI[侧栏 本地模式 / 在线模式]
  CFG[GET/POST /api/config/data-source]
  FAC[hmi/router.py 工厂]

  UI --> CFG
  CFG --> FAC

  FAC -->|local| LSQL[hmi.db + artifacts + 本地 oss/]
  FAC -->|cloud| MC[MaxCompute + 真 OSS 签名 URL]

  subgraph pollers [lifespan 后台线程 无 Celery]
    W1[local_sdk_worker 仅 local]
    W2[oss_sync_poller 读 dispatch]
    W3[cloud_bag_trigger_poller 仅 cloud]
  end
```

| | local | cloud |
|--|-------|-------|
| Clip/检索 | SQLite `hmi.db` | MC |
| 媒体 | `artifacts/` + `oss/` | OSS |
| `POST /api/platform/sources` | 允许 | 拒绝 |
| `local_sdk_worker` | 默认开 | 关 |
| 源湖上传 | 本机 | 走云管线 |

测试开关：`HMI_TEST_MODE` 才允许 UI 切 local。

---

## 6. HMI 信息架构（前端路由）

```mermaid
flowchart TB
  HOME["/ DataType 列表"]
  EDIT["/data-types/:id/edit admin"]
  WS["/w/:dataTypeId 工作区总览"]
  LAKE["/lake 源湖入库 + OSS Tab"]
  PIPE["/pipeline 开跑 / 绑定"]
  TAX["/taxonomy Hub"]
  CLIP["/clips/:clipId 时间轴"]
  REV["/review 校核"]
  DS["/datasets"]
  ADM["/admin/*"]

  HOME --> WS
  HOME --> EDIT
  WS --> CLIP
  LAKE --> PIPE
  PIPE --> WS
```

检索必须先进入 `/w/:dataTypeId`，**禁止跨类型混合命中**。

---

## 7. 两套 SQLite

```mermaid
erDiagram
  APP_DB ||--o{ USERS : auth
  APP_DB ||--o{ TAXONOMY_VERSION : hub
  APP_DB ||--o{ REVIEW : v2
  APP_DB ||--o{ DATASET : snapshot
  APP_DB ||--o{ PLATFORM_SOURCE : lake
  APP_DB ||--o{ PLATFORM_DATA_TYPE : recipe
  APP_DB ||--o{ PLATFORM_RUN : run
  APP_DB ||--o{ PLATFORM_PRODUCT : cache

  HMI_DB ||--o{ DIM_CLIP : clip
  HMI_DB ||--o{ PIPELINE_RUN : steps
  HMI_DB ||--o{ FACT_CLIP_LABEL : labels
  HMI_DB ||--o{ FACT_FRAME : timeline
```

| 文件 | 路径 | 内容 |
|------|------|------|
| **app.db** | `hmi/data/app.db` | 用户、Taxonomy、校核、Dataset、**platform_*** |
| **hmi.db** | `hmi/data/hmi_runtime/`（或 hmi_local） | dim_clip、fact_*、pipeline_* |
| parse/timeline | `pipeline/data/*.db` | 本地 Job1 遗留，非 HMI 主库 |

---

## 8. NVH / AST（HMI worker，不在 SDK label 阶段）

SDK `label` = OMS Omni → `labels.jsonl`。阵列 L6 是 **HMI 配方阶段** `nvh_sem_ast`。

```mermaid
flowchart LR
  DAT[HEAD.dat / 阵列 WAV] --> STFT[STFT / Mel / 1/3oct / SPL]
  STFT --> DER[nvh_deriver 客观 L2]
  DER --> AST[nvh_ast Gong AST + AudioSet-527]
  AST --> L6[只写 nvh.sem.noise_category / noise_sources]
  L6 --> LAB[fact_clip_label + platform_product]
```

| 约束 | 说明 |
|------|------|
| 权重 | `hmi/data/models/ast/pytorch_model.bin` 或 `HMI_NVH_AST_WEIGHTS`（gitignore） |
| 禁止 | 把管线 64-bin Mel 直接喂 AST；Gong 源码 wget；未峰值归一化的 PCM |
| 回退 | 缺 torch / 权重 → `heuristic_fallback` |
| 下一工单 | UI-NVH-REVIEW-SAVE 人工写回 L6 |

---

## 9. Taxonomy Hub（M10）

```mermaid
flowchart LR
  YAML[oms / audio_nvh YAML] --> VER[label_taxonomy_version]
  VER --> TREE[nodes]
  VER --> CTX[context / coverage]
  VER --> DIFF[diff / impact]
  VER --> LIN[clone 血缘]
  PROP[proposals] --> DRAFT[approve → draft]
  DRAFT -.->|禁止自动| PUB[publish]
```

提案合入 draft **不得自动 publish**。洞察只读，不得写回 clip 标签或批量重打标。

---

## 10. Agent / 文档入口

```mermaid
flowchart TD
  START[新会话] --> H[docs/HANDOVER.md]
  H --> C[project-management/CURRENT.md]
  C --> SK{任务类型}
  SK -->|不知从哪下手| S1[skill rosbag-onboarding]
  SK -->|DataType/源湖| S2[skill rosbag-platform-kernel]
  SK -->|改 UI/API| S3[skill rosbag-hmi-dev]
  SK -->|云管线/DPE| S4[skill rosbag-sdk-pipeline]
  SK -->|查 OSS/MC| S5[skill cloud-cli-ops]
  S1 --> DONE[实现 + acceptance A/A-E2E/H]
  S2 --> DONE
  S3 --> DONE
  S4 --> DONE
  S5 --> DONE
```

alwaysApply 规则：`project-progress-handoff.mdc` · `pipeline-architecture.mdc` · `maxframe-dpe-cloud.mdc`。

---

## 11. 域内部署（POC）

```mermaid
flowchart LR
  ROOT[仓库根] --> BUILD[save-image.ps1]
  BUILD --> TAR[offline/*.tar]
  TAR --> SFTP[sftp :60022 堡垒机]
  SFTP --> POC[智能座舱POC]
  POC --> LOAD[docker load]
  LOAD --> RUN["docker run -p 8012:8000"]
```

口令不入库。步骤见 [`deploy-intranet-cicd.md`](deploy-intranet-cicd.md)。
