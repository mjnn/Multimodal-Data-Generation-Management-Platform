# Dataset 交付 Schema（训练侧契约）

| 字段 | 值 |
|------|-----|
| schema_version | **1.0** |
| 维护 | M7.1；与 `hmi/backend/hmi/dataset/export.py` 中 `PACKAGE_VERSION` / `schema_version` 同步 |
| 权威链 | PRD §7.1 > 本文档 > 快照内 `meta.json` |

> **平台边界**：本文档描述「数据是什么、如何对齐、如何审计」。tensor 化、label encoding、DataLoader 实现均在**平台外**。

---

## 1. 快照包结构

下载物为 `dataset.zip`（或 OSS 等价目录）。由 `export_preset` 决定内容：

| 文件 | minimal | full | MIME |
|------|---------|------|------|
| `特征.jsonl` | ✓ | ✓ | NDJSON |
| `目标.jsonl` | ✓ | ✓ | NDJSON |
| `特征.parquet` | 可选 | 可选 | Parquet（`include_parquet=true`） |
| `目标.parquet` | 可选 | 可选 | Parquet |
| `meta.json` | ✓ | ✓ | JSON |
| `README.txt` | ✓ | ✓ | text |
| `解析数据.jsonl` | — | ✓ | NDJSON |
| `clips/{clip_id}/runs/{run_id}/**` | — | ✓ | 混合 |

OSS 路径（未打包时）：`datasets/{snapshot_id}/X.jsonl`、`y.jsonl`、`parsed.jsonl`、`meta.json`、`dataset.zip`。

---

## 2. 对齐规则（必读）

| 规则 | 说明 |
|------|------|
| **R8** | 同一行的 `(clip_id, run_id)` 中，X 与 y 必须来自**同一 pipeline run** |
| **R7** | 默认仅含 `review_status=reviewed` 且 field review 完成的 clip |
| **R2** | y 以校核后 `clip_label_review.labels_json` 为准，非 AI 帧标签原始值 |
| **行对齐** | `特征.jsonl` 与 `目标.jsonl` 按 `(clip_id, run_id)`  join；行数可因单侧 skip 而不等，以 `meta.build_report` 为准 |
| **taxonomy** | y 中 key 为 taxonomy `node_id`（如 `L1.1.day_period`）；导出时附带 `taxonomy_version_id` / `taxonomy_version_code` |

---

## 3. `特征.jsonl`（X）

每行一个 JSON 对象：

```json
{
  "clip_id": "sha256:…",
  "run_id": "uuid",
  "x_json": { }
}
```

### 3.1 `x_json.schema = clip_embedding_v1`

clip 级单向量（优先）。

| 字段 | 类型 | 说明 |
|------|------|------|
| schema | string | 固定 `"clip_embedding_v1"` |
| vector | float[] | embedding 向量 |
| model_version | string? | Job4 / 模型版本 |
| dim | int | 向量维度 |
| aggregation_method | string? | 如 `clip_native`、`clip_omni` |

### 3.2 `x_json.schema = frame_embeddings_v1`

无 clip 级 embedding 时的回退：多帧/多对象向量列表。

| 字段 | 类型 | 说明 |
|------|------|------|
| schema | string | 固定 `"frame_embeddings_v1"` |
| items | array | 见下表 |

**items[] 元素：**

| 字段 | 类型 | 说明 |
|------|------|------|
| object_type | string | 如 `frame` |
| object_id | string | 如 `cam0:0` |
| timestamp_ns | int? | 对齐基准时间 |
| start_ns / end_ns | int? | 区间对象 |
| vector | float[] | 向量 |
| model_version | string? | |
| dim | int | |

---

## 4. `目标.jsonl`（y）

每行一个 JSON 对象：

```json
{
  "clip_id": "sha256:…",
  "run_id": "uuid",
  "y_json": { "L1.1.day_period": "night" },
  "taxonomy_version_id": "uuid",
  "taxonomy_version_code": "v2"
}
```

### 4.1 `y_json` 语义

| 情况 | 表示 |
|------|------|
| 正常枚举值 | string，符合 taxonomy `value_schema` |
| 校核置空 | key 缺失或值为 `null` / `""`（以 merge 逻辑为准） |
| 不确定 (`human_doubtful`) | 按 M6 merge 规则写入；训练侧需自行处理缺失类 |

### 4.2 不负责项（平台外）

- one-hot / multi-hot 编码
- 层级 taxonomy 展开
- 缺失值 imputation 策略

### 4.3 manifest 虚拟行（M8 · schema 1.1+）

过采样时同一物理 clip 可占多行：

| 字段 | 说明 |
|------|------|
| variant_id | `base` 或 `dup_{n}` 等；缺省视为 base |
| source_row_key | 指向原始 `(clip_id, run_id, base)` |
| aug_hint | `{type: platform_oversample, duplicate_index, balance_by_label}` |

**约束**：虚拟行 `y_json` 必须与 source 相同；不复制 parsed 二进制（仍指向同一 artifact）。

---

## 5. `解析数据.jsonl`（full preset）

每行一条 clip 的结构化索引（非二进制）：

