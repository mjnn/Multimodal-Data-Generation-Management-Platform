# SDK 优先管线：OSS 目录与 MC 重构设计

**状态**：草案（2026-07-27）  
**决策**：所有管线产物与目录结构以 **SDK `real_data` 批次** 为准；原 clip-omni v2（Job1–Job4、`parsed/` / `aligned/` / `ai/`）与对应 MC 宽表 **废弃重做**，不做双轨长期并存。

---

## 1. SDK 真相源（每个 run）

与 `hmi/data/real_data/pipeline_latest/README.md` 一致，一个 **run 文件夹**（如 `2026-07-23_14-12-31/`）包含：

| 相对路径 | 说明 |
|----------|------|
| `labels.jsonl` | 单行：clip 时间范围、OMS `labels`、`asr_text` / `asr`、`scene_summary`、模型名 |
| `fusion_embeddings.jsonl` | 单行：clip 级融合向量 |
| `clip_videos.jsonl` | 单行：多路 `clip_video_paths`、`encoded_cameras`、`audio_path` |
| `work/output/clips/output_0000/clip_preview_camera{N}.mp4` | SDK 预览 MP4（通常 3 路） |
| `work/output/clips/output_0000/audio.wav` | 片段音频 |

可选批次级：`run_summary.json`（不入 clip run 树，仅运维）。

**不再作为管线主产物**：rosbag 全帧 JPEG、`parsed/events.jsonl`、`aligned/timeline.json`、多模型 `ai/labels_*.json` 等 v2 文件。

---

## 2. OSS 桶级布局（精简后）

| 前缀 | 用途 |
|------|------|
| `rosbags/` | 原始 `.bag`（可选；Job0 扫描） |
| `clips/` | **SDK run _bundle**（见 §3） |
| `reviews/` | HMI 人工校核（不变） |
| `config/taxonomy/` | 标签树（不变） |
| `pipeline/dispatch/latest.json` | 调度 + 同步触发（字段见 §5） |
| `datasets/` | 训练集导出（不变） |
| `legacy/` | 旧 v2 `clips/.../parsed|aligned|ai` 只读归档 |

---

## 3. Clip run OSS 树（`layout_version: sdk_v1`）

**Object 前缀**（与现 config 一致）：

```text
clips/{clip_id}/runs/{run_id}/
```

`clip_id`：内容 id，推荐 `sha256:{hex}`；real 导入可保留 `sha256:real_{run_dir}`。  
`run_id`：UUID，与 MC `pipeline_run.run_id` 一致。

### 3.1 必传对象（与 SDK 同构 + HMI 索引）

```text
clips/{clip_id}/runs/{run_id}/
├── run.json                      # 注册表（§3.2）
├── labels.jsonl                  # SDK 原样
├── fusion_embeddings.jsonl
├── clip_videos.jsonl
└── preview/                      # 媒体（可由 SDK 路径拷贝/重命名，不要求保留 work/ 深度）
    ├── manifest.json             # HMI 播放清单（§3.3）
    ├── grid.mp4                  # ffmpeg 合成（多路时）
    ├── camera0.mp4               # 源自 clip_preview_camera0.mp4
    ├── camera1.mp4
    ├── camera2.mp4
    ├── camera3.mp4               # 有几路写几路
    └── audio.wav
```

**刻意省略**：`parsed/`、`aligned/`、`ai/`、`job2/`、`job3/`、`job4/`。

### 3.2 `run.json`（最小注册表）

```json
{
  "layout_version": "sdk_v1",
  "clip_id": "sha256:real_2026-07-23_14-12-31",
  "run_id": "uuid",
  "ds": "20260727",
  "source_run_dir": "2026-07-23_14-12-31",
  "bag_oss_key": "rosbags/.../output.bag",
  "sdk_files": {
    "labels": "labels.jsonl",
    "embeddings": "fusion_embeddings.jsonl",
    "videos": "clip_videos.jsonl"
  },
  "preview_manifest": "preview/manifest.json",
  "completed_at": "2026-07-27T05:00:00Z"
}
```

### 3.3 `preview/manifest.json`（HMI）

与现 `parsed/preview/manifest.json` 字段兼容，仅 **相对路径改为 `preview/`**：

- `mode`: `"mp4"`
- `fps`, `frame_count`, `start_time_ns`, `end_time_ns`
- `grid_relpath`: `preview/grid.mp4`
- `cameras[]`: `{ "camera", "relpath", "frame_count" }`

同步到本地时可 **镜像到** `artifacts/.../preview/`（不再写 `parsed/preview/`）。

---

## 4. MaxCompute 表（重做）

**表前缀建议**：`aig_sdk__`（新项目）或清空重建 `aig_rosbag__`（同 project 内需迁移脚本）。  
**分区**：仍用 `ds`（入库日 yyyyMMdd）。

### 4.1 保留并简化

| 表 | 说明 |
|----|------|
| `dim_clip` | `clip_id`, `clip_dir_name`, `content_hash`, `bag_oss_key`, `active_run_id`, 时间戳 |
| `pipeline_run` | `run_id`, `clip_id`, `status`, `layout_version`（固定 `sdk_v1`）, `label_granularity`（固定 `clip`）, 时间戳 |
| `clip_parse_summary` | 从 `labels.jsonl` + `clip_videos.jsonl` 填：`start/end/duration`、相机数、无 `message_count` 亦可 |
| `fact_clip_label` | 从 `labels.jsonl` 展平 `labels` → `labels_json`；`model_version`；可选 `labels_jsonl_oss_key` |
| `fact_clip_embedding` | 从 `fusion_embeddings.jsonl` |
| `fact_audio_segment` | 从 `labels.jsonl` 的 `asr_text`（clip 级一段即可）；`audio_relpath` 指向 `preview/audio.wav` |

