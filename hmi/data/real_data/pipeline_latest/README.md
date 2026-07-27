# pipeline_latest

最新 SDK 流水线产物：**多路 clip 预览 MP4**（`clip_preview_camera0..3.mp4`）+ ASR + Omni 打标 + fusion embedding。

本批次：`testdata` 前 **3** 个 bag（各 1 clip）。

## 目录结构（每个 run 文件夹，如 `2026-07-23_14-02-57/`）

| 路径 | 说明 |
|------|------|
| `labels.jsonl` | 打标 + ASR |
| `fusion_embeddings.jsonl` | 融合向量 |
| `clip_videos.jsonl` | 多路视频元数据（`clip_video_paths`、`encoded_cameras`） |
| `work/output/clips/output_0000/` | **SDK 预览产物**（推荐与 jsonl 同树存放） |
| `work/.../clip_preview_camera0.mp4` | 单路摄像头预览（通常 3 路：camera0–2） |
| `work/.../audio.wav` | 片段音频 |

## OSS（sdk_v1，与本地 artifact 同构）

```text
clips/{clip_id}/runs/{run_id}/
├── run.json
├── labels.jsonl
├── fusion_embeddings.jsonl
├── clip_videos.jsonl
└── preview/
    ├── manifest.json
    ├── grid.mp4
    ├── clip_preview_camera0.mp4 …
    └── audio.wav
```

`clip_id` = **`sha256:{对应 .bag 文件内容 hash}`**。

## HMI 本地导入

```powershell
```powershell
cd hmi
py -3 scripts/import_real_data_clips.py --list
py -3 scripts/import_real_data_clips.py --source pipeline_latest --reset
cd ..\pipeline
py -3 scripts/upload_clip_preview_to_oss.py --all-real
```

导入时会：

1. 对 run 关联的 `.bag` 做 SHA256，生成 `clip_id`
2. 拷贝三个 jsonl + SDK 原名 MP4 到 `preview/`
3. 合成 `preview/grid.mp4` 并写 `preview/manifest.json`

## 批次摘要

见 `run_summary.json`、`run_multicam.log`。