```json
{
  "clip_id": "…",
  "run_id": "…",
  "ds": "YYYYMMDD",
  "parse_summary": { "start_time_ns", "end_time_ns", "duration_sec" },
  "manifest": { },
  "frames": [{ "camera", "frame_idx", "timestamp_ns", "image_path", "artifact_relpath" }],
  "events": [ ],
  "audio_segments": [{ "segment_id", "start_ns", "end_ns", "asr_text", "artifact_relpath" }],
  "aligned": { "timeline": { } }
}
```

二进制文件路径见 `artifact_relpath`，相对 `clips/{clip_id}/runs/{run_id}/`。

**时间对齐**：跨模态默认 ±200ms；以 rosbag `record_time_ns` 为基准（见管线架构约定）。

---

## 6. `meta.json`

| 字段 | 类型 | 说明 |
|------|------|------|
| snapshot_id | string | UUID |
| name | string? | 快照名称 |
| schema_version | string | 契约版本，当前 `1.0` |
| package_version | int | zip 文件布局版本（当前 `2`） |
| export_preset | string | `minimal` \| `full` |
| filter_snapshot | object | 创建时 filter_json 快照 |
| clip_count | int | 成功导出 clip 数 |
| line_count | int | X/y 行数 |
| taxonomy_summary | object? | `{version_id, version_code}` |
| embedding_summary | object? | `{schemas[], model_versions[]}` |
| build_report | object | 见 §7 |
| files | object | 包内文件名映射 |
| x_key / y_key / parsed_key / package_key | string? | OSS key |
| x_parquet_key / y_parquet_key | string? | Parquet OSS key（`parquet_available=true` 时） |
| include_parquet / parquet_available | bool | 创建选项 / 实际是否写出 Parquet |

---

## 6.1 Parquet 列布局（M7.5 · 可选）

**特征.parquet**：`clip_id`, `run_id`, `variant_id`, `x_schema`, `dim`, `model_version`, `vector`（clip 级）；`frame_embeddings_v1` 时 `x_json` 为 JSON 字符串。

**目标.parquet**：`clip_id`, `run_id`, `variant_id`, `taxonomy_version_*`, `y_json`，以及扁平 `label__{node_id}` 列（`.` 替换为 `__`）。

JSONL 仍为权威 manifest；Parquet 便于 pandas / Spark 批量读取。

---

## 6.2 导出顾问（M7.8 · preview）

`POST /api/datasets/preview` 响应含 `export_recommendation`：

| 字段 | 说明 |
|------|------|
| `suggested_export_preset` | `minimal` / `full` |
| `suggested_include_parquet` | 是否建议 Parquet |
| `suggested_batch` / `suggested_sample_size` | 超 10k 或过大时建议 |
| `reasons` | 可读依据列表 |
| `estimates` | JSONL 体积粗算 |
| `stats` | clip/行/标签列/embedding schema |

**边界**：仅建议，不自动改 y、不导出 `.pt`；用户可「采用建议」或手动覆盖。

---

## 7. `build_report`

| 字段 | 类型 | 说明 |
|------|------|------|
| skipped | array | `[{clip_id, run_id, reason}]` |
| skipped_by_reason | object | `{reason: count}` |
| warnings | string[] | 非致命警告 |

**skip reason 枚举（M7.2）：**

| reason | 含义 |
|--------|------|
| `no_clip_embedding` | 无 clip/frame embedding |
| `field_review_incomplete` | AI label 未全部 field-review |
| `review_status_excluded` | 非 reviewed 且未 admin include |
| `label_filter_mismatch` | 不满足 label_filters |
| `taxonomy_mismatch` | taxonomy_version 过滤不匹配 |

---

## 8. 规模化与 preset 选择

| 场景 | 建议 preset |
|------|-------------|
| 基于 embedding 的分类 / 探针 | **minimal** |
| 端到端多模态（自读图像/音频） | **full** |
| \>10k clip | 分批创建多个 snapshot；单快照上限 10k（O2） |

---

## 10. 版本演进

| schema_version | 变更 |
|----------------|------|
| 1.0 | M7 首版：meta build_report、export_preset、契约文档 |
| 1.1 | M8：manifest `variant_id` / `aug_hint`；meta augmentation / distribution / lineage |

不兼容变更须递增 `schema_version` 并在 `meta.json` 与本文档同步说明。

扩增 recipe 契约见 `docs/dataset-augmentation-recipe-schema.md`（M8）。

---

## 11. 示例加载（平台外）

参考 `examples/load_dataset_snapshot.py`（M7.6）。最小读取逻辑：

1. 解压 `dataset.zip`
2. 读 `meta.json` 确认 `schema_version`
3. 按 `(clip_id, run_id)` join `特征.jsonl` 与 `目标.jsonl`
4. 训练侧自行 `vector → Tensor`、`y_json → labels`

---

## 12. 相关文档

- PRD：`docs/prd-rosbag-labels.md` §7.1、R7、R8
- M4 实现：`docs/m4-implementation-notes.md`
- M6 field review：`docs/prd-review-v2.md` R-M6-3
- M7 实现：`docs/m7-implementation-notes.md`
- M8 扩增治理：`docs/m8-implementation-notes.md`
- Aug recipe：`docs/dataset-augmentation-recipe-schema.md`
