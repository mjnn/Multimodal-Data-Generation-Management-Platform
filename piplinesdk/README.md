# OMS Multimodal SDK

**软件包名**：`oms-multimodal-sdk` · **当前版本**：0.3.2

把 **ROS1 录制文件（`.bag`）** 解析成时间片段，并可选用阿里云大模型做：**语音转文字、场景打标、融合向量**。

## 安装

```powershell
cd piplinesdk
# 推荐 Python 3.11
py -3.11 -m pip install -e .

# 若要通过 MaxCompute 调用模型（进阶）：
py -3.11 -m pip install -e ".[mc]"
```

或安装已构建的 wheel：

```powershell
py -3.11 -m pip install .\oms_multimodal_sdk-0.3.2-py3-none-any.whl
```

## 从这里开始

| 资源 | 内容 |
|------|------|
| **[examples/](examples/)** | **可运行示例（建议先跑这里）** |
| [docs/SDK.md](docs/SDK.md) | 完整使用说明（含术语表） |
| [docs/DATAWORKS_SDK.md](docs/DATAWORKS_SDK.md) | 在阿里云 DataWorks 上批量运行（进阶） |
| [docs/README.md](docs/README.md) | 文档索引 |

```powershell
py -3.11 -c "from oms_multimodal import __version__; print(__version__)"
py -3.11 examples\01_inspect_bag.py
py -3.11 examples\02_extract_only.py
py -3.11 examples\03_run_stages.py extract,asr
```

调用云端模型时，请在 `piplinesdk/.env` 填写百炼密钥（见 `.env.example`）：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`
- `MODEL_BACKEND=api`（本机默认）

## 能力一览

| 步骤 | 是否需要云端模型 | 入口 |
|------|------------------|------|
| 解析 bag / 整理预览 | 否 | `extract_clips` / `materialize_preview` |
| 语音转文字 | 是 | `transcribe_clips` |
| 场景打标 / 融合向量 | 是 | `label_clips` / `embed_clips` |
| 按步骤组合执行 | 视步骤而定 | **`run_stages`（推荐）** |

## 构建发布包

```powershell
cd piplinesdk
.\scripts\build_release.ps1
```
