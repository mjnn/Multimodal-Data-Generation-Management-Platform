# OMS Multimodal SDK

**软件包名**：`oms-multimodal-sdk` · **当前版本**：0.3.3

把 **ROS1 录制文件（`.bag`）**（或上传的视频/音频/文本）解析成时间片段，并可选用阿里云大模型做：**语音转文字、场景打标、融合向量**；可选本机 **帧级 BBox**（`bboxes.jsonl`）与 **plain 预览 MP4**。

## 安装

```powershell
cd piplinesdk
# 推荐 Python 3.11
py -3.11 -m pip install -e .

# 可选：YOLO 检测
py -3.11 -m pip install -e ".[bbox]"

# 可选：MaxCompute / MaxFrame AI（需 maxframe≥2.8.0）
py -3.11 -m pip install -e ".[mc]"
```

## 从这里开始

| 资源 | 内容 |
|------|------|
| **[docs/SDK-CAPABILITIES-AND-ARTIFACTS.md](docs/SDK-CAPABILITIES-AND-ARTIFACTS.md)** | **小白向：能力 + 产物总览** |
| **[docs/SDK.md](docs/SDK.md)** | 完整使用说明（主文档） |
| **[examples/](examples/)** | 可运行示例（建议先跑这里） |
| [docs/DATAWORKS_SDK.md](docs/DATAWORKS_SDK.md) | 在阿里云 DataWorks 上批量运行（进阶） |
| [docs/README.md](docs/README.md) | 文档索引 |

```powershell
py -3.11 -c "from oms_multimodal import __version__; print(__version__)"
py -3.11 examples\01_inspect_bag.py
py -3.11 examples\02_extract_only.py
py -3.11 examples\03_run_stages.py extract,asr
# 可选：本地 stub 画框 + 双预览（无需云端密钥）
$env:BBOX_DETECTOR="stub"; $env:ENCODE_PLAIN="1"
py -3.11 examples\03_run_stages.py extract,bbox,encode,preview
```

调用云端模型时，请在 `piplinesdk/.env` 填写百炼密钥（见 `.env.example`）：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`
- `MODEL_BACKEND=api`（本机默认）或 `mc`（MaxFrame AI）

## 能力一览

| 步骤 | 是否需要云端模型 | 入口 |
|------|------------------|------|
| 解析 bag / 整理预览 | 否 | `extract_clips` / `materialize_preview` |
| 帧级 BBox / 预览编码 | 否 | `annotate_bboxes` / `encode_preview_videos` |
| 语音转文字 | 是 | `transcribe_clips` |
| 场景打标 / 融合向量 | 是 | `label_clips` / `embed_clips` |
| 按步骤组合执行 | 视步骤而定 | **`run_stages`（推荐）** |
| 复合全流程（含可选 bbox） | 视配置 | `infer_full` |

## 构建发布包

```powershell
cd piplinesdk
.\scripts\build_release.ps1
```
