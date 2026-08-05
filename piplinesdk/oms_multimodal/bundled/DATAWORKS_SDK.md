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
| `MODEL_BACKEND` | 否 | **`api`**（默认）或 **`mc`**（未实现） |
| `OMNI_MODEL` | 否 | 默认 `qwen3.5-omni-plus` |
| `ASR_MODEL` | 否 | 默认 `qwen3-asr-flash` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` | 否 | 默认 `qwen3-vl-embedding` / `1024` |
| `CLIP_VIDEO_ENABLED` | 否 | 默认 true，多路 MP4 |

**Secrets**：走 DataWorks 参数 / KMS，不要写进代码库。

---

## 5. API vs MC（路线图）

| 能力 | `MODEL_BACKEND=api`（现在） | `MODEL_BACKEND=mc`（规划） |
|------|----------------------------|----------------------------|
| ASR | DashScope SDK | MaxFrame AI / 模型集（若上架） |
| Omni 打标 | MaaS OpenAI 兼容 | **待 bigdata_modelset 上架 Omni** |
| VL Embedding | DashScope `MultiModalEmbedding` | MC 侧 embedding UDF |
| 解析 / MP4 | 始终本地 ffmpeg + rosbags | 不变 |

SDK 已预留：

- `ClientConfig.model_backend` / 环境变量 **`MODEL_BACKEND`**
- `OmsMultimodalClient` 在 `mc` 下对 Omni 显式 `ConfigurationError`（避免误用）

后续改造点（源码 **`piplinesdk/oms_multimodal/`**）：

1. `omni_client.py` — `McOmniLabelClient` 或分支调用 MaxFrame
2. `embedding_client.py` / `asr_client.py` — 同上
3. `pipeline.py` — 按 `model_backend` 注入 client 工厂
4. DataWorks — 节点参数 `model_backend=api` 直到 MC 验收通过

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
