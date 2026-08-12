# DataWorks × OMS Multimodal SDK

> 目标：**云端推理前步骤**（解析、ASR、预览、Omni 打标、融合向量）由 **同一 SDK** 完成，产物对齐 **`sdk_v1` OSS** 与 **`aig_sdk__` MC**。  
> **推荐云上路径（2026-08）**：单节点 **`sdk_pipeline_driver`**（`apply_chunk` + `stages` + UDF 内 `MODEL_BACKEND=mc`）。多节点 `sdk_*` 已冻结，仅参考/回退。  
> **本机测能力**：`piplinesdk/examples/`（`run_stages`）。详设见仓库 `docs/sdk-v1-cloud-e2e-runbook.md`。

---

## 0. 单 Driver（推荐）

| 项 | 路径 |
|----|------|
| 粘贴包 | `pipeline/dataworks/bundled/sdk_pipeline_driver_node.py`（`bundle_sdk_pipeline_driver.py` 生成） |
| 参数模板 | `pipeline/dataworks/workflow-params-sdk-pipeline-p0.example` |
| SDK 编排 | `oms_multimodal.run_stages` / `parse_stages` |

P0 探针：`stages=extract,asr`，`batch_rows=1`，`model_backend=mc`。失败可同节点改 `model_backend=api`。

### UDF 与 `apply_chunk` 并发（教学示例）

带中文注释的粘贴示例：

`piplinesdk/examples/05_dpe_apply_chunk_concurrency.py`

覆盖：**发现 bag**（Driver 列 OSS → DPE `apply_chunk` 算 SHA256 → `clip_id`）以及 pipeline `apply_chunk` 并发参数。

| 概念 | 含义 |
|------|------|
| Driver | PyODPS3 节点进程：组参数、**列举 bag**、建 DataFrame、`new_session`、提交任务、`fetch` 结果 |
| DPE Worker | 远端真正执行 UDF 的进程：挂载 OSS、**hash bag**、跑 `run_stages` |
| UDF | 节点脚本里定义、被 MaxFrame 发到 Worker 的函数；**禁止** `@dataclass` / 自定义 `class`，只用 `dict`/`list`/内置类型 |
| 发现（discover） | `list_bag_keys_from_oss` + `build_hash_chunk_udf`；`discover_mode=auto\|keys\|demo` |
| `apply`（`axis=1`） | **一行调用一次** UDF，入门简单 |
| `mf.apply_chunk` | **一次吃多行**；发现用 `hash_batch_rows`，流水线用 `batch_rows` |
| `dpe_parallel` + `mf.rebalance` | 把输入拆成约 N 个分区，便于多 Worker 并行；实际分区 ≤ 行数 |

最小对照（生产 Driver 同构：先 hash 再 pipeline）：

```python
# ① 发现：列键 → DPE hash → clip_id
bag_keys = list_bag_keys_from_oss(...)  # Driver
discovered = discover_bags_via_hash(bag_keys=bag_keys, hash_batch_rows=32, ...)

# ② 流水线
input_df = md.DataFrame(pd.DataFrame(build_job_rows_from_discovered(discovered, ...)))
input_df = input_df.mf.rebalance(num_partitions=min(dpe_parallel, n_rows))
result_df = input_df.mf.apply_chunk(udf, batch_rows=batch_rows, ...)
```

辅助实现也可对照：`pipeline/dataworks/sdk_pipeline_driver_node.py`、`sdk_dpe_common.py`、`dpe_udf_minimal_example.py`。

---

## 1. 节点职责（历史多节点拆分，已冻结）

| SDK 阶段 | 能力 | 本地 / API | 输出（run 目录） |
|----------|------|------------|------------------|
| `sdk_discover` | 登记 bag、`clip_id=sha256:{bag}` | MC / 调度 | `dim_clip` |
| `sdk_infer` | **整包 SDK 流水线** | 见下 | 三个 jsonl + `preview/` |
| `sdk_upload` | 上传 OSS | OSS SDK | `clips/{clip_id}/runs/{run_id}/` |
| `sdk_mc_write` | 写 MC 事实表 | PyODPS | `aig_sdk__*` |
| `sdk_dispatch` | 更新 dispatch | OSS | `pipeline/dispatch/latest.json` |

**`sdk_infer` / `run_stages` 内部顺序**：

