# Rosbag 解析打标管线 — 全流程说明（clip-omni v2）

> 本文档与 `WORKFLOW.md`（编排细节）、`PARAMETERS.md`（参数表）互补。  
> **当前推荐管线**：clip-omni v2（十节点 + HMI 校核）。

---

## 一、管线目标

将车载/机器人 **ROS bag** 经云端批处理转为 **clip 级** 结构化资产：

| 阶段 | 产出 | 用途 |
|------|------|------|
| **发现** | clip 元数据入库 | 桶内 bag 清单、内容 hash 唯一 ID |
| **解析 (Job1)** | 四路相机帧、音频、事件 | 多模态对齐基准 |
| **对齐 (Job1 align)** | 统一时间轴 + sync manifest | 整 clip 模型输入 |
| **双模型打标 (Job2 + Job3)** | 主/副模型标签 JSON | AI 预标签 + 一致性比对 |
| **合并 (Job4)** | `labels_merged.json` + `consensus_meta.json` | HMI 主读；争议标记 |
| **向量 (Job2 embed)** | clip 级 embedding | 检索 / 训练特征（x） |
| **校核 (HMI)** | 人工修订标签 → `reviews/` | 训练目标（y） |

**设计原则**：

- **内容寻址**：`clip_id = sha256:{hex}`
- **版本化 run**：每次 pipeline 一个 `run_id`（UUID），`dim_clip.active_run_id` 指向生效版本
- **双模型共识**：主模型（job2）+ 副模型（job3）→ job4 合并；低一致率字段留空待人工
- **AI / 人工分离**：管线只写 `clips/.../ai/`；人工只写 `reviews/`
- **OSS 为算子间总线**；MC 存索引与 clip 级事实表

---

## 二、十节点编排（DataWorks 工作流）

### 2.1 节点清单

| # | 节点 | 职责 | 运行时 |
|---|------|------|--------|
| 0 | `job0_discover` | 扫描 OSS `rosbags/`，hash bag，写 `dim_clip` | MaxFrame DPE |
| 0b | `job0_dispatch` | 挑 clip/run，写 dispatch manifest | Driver |
| 1a | `job1_parse` | 读 bag，写 OSS `parsed/` | MaxFrame DPE |
| 1b | `job1_mc_write` | 读 payload，写 MC 事实表 | Driver |
| 1c | `job1_align` | 多模态对齐，写 `aligned/` | Driver stub / DPE |
| 2a | `job2_labeling` | **主模型**整 clip 打标 | DPE + MaxFrame AI |
| 2b | `job2_embedding` | clip 向量化 | DPE + MaxFrame AI |
| 3 | `job3_labeling_by_other_model` | **副模型**整 clip 打标 | DPE + MaxFrame AI |
| 4a | `job4_label_merge_and_compare` | 双模型比对合并 | Driver |
| 4b | `job4_mc_write` | 写 `fact_clip_label` / `fact_clip_embedding` | Driver（待实现） |

### 2.2 依赖拓扑

```
job0_discover → job0_dispatch
  → job1_parse → job1_mc_write → job1_align
  → job2_labeling ──┐
  → job2_embedding ─┼→ job4_label_merge_and_compare → job4_mc_write
  → job3_labeling_by_other_model ─┘
```

Job2 三路（labeling / embedding / job3）可在 align 完成后 **并行**；job4 合并需等两个打标完成。

### 2.3 状态机

| 状态 | `active_run_id` | 含义 |
|------|-----------------|------|
| 已发现 | `NULL` | Job0 写入，待 Job1 |
| 已解析生效 | UUID | Job1 写 MC 完成 |

`pipeline_step`（v2 六步）：  
`job1_parse` → `job1_align` → `job2_labeling` → `job2_embedding` → `job3_labeling_by_other_model` → `job4_label_merge_and_compare`

---

## 三、OSS 目录约定

**桶**：`rosbag-labels-pipeline-bucket2`

```
rosbag-labels-pipeline-bucket2/
├── rosbags/
│   └── {clip_dir_name}/output.bag
├── config/
│   └── taxonomy/                    # 发布版标签树 + latest.json
├── pipeline/
│   └── dispatch/latest.json         # pipeline_version=clip_omni_v2
├── clips/
│   └── {clip_id}/
│       └── runs/{run_id}/
│           ├── parsed/                # Job1
│           ├── aligned/               # Job1 align
│           └── ai/                    # Job2~4（AI only）
│               ├── labels_primary.json      # job2_labeling
│               ├── labels_secondary.json    # job3
│               ├── labels_merged.json       # job4（HMI 主读）
│               ├── consensus_meta.json      # job4 争议元数据
│               ├── labels.json              # job4 别名
│               └── embedding.json           # job2_embedding
├── reviews/                           # HMI 人工校核（非管线）
│   └── clips/{clip_id}/runs/{run_id}/
│       ├── labels.json
│       └── meta.json
├── datasets/                          # 训练集 export
└── legacy/                            # 旧版 job2/3/4 归档
```

---

## 四、MaxCompute 表（MC）

**项目**：`rogbag_label_pipline` · **表前缀**：`aig_rosbag__` · **分区**：`ds=yyyyMMdd`