### 4.2 删除或不再写入（v2 专用）

- `fact_message_timeline`
- `fact_frame`（大规模帧索引）
- `fact_audio_chunk`
- `fact_event`（除非 SDK 后续单独输出 event jsonl）
- `fact_sample_policy`, `fact_sample_sync_group`
- `fact_image_label`（帧级打标）
- `fact_embedding`（对象级向量）
- `pipeline_step` 的 job1–job4 细粒度（见 §4.3）

### 4.3 调度步骤（替代 Job1–Job4）

`pipeline_step` 可收缩为 SDK 阶段（每 run 一条 ds 分区多行）：

| step_id | 含义 |
|---------|------|
| `sdk_discover` | bag / run 登记 |
| `sdk_infer` | labels + embedding + videos jsonl 就绪 |
| `sdk_upload` | OSS run 树写完整 |
| `sdk_mc_write` | MC 事实表写入 |
| `sdk_dispatch` | dispatch manifest 更新 |

HMI 总览「管线进度」读上述五步，不再展示 job1_parse / job2_labeling 等。

### 4.4 MC 写入 Job（新）

**单节点**：`sdk_mc_write_node.py`（替代 job1_mc_write + job4_mc_write）

1. 读 OSS `run.json` + 三个 jsonl（或读 MC 外表 staging）。
2. INSERT/overwrite 分区行：`dim_clip`, `pipeline_run`, `clip_parse_summary`, `fact_clip_label`, `fact_clip_embedding`, `fact_audio_segment`。
3. 不读 JPEG、不写帧表。

---

## 5. `pipeline/dispatch/latest.json`

```json
{
  "action": "run",
  "layout_version": "sdk_v1",
  "clip_id": "sha256:...",
  "run_id": "uuid",
  "ds": "20260727",
  "bag_oss_key": "rosbags/...",
  "run_oss_prefix": "clips/sha256:.../runs/uuid/",
  "dispatched_at": "2026-07-27T05:00:00Z",
  "pipeline_version": "sdk_v1"
}
```

HMI `oss_sync_poller` → `sync_hmi_local.py`：

1. 拉 MC 表（§4.1 列表）。
2. OSS 下载前缀：`labels.jsonl`, `fusion_embeddings.jsonl`, `clip_videos.jsonl`, `run.json`, `preview/**`。
3. 本地 `ingest_sdk_run()`：写 SQLite + 可选从 jsonl 生成校核 hints（内存或 `preview/.hints.json`，**不上 OSS**）。

---

## 6. HMI 本地镜像

| 层级 | 策略 |
|------|------|
| SQLite | 与 MC §4.1 同构；去掉帧级表或留空 |
| Artifacts | `artifacts/clips/{safe_clip_id}/runs/{run_id}/preview/` + 根目录三个 jsonl 副本 |
| API | `get_timeline_meta` 只读 `preview/manifest.json`；ASR 来自 DB |
| 兼容 | 只读 fallback：`parsed/preview/`、`ai/labels_merged.json` 标记 deprecated，6 个月内删除 |

---

## 7. 上传路径（real_data → OSS）

1. 登记 `clip_id` / `run_id` / `ds`（与 MC 一致）。
2. 上传 §3.1 文件（媒体可先本地 ffmpeg grid 再传）。
3. 写 `run.json`。
4. 跑 `sdk_mc_write` 或使用 `pipeline/scripts/ingest_sdk_run_to_mc.py`。
5. 更新 `pipeline/dispatch/latest.json`。

仓库内 **`hmi/scripts/import_real_data_clips.py`** 产出 sdk_v1 树（不再写 `parsed/aligned/ai`）。

---

## 8. 迁移与清理

1. 现有 OSS `clips/**/parsed|aligned|ai` → 复制到 `legacy/clips/...`（可选）。
2. MC：新 DDL `pipeline/sql/maxcompute/aig_sdk__ddl.sql`；旧表 rename `_deprecated` 或 drop（需业务确认）。
3. DataWorks：下线 job1–job4 节点文档改指 `docs/sdk-first-pipeline-design.md`。
4. 代码删除优先级：`oss_layout` v2 常量、`upload_clip_preview_to_oss` 的 v2 前缀、`ai_artifacts` 对 `ai/*.json` 的硬依赖。

---

## 9. 实现分期（建议）

| 阶段 | 交付 |
|------|------|
| P0 | ✅ 本文档 + `oss_layout` + `import_real_data` → sdk_v1 本地树 |
| P1 | ✅ `sdk_ingest.py`、`sync_hmi_local`（`aig_sdk__` 表集）、hints 读 `labels.jsonl`、SDK 步骤 UI、`upload` / `publish_sdk_dispatch` / `ingest_sdk_run_to_mc` |
| P2 | 在 ODPS 执行 `aig_sdk__ddl.sql` 并跑通 MC ingest + dispatch 触发 sync |
| P3 | 删 v2 路径与 dataset 内 parsed/aligned 打包 |

---

## 10. 已定稿（2026-07-27）

- **clip_id**：`sha256:{bag 内容 SHA256 hex}`（非 `sha256:real_{目录名}`）。
- **preview 媒体**：保留 SDK 文件名（`clip_preview_camera*.mp4`、`audio.wav`），仅在 `preview/manifest.json` 的 `relpath` 中引用。
- **MC 表前缀**：新建 **`aig_sdk__`**（见 `sql/maxcompute/aig_sdk__ddl.sql`）。