1. `extract_clips` — 解码帧、WAV、声学面板、**多路 `clip_preview_camera*.mp4`**
2. `transcribe_clips` — **qwen3-asr-flash**（`api` 或 `mc`）
3. `materialize_preview` — `preview/` + `manifest.json`
4. `label_clips` — Omni
5. `embed_clips` — VL-embedding
6. `write_run_json` — `run.json`（upload 提交标记）

---

## 2. Driver 节点推荐写法（PyODPS3）

依赖：在 **DPE 镜像**安装 SDK（含 `[mc]`）：

```bash
pip install 'oms-multimodal-sdk[mc]>=0.3.2'
```

本机 / 调试核心逻辑（与 `run_stages` 一致）：

```python
from pathlib import Path
from oms_multimodal import (
    OmsMultimodalClient,
    ClipConfig,
    bundled_taxonomy_path,
    parse_stages,
    run_stages,
)

run_dir = Path("/mnt/oss/clips/sha256:.../runs/...")
client = OmsMultimodalClient(
    taxonomy_path=bundled_taxonomy_path(),
    work_dir=run_dir / "_sdk_work",
    model_backend="mc",  # 或 api
    load_dotenv=False,
)
ctx = client.make_run_context(run_dir, media_mode="local", clip_id="...", run_id="...")
try:
    result = run_stages(
        ctx,
        Path("/mnt/oss/rosbags/.../output.bag"),
        client,
        stages=parse_stages("extract,asr,preview,label,embed,upload"),
        clip_config=ClipConfig(min_sec=15, max_sec=20),
        model_backend="mc",
    )
finally:
    client.close()
```

> 生产请粘贴 **bundled** 单文件 Driver，不要只贴未打包的 `sdk_pipeline_driver_node.py`（缺 helpers）。

<details><summary>旧 sdk_infer 一键写法（参考）</summary>

```python
from pathlib import Path
from oms_multimodal import OmsMultimodalClient, ClipConfig, OutputConfig, bundled_taxonomy_path

bag_path = Path("/mnt/oss/rosbags/.../output.bag")  # OSS 挂载
out_dir = Path("/mnt/oss/clips/{clip_id}/runs/{run_id}")  # 或先写本地再 upload

client = OmsMultimodalClient(
    taxonomy_path=bundled_taxonomy_path(),
    work_dir=out_dir / "_work",
    load_dotenv=True,
    # model_backend="api",  # 显式默认；MC 就绪后改为 mc 或 MODEL_BACKEND=mc
)
result = client.process_bag(
    bag_path,
    clip_config=ClipConfig(min_sec=15, max_sec=20, sample_fps=1.0),
    output=OutputConfig(
        labels_out=out_dir / "labels.jsonl",
        embeddings_out=out_dir / "fusion_embeddings.jsonl",
        videos_out=out_dir / "clip_videos.jsonl",
    ),
)
# 将 work/.../clips/*/clip_preview_*.mp4、audio.wav 拷到 out_dir/preview/，写 manifest.json + run.json
```

CLI 等价（适合 shell 节点）：

```bash
python -m oms_multimodal run --bag /mnt/oss/rosbags/xxx.bag \
  --work-dir /tmp/work \
  --labels-out /tmp/out/labels.jsonl \
  --embeddings-out /tmp/out/fusion_embeddings.jsonl \
  --videos-out /tmp/out/clip_videos.jsonl \
  --taxonomy $(python -c "from oms_multimodal import bundled_taxonomy_path; print(bundled_taxonomy_path())")
```

</details>

---

## 3. OSS 产物（sdk_v1）

上传前缀：`clips/{clip_id}/runs/{run_id}/`

```text
run.json
labels.jsonl
fusion_embeddings.jsonl
clip_videos.jsonl
preview/manifest.json
preview/grid.mp4                    # 可选，HMI 合成
preview/clip_preview_camera0.mp4  # SDK 原名
preview/audio.wav
```

`clip_id` = **`sha256:{bag 文件 SHA256 hex}`**（与 HMI import 一致）。

---

## 4. 环境变量（节点 / 工作流）