| 表 | 写入 Job | 作用 |
|----|----------|------|
| `dim_clip` | Job0 / Job1 mc_write | Clip 维度、`active_run_id` |
| `pipeline_run` | Job1 mc_write | Run 生命周期 |
| `pipeline_step` | 各 step 节点 | v2 六步状态 |
| `fact_frame` / `fact_audio_chunk` / `fact_event` | Job1 mc_write | 解析事实 |
| `fact_clip_label` | job4_mc_write | **Clip 级** AI/合并标签 |
| `fact_clip_embedding` | job4_mc_write | **Clip 级** 向量 |

Legacy 表（`fact_image_label` · `fact_embedding` 等）仍保留，供旧 run 查询。

---

## 五、参数传递

工作流级参数示例：

```properties
oss_bucket=rosbag-labels-pipeline-bucket2
pipeline_version=clip_omni_v2
cloud_region=cn_shanghai
table_prefix=aig_rosbag__
ds=${bizdate}
agreement_threshold=0.7
primary_model=
secondary_model=
embed_model=
```

定时任务：`clip_id` / `run_id` 留空 → `job0_dispatch` 写 manifest → 下游 `resolve_pipeline_context()`。

详见 `DISPATCH_PARAMS.md` · `workflow-params.example`。

---

## 六、Job 阶段详解（v2）

### Job0 — 发现 + 调度

- Discover：列举 `rosbags/`，SHA256 → `dim_clip`
- Dispatch：选待处理 clip，写 `pipeline/dispatch/latest.json`（含 taxonomy 指针）

### Job1 — 解析 + 对齐

- **Parse**：DPE `parse_bag` → `parsed/`
- **MC write**：灌入 frame/audio/event 表
- **Align**：从 parsed 生成 `aligned/timeline.json` + `sync_manifest.jsonl`

### Job2 — 主模型打标 + 向量

- **Labeling**：读 `aligned/` + taxonomy → `ai/labels_primary.json`
- **Embedding**：读 `aligned/` → `ai/embedding.json`

### Job3 — 副模型打标

- 读 `aligned/` + taxonomy（同 job2）
- 写 `ai/labels_secondary.json`

### Job4 — 合并 + 入库

- **Merge**：比对 primary/secondary；一致率 ≥ 0.7 合并（冲突取 primary）；否则争议字段留空
- **MC write**（待实现）：读 `ai/labels_merged.json` + `embedding.json` → MC

### HMI — 校核（工作流外）

- 读 `labels_merged.json` / `consensus_meta.json` 入队校核
- `gate_passed=false` 时校核页高亮争议字段
- 校核员保存 → export 到 `reviews/`
- 数据集：特征 = embedding，目标 = 校核后 labels

---

## 七、本地 vs 上云

| 维度 | 本地 HMI | 上云（本管线） |
|------|----------|----------------|
| 入口 | `hmi/data/hmi_local/` | OSS + MC |
| AI 产物 | `artifacts/.../ai/` | OSS `clips/.../ai/` |
| 校核 | SQLite `clip_label_review` | + OSS `reviews/` export |
| 同步 | `sync_hmi_local.py` | MC + OSS → 本地 |

---

## 八、运维与验收

```bash
py -3 pipeline/scripts/init_oss_layout.py
py -3 pipeline/scripts/verify_pipeline_run.py --clip-id sha256:... --run-id <uuid>
py -3 pipeline/scripts/sync_hmi_local.py --clip-id sha256:... --run-id <uuid>
py -3 archive/legacy-scripts/mock_pipeline_artifacts.py --all --reset
py -3 pipeline/scripts/seed_demo_clip_data.py --reset
```

```sql
SELECT step_id, status FROM aig_rosbag__pipeline_step
WHERE run_id='<uuid>' AND ds='${bizdate}' ORDER BY step_id;
-- 期望：job1_parse, job1_align, job2_labeling, job2_embedding,
--       job3_labeling_by_other_model, job4_label_merge_and_compare
```

**Demo clip 场景**（mock 脚本生成）：

| clip | gate | 说明 |
|------|------|------|
| `demo_morning_city` | fail | day_period 争议 |
| `demo_holiday_mall` | fail | is_holiday 争议 |
| `demo_afternoon_park` | pass | 双模型一致 |
| `demo_night_highway` | pass | 已校核 |
| `demo_unlabeled` | n/a | 仅 parsed/aligned |

---

## 九、演进路线

| 阶段 | 内容 |
|------|------|
| ✅ 已完成 | v2 OSS 布局、双模型打标/合并、HMI 争议高亮、dispatch 六步、align/label stub |
| 🔄 进行中 | `job4_mc_write` v2、完整 MaxFrame DPE 打标/向量节点 |
| ⏳ 待做 | 真实 Omni/VL 模型联调；legacy run 迁移至 `legacy/` |

---

## 相关文档

| 文档 | 内容 |
|------|------|
| `pipeline/dataworks/WORKFLOW.md` | 节点粘贴、连线、流程图 |
| `pipeline/dataworks/WORKFLOW_COMPLETE.md` | 完整数据流与 idle 逻辑 |
| `pipeline/dataworks/DISPATCH_PARAMS.md` | OSS dispatch 专篇 |
| `pipeline/dataworks/workflow-params.example` | 参数模板 |
| `pipeline/dataworks/PARAMETERS.md` | 全参数手册（含 legacy 章节） |

## 附录：Legacy 十节点

帧级 sample/ASR/label/embed 管线已废弃；`job2_clip_omni` 单体节点已 deprecated。  
验收：`verify_pipeline_run.py --legacy`。详述见 `WORKFLOW_COMPLETE.md` 附录 A。
