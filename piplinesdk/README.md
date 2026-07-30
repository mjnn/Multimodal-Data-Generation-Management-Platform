# Pipeline SDK（OMS Multimodal）

**包名**：`oms-multimodal-sdk` · **当前版本**：0.3.0

本目录为 **SDK 源码 monorepo**：Python 包 `oms_multimodal/`、构建配置、wheel 与对外文档。与 HMI 仓 `rosbag_to_labels_pipline/` 的 `sdk_v1` OSS、`aig_sdk__` MC 对齐。

## 安装

```powershell
cd piplinesdk
pip install ./oms_multimodal_sdk-0.3.0-py3-none-any.whl

# 开发（改 SDK 与 HMI 联调，仓库根）
cd pipeline
pip install -e ../piplinesdk
# 或
cd hmi && pip install -r requirements-dev.txt
```

## 文档

| 文件 | 内容 |
|------|------|
| [docs/SDK.md](docs/SDK.md) | API / CLI / 环境变量（构建前同步到 `oms_multimodal/bundled/SDK.md`） |
| [docs/DATAWORKS_SDK.md](docs/DATAWORKS_SDK.md) | DataWorks 节点、OSS 输出、`MODEL_BACKEND=api` |
| [RELEASE.md](RELEASE.md) | wheel 说明与构建步骤 |

## 构建 wheel

```powershell
cd piplinesdk
Copy-Item docs\SDK.md oms_multimodal\bundled\SDK.md -Force
python -m pip install build
python -m build
Copy-Item dist\oms_multimodal_sdk-0.3.0-py3-none-any.whl . -Force
```

## 能力一览

| 阶段 | 本地（`STORAGE_BACKEND=local`） | 云端（`MODEL_BACKEND=api` / `STORAGE_BACKEND=cloud`） |
|------|------|------------------------------|
| Rosbag 解析 + clip | `RosbagExtractor` | — |
| 预览 MP4 + WAV | ffmpeg | — |
| ASR | — | `qwen3-asr-flash` |
| OMS 打标 | — | `qwen3.5-omni-plus` |
| 融合向量 | — | `qwen3-vl-embedding` |

## 快速验证

```powershell
python -c "from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path, __version__; print(__version__)"
python -m oms_multimodal inspect --bag path\to\output.bag
```

需 `.env`：`DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`（见 `.env.example`）。

## 与 HMI 仓

```text
SDK process_bag → jsonl + preview/
       ↓ import_real_data_clips / OSS sdk_v1
HMI local + aig_sdk__ MC
```

设计：`docs/sdk-first-pipeline-design.md`