| 变量 | 必需 | 说明 |
|------|------|------|
| `DASHSCOPE_API_KEY` | 是 | ASR + Embedding +（部分）Omni |
| `DASHSCOPE_WORKSPACE_ID` | Omni 是 | MaaS 业务空间 |
| `DASHSCOPE_REGION` | 否 | 默认 `cn-beijing` |
| `MODEL_BACKEND` | 否 | **`api`**（默认）或 **`mc`**（MaxFrame AI，需 `pip install '.[mc]'`，**maxframe≥2.8.0**） |
| `OMNI_MODEL` | 否 | 默认 `qwen3.5-omni-plus` |
| `ASR_MODEL` | 否 | 默认 `qwen3-asr-flash` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | 否 | 默认 `qwen3-vl-embedding` / `1024` |
| `CLIP_VIDEO_ENABLED` | 否 | 默认 true，多路 MP4 |

**Secrets**：走 DataWorks 参数 / KMS，不要写进代码库。

---

## 5. API vs MC

| 能力 | `MODEL_BACKEND=api` | `MODEL_BACKEND=mc`（已实现，本机 18/18） |
|------|---------------------|------------------------------------------|
| ASR | DashScope SDK | MaxFrame **`content_part.audio`**（2.8+）或 legacy `input_audio` |
| Omni 打标 | MaaS OpenAI 兼容（video 帧序列 + audio + text） | MaxFrame **`cp.video` + `cp.audio` + `cp.text`（含 ASR）** |
| VL Embedding | DashScope `MultiModalEmbedding` | MaxFrame `cp.image` + `cp.text`（`enable_fusion`） |
| 解析 / MP4 | 本地 ffmpeg + rosbags | 不变（DPE extract） |

SDK 入口：

- `ClientConfig.model_backend` / 环境变量 **`MODEL_BACKEND`**
- MC 客户端：`oms_multimodal.mc` — `McAsrClient` / `McOmniLabelClient` / `McFusionEmbeddingClient`
- ContentPart 构造：`oms_multimodal/mc/content_parts.py`

### 5.1 MC 环境变量（补充）

| 变量 | 默认 | 说明 |
|------|------|------|
| `MC_OMNI_NATIVE_MEDIA` | `true` | Omni：`cp.video` + `cp.audio` + `cp.text`（含 ASR transcript） |
| `MC_OMNI_FALLBACK_MODEL` | 空 | 显式 VL 兜底（如 `qwen3.6-plus`），优先于 catalog Omni |
| `MC_IMAGE_MODE` | `auto` | `base64` / `oss_url` / `auto`（有 OSS AK/SK 时 auto→oss_url） |
| `MC_MODELSET_PROJECT` | `bigdata_public_modelset` | modelset 项目 |

### 5.2 验数字段（`labels.jsonl` / `asr.jsonl`）

| 字段 | 期望（原生 media 开启） |
|------|-------------------------|
| `asr.jsonl` → `mc_mode` | `content_part_audio` |
| `labels.jsonl` → `mc_mode` | `omni_native`（有 clip MP4 + WAV） |
| `labels.jsonl` → `mc_has_video` / `mc_has_audio_part` | `true` |
| `labels.jsonl` → `mc_has_asr_in_text` | `true`（`cp.text` 含 `[ASR transcript]`） |

本机脚本：`pipeline/local_sdk_mc_test/run_mc_oss_verify.py`（Python **3.11** + `pip install -e "piplinesdk/.[mc]"`）。

关闭原生 media A/B：`MC_OMNI_NATIVE_MEDIA=false`（回退 image 抽帧；文本仍含 ASR）。

---

## 6. MC 写入

Driver 完成后调用 HMI 仓脚本（或内联 PyODPS）：

```bash
py -3 scripts/ingest_sdk_run_to_mc.py --clip-id sha256:... --run-id ... --ds yyyyMMdd
py -3 scripts/publish_sdk_dispatch.py --clip-id ... --run-id ... --ds yyyyMMdd
```

表前缀：**`aig_sdk__`**（DDL：`pipeline/sql/maxcompute/aig_sdk__ddl.sql`）。

---

## 7. 本地联调（无 DataWorks）

1. `pip install -e ../piplinesdk`（在 `hmi/` 目录：`pip install -r requirements-dev.txt`）
2. 配置 `.env`（DashScope）
3. `python -m oms_multimodal run --bag testdata\...\output.bag`
4. HMI 仓：`py -3 scripts/import_real_data_clips.py --source pipeline_latest --reset`

产物应与 `data/real_data/pipeline_latest/*/labels.jsonl` 同构。
