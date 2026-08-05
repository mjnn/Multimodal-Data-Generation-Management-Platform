# OMS Multimodal SDK 使用说明

> **软件包名**：`oms-multimodal-sdk`  
> **当前版本**：0.3.2  
> **Python 要求**：建议 3.11 或 3.12（最低 3.10）  
> **本文读者**：第一次使用本 SDK 的开发者（不要求事先了解任何内部项目）

如果你只想尽快跑通，请直接阅读 [第 3 节 快速开始](#3-快速开始)，或打开同仓库里的可运行脚本目录 `examples/`。

---

## 目录

1. [这个 SDK 是做什么的](#1-这个-sdk-是做什么的)
2. [安装](#2-安装)
3. [快速开始](#3-快速开始)
4. [认证与配置](#4-认证与配置)
5. [核心概念（先看懂这些词）](#5-核心概念先看懂这些词)
6. [推荐用法：按步骤运行流水线](#6-推荐用法按步骤运行流水线)
7. [客户端 API（OmsMultimodalClient）](#7-omsmultimodalclient-api)
8. [配置类参考](#8-配置类参考)
9. [低级 API](#9-低级-api)
10. [命令行工具](#10-cli-参考)
11. [输出文件格式](#11-输出数据结构)
12. [错误处理](#12-错误处理)
13. [更多代码示例](#13-完整示例)
14. [架构与限制](#14-架构与限制)
15. [术语表](#15-术语表)

可运行示例目录：`examples/`（见该目录下的 `README.md`）。

---

## 1. 这个 SDK 是做什么的

本 SDK 帮你把一份 **ROS1 录制文件（`.bag`）** 变成可分析的多模态结果：

1. **切开时间片段**：把整段录制切成约 15～20 秒的片段（称为 clip）
2. **抽出画面与声音**：多路摄像头图片、音频 WAV、预览视频等
3. **语音转文字**：调用语音识别模型，得到转写文本
4. **场景打标**：调用多模态大模型，按你提供的标签体系给出结构化标签
5. **生成向量**：调用多模态向量模型，得到可用于相似度检索的融合向量

你可以只做本地解析（不联网），也可以按步骤打开语音识别 / 打标 / 向量。

### 1.1 你最终会得到什么

一次完整运行后，输出目录里通常会有：

| 文件 | 含义（通俗） |
|------|----------------|
| `clips_index.jsonl` | 每个时间片段的索引 |
| `asr.jsonl` | 语音识别结果 |
| `labels.jsonl` | 场景标签结果 |
| `fusion_embeddings.jsonl` | 融合向量（一行一个片段） |
| `clip_videos.jsonl` | 预览视频路径记录 |
| `preview/` | 给人看的预览视频、音频、清单 |
| `run.json` | 本次运行的元信息（版本、完成步骤等） |

### 1.2 能力一览（按步骤）

| 你想做的事 | 是否需要联网调用大模型 | 推荐函数 |
|------------|------------------------|----------|
| 查看 bag 里有哪些话题 | 否 | `inspect_bag` |
| 只解析 bag、切片段、导出媒体 | 否 | `extract_clips` 或 `client.extract_bag` |
| 整理预览目录 | 否 | `materialize_preview` |
| 语音转文字 | 是 | `transcribe_clips` |
| 场景打标 | 是 | `label_clips` |
| 生成融合向量 | 是 | `embed_clips` |
| 按你指定的步骤组合执行 | 视步骤而定 | **`run_stages`（推荐）** |
| 一键跑完全流程（旧写法） | 是 | `client.process_bag` |

### 1.3 两种「模型调用方式」

调用语音识别 / 打标 / 向量时，可通过环境变量或代码参数选择：

| `MODEL_BACKEND` 取值 | 含义 | 你需要准备什么 |
|----------------------|------|----------------|
| `api`（**默认，适合本机试用**） | 通过阿里云百炼（DashScope）的 HTTP 接口调用模型 | `DASHSCOPE_API_KEY`；打标还需要 `DASHSCOPE_WORKSPACE_ID` |
| `mc` | 通过阿里云 MaxCompute 上的 MaxFrame AI / 公共模型集调用 | 额外安装 `pip install -e ".[mc]"`，并配置 MaxCompute 账号相关环境变量 |

> 初次试用请用 `api`。`mc` 面向已有 MaxCompute 环境的进阶场景，详见 [DATAWORKS_SDK.md](DATAWORKS_SDK.md)。

### 1.4 处理流程（示意）

```text
ROS1 录制文件 (.bag)
        │
        ▼
  解析并切成多个 clip（约 15～20 秒）
  · 多路相机帧、音频 WAV
  · 声学频谱图（PNG）、Mel 特征
  · 预览 MP4（可选）
        │
        ▼
  语音识别 → 得到转写文本
        │
        ├──────────────────┐
        ▼                  ▼
   场景打标模型         融合向量模型
   （画面+声音+文本）    （代表帧+频谱图+文本）
        │                  │
        ▼                  ▼
  labels.jsonl      fusion_embeddings.jsonl
```

---

## 2. 安装

### 2.1 推荐：在源码目录以可编辑方式安装

进入本 SDK 所在目录（文件夹名通常是 `piplinesdk`），执行：

```powershell
cd piplinesdk
py -3.11 -m pip install -e .
```

如果要用 `MODEL_BACKEND=mc`（MaxCompute 路径），再执行：

```powershell
py -3.11 -m pip install -e ".[mc]"
```

说明：

- 建议使用 **Python 3.11 或 3.12**。Python 3.14 上 MaxCompute 相关依赖经常装不上。
- 安装成功后即可：`import oms_multimodal`
- 命令行推荐用模块方式：`python -m oms_multimodal --help`

### 2.2 用 wheel 安装

若目录里已有构建好的 wheel 文件：

```powershell
py -3.11 -m pip install .\oms_multimodal_sdk-0.3.2-py3-none-any.whl
```

### 2.3 Windows 上找不到 `oms-multimodal` 命令

`pip` 会把可执行文件装到 Python 的 `Scripts` 目录。若该目录不在系统 `PATH` 中，直接输入 `oms-multimodal` 会失败。

**推荐做法**：始终用模块调用，不必改 `PATH`：

```powershell
python -m oms_multimodal --help
python -m oms_multimodal inspect --bag path\to\file.bag
```

### 2.4 验证安装是否成功

```powershell
python -c "from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path, __version__; print(__version__); print(bundled_taxonomy_path())"
python -m oms_multimodal --help
```

### 2.5 安装包自带的资源

安装后可在包内找到：

| 资源 | 如何拿到路径 |
|------|----------------|
| 默认标签体系 `oms_label_taxonomy.yaml` | `from oms_multimodal import bundled_taxonomy_path` |
| 本说明文档副本 | `from oms_multimodal import bundled_sdk_doc_path` |

---

## 3. 快速开始

### 3.1 准备密钥（只要调用云端模型就需要）

在 `piplinesdk` 目录复制环境变量模板并填写：

```powershell
copy .env.example .env
```

本机默认（`MODEL_BACKEND=api`）至少需要：

```env
DASHSCOPE_API_KEY=你的百炼密钥
DASHSCOPE_WORKSPACE_ID=你的业务空间ID
DASHSCOPE_REGION=cn-beijing
MODEL_BACKEND=api
```

> 密钥在阿里云「百炼 / DashScope」控制台申请。只做本地解析（不跑语音识别和打标）时，可以不填。

还需要一份 **ROS1 `.bag` 文件**。可运行示例默认会尝试读取一份样例路径；你也可以用环境变量指定：

```powershell
$env:BAG_PATH = "D:\data\my_recording.bag"
```

### 3.2 推荐写法：按步骤运行（`run_stages`）

这是目前最清晰的用法：先指定要跑哪些步骤，再一次性执行。

```python
from pathlib import Path
from oms_multimodal import (
    OmsMultimodalClient,
    ClipConfig,
    bundled_taxonomy_path,
    parse_stages,
    run_stages,
)

bag = Path(r"D:\data\my_recording.bag")   # 换成你的 .bag 路径
run_dir = Path("output/demo_run")         # 结果输出目录
run_dir.mkdir(parents=True, exist_ok=True)

client = OmsMultimodalClient(
    taxonomy_path=bundled_taxonomy_path(),  # 使用安装包自带的标签体系
    work_dir=run_dir / "_sdk_work",         # 中间工作目录（帧、临时文件）
    model_backend="api",                    # 本机试用请用 api
)
# 运行上下文：告诉 SDK「结果写到哪里」
ctx = client.make_run_context(
    run_dir,
    media_mode="local",   # 从本机磁盘读写媒体
    clip_id="demo",
    run_id="run-1",
)
try:
    result = run_stages(
        ctx,
        bag,
        client,
        # 步骤名用英文逗号分隔，含义见第 6 节
        stages=parse_stages("extract,asr,preview,label,embed,upload"),
        clip_config=ClipConfig(min_sec=15, max_sec=20, sample_fps=1.0),
        model_backend="api",
    )
finally:
    client.close()

print("已完成步骤:", result.stages_done)
print("错误列表:", result.errors)
print("是否写出标签文件:", (run_dir / "labels.jsonl").exists())
```

不想手写代码时，可直接跑：

```powershell
cd piplinesdk
py -3.11 examples\03_run_stages.py extract,asr
py -3.11 examples\03_run_stages.py
```

### 3.3 更短的一键写法（旧接口）

适合快速试一把；步骤开关不如 `run_stages` 灵活。

```python
from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path

client = OmsMultimodalClient(taxonomy_path=bundled_taxonomy_path())
result = client.process_bag(r"D:\data\my_recording.bag")
print(result.label_rows, result.embedding_rows, result.errors)
client.close()
```

### 3.4 只做本地解析（不调用任何云端模型）

```python
from oms_multimodal import OmsMultimodalClient, ClipConfig, OutputConfig, bundled_taxonomy_path

client = OmsMultimodalClient(taxonomy_path=bundled_taxonomy_path(), load_dotenv=False)
result = client.extract_bag(
    r"D:\data\my_recording.bag",
    clip_config=ClipConfig(min_sec=15, max_sec=20),
    output=OutputConfig(clips_out="output/clips.jsonl"),
)
print("切出片段数:", result.clip_rows)
client.close()
```

或：

```powershell
py -3.11 examples\02_extract_only.py
```

---

## 4. 认证与配置

### 4.1 环境变量

| 变量 | 是否必需 | 默认值 | 说明 |
|------|----------|--------|------|
| `DASHSCOPE_API_KEY` | 使用 `api` 调用模型时必需 | — | 阿里云百炼 API 密钥；语音识别、打标、向量共用 |
| `DASHSCOPE_WORKSPACE_ID` | 打标时必需 | — | 百炼业务空间 ID |
| `DASHSCOPE_REGION` | 否 | `cn-beijing` | 区域 |
| `MODEL_BACKEND` | 否 | `api` | `api`=百炼 HTTP；`mc`=MaxCompute MaxFrame AI |
| `EMBEDDING_MODEL` | 否 | `qwen3-vl-embedding` | 向量模型名 |
| `EMBEDDING_DIMENSION` | 否 | `1024` | 向量维度 |
| `OMNI_MODEL` | 否 | `qwen3.5-omni-plus` | 打标模型名 |
| `ASR_ENABLED` | 否 | `true` | 是否启用语音识别 |
| `ASR_MODEL` | 否 | `qwen3-asr-flash` | 语音识别模型名 |
| `ASR_LANGUAGE` | 否 | `zh` | 语音识别语言提示 |
| `ASR_ENABLE_ITN` | 否 | `false` | 是否做逆文本归一化 |
| `CLIP_VIDEO_ENABLED` | 否 | `true` | 是否生成预览 MP4 |
| `CLIP_VIDEO_FILENAME` | 否 | `clip_preview.mp4` | 预览文件名 |
| `CLIP_VIDEO_MAX_WIDTH` / `CLIP_VIDEO_MAX_HEIGHT` | 否 | `1280` / `720` | 预览画面最大宽高 |
| `CLIP_VIDEO_CODEC` / `CLIP_VIDEO_AUDIO_CODEC` | 否 | `libx264` / `aac` | 视频 / 音频编码器 |
| `CLIP_VIDEO_CRF` | 否 | `23` | 视频质量（数值越小通常越清晰、体积越大） |
| `ACOUSTIC_PANEL_TYPE` | 否 | `mel` | 声学频谱图类型：`stft` 或 `mel` |
| `ACOUSTIC_PANEL_N_FFT` | 否 | `2048` | FFT 窗口大小 |
| `ACOUSTIC_PANEL_HOP_LENGTH` | 否 | `512` | 帧移 |
| `ACOUSTIC_PANEL_N_MELS` | 否 | `128` | Mel 滤波器个数 |
| `ACOUSTIC_PANEL_FMIN` | 否 | `20` | Mel 最低频率（赫兹） |
| `ACOUSTIC_PANEL_FMAX` | 否 | 空（用奈奎斯特频率） | Mel 最高频率（赫兹） |
| `ACOUSTIC_PANEL_WIDTH` | 否 | `768` | 频谱图宽度（像素） |
| `ACOUSTIC_PANEL_HEIGHT` | 否 | `256` | 频谱图高度（像素） |

使用 `MODEL_BACKEND=mc` 时，还需要 MaxCompute 相关变量（如 `ODPS_ACCESS_ID`、`ODPS_ACCESS_KEY`、`ODPS_PROJECT`、`ODPS_ENDPOINT` 等），详见 [DATAWORKS_SDK.md](DATAWORKS_SDK.md)。

### 4.2 在代码里显式传参（可覆盖环境变量）

```python
from oms_multimodal import OmsMultimodalClient, AcousticPanelConfig

client = OmsMultimodalClient(
    api_key="sk-...",
    workspace_id="ws-...",
    region="cn-beijing",
    taxonomy_path="oms_label_taxonomy.yaml",
    work_dir="output/work",
    omni_model="qwen3.5-omni-plus",
    embedding_model="qwen3-vl-embedding",
    embedding_dimension=1024,
    acoustic_panel_config=AcousticPanelConfig(
        panel_type="mel",
        n_mels=128,
        target_width=768,
        target_height=256,
    ),
    load_dotenv=True,  # 是否自动加载当前目录向上查找的 .env
)
```

### 4.3 用 ClientConfig 批量配置

```python
from oms_multimodal import ClientConfig, OmsMultimodalClient

config = ClientConfig.from_env(taxonomy_path="oms_label_taxonomy.yaml")
config.embedding_dimension = 2048
client = OmsMultimodalClient(config=config)
```

---

## 5. 核心概念（先看懂这些词）

### 5.1 Bag 文件

**Bag**（或 rosbag）是 ROS（机器人操作系统）的录制文件，扩展名通常是 `.bag`。里面按时间戳保存了多个话题的消息，例如多路压缩图像、麦克风音频、文本事件等。

本 SDK **只支持 ROS1 格式的 bag**（当前实现基于 `rosbags` 库读取）。

### 5.2 Clip（时间片段）

**Clip** 是处理的最小单元：默认把录制切成约 **15～20 秒** 一段。若整份 bag 短于约 20 秒，通常只会得到 1 个 clip。

| 字段 | 类型 | 含义 |
|------|------|------|
| `clip_id` | `str` | 片段 ID，形如 `{文件名主干}_{序号}` |
| `frames` | `list` | 按采样帧率抽出的多相机帧（给打标模型看视频用） |
| `embedding_frames` | `list` | 每路相机一张代表帧（给向量模型用，最多约 4 张） |
| `audio` | 对象或空 | 该片段的音频 |
| `acoustic_panel_path` | 路径或空 | 声学频谱图 PNG |
| `mel_matrix_path` | 路径或空 | Mel 矩阵 CSV |
| `mel_feature_text` | 文本或空 | 压缩后的 Mel 特征文本（会塞进打标/向量的文本侧） |
| `events` | `list` | 该时间范围内的文本事件 |
| `duration_sec` | `float` | 片段时长（秒） |

### 5.3 话题（Topic）

`inspect_bag()` 返回每个话题的元数据，例如：

```python
TopicInfo(
    name="/camera0/image_raw/compressed",
    msgtype="sensor_msgs/msg/CompressedImage",
    modality="image",
    message_count=455,
)
```

`modality`（模态）常见取值：`image`（图像）、`audio`（音频）、`text`（文本）、`other`（其它）。

### 5.4 标签体系（Taxonomy）

打标时模型必须知道「有哪些标签、标签什么意思」。这些定义放在一份 YAML 文件里（安装包自带一份 `oms_label_taxonomy.yaml`）。SDK 会把它编进提示词，并解析模型返回的 JSON。

### 5.5 声学频谱图与 Mel 特征

向量模型通常不能直接吃原始音频波形，因此 SDK 会：

1. 把音频画成 **声学频谱图 PNG**（默认 Mel 谱）
2. 另存 **Mel 矩阵**（CSV）并压缩成一段 **特征文本**

打标与向量都会用到这些信息。

### 5.6 运行目录与工作目录

| 目录 | 作用 |
|------|------|
| **运行目录 `run_dir`** | 对外结果写在这里：`labels.jsonl`、`preview/`、`run.json` 等 |
| **工作目录 `work_dir`** | 中间产物：解码帧、临时 clip 目录等，默认常为 `run_dir/_sdk_work` |

---

## 6. 推荐用法：按步骤运行流水线

这一层把整条处理拆成可开关的步骤。每个步骤函数读写**同一个运行目录**里的文件，因此可以「先只解析，再单独跑语音识别」，也可以一次全开。

### 6.1 运行上下文 `RunContext`

```python
from pathlib import Path
from oms_multimodal import RunContext

ctx = RunContext(
    run_dir=Path("output/run"),
    clip_id="demo-clip",
    run_id="demo-run-001",
    media_mode="local",  # local=读本机文件；oss=按对象存储路径读；auto=自动判断
)
# 若不指定 work_dir，默认是 run_dir / "_sdk_work"
```

也可以：`client.make_run_context(run_dir, media_mode="local", clip_id=..., run_id=...)`。

### 6.2 各步骤做什么、写出什么

| 函数 | 步骤英文名 | 主要写出的文件 |
|------|------------|----------------|
| `extract_clips(...)` | `extract` | `clips_index.jsonl`、`clip_videos.jsonl`、工作目录下的媒体 |
| `transcribe_clips(...)` | `asr` | `asr.jsonl`（asr = Automatic Speech Recognition，自动语音识别） |
| `materialize_preview(...)` | `preview` | `preview/` 下的 MP4、音频、`manifest.json` |
| `label_clips(...)` | `label` | `labels.jsonl` |
| `embed_clips(...)` | `embed` | `fusion_embeddings.jsonl` |
| `write_run_json(...)` | `upload`（表示「结果已落盘可交付」） | `run.json` |
| `infer_full(...)` | （复合接口） | 依次执行解析→语音识别→打标→向量→预览 |

### 6.3 `parse_stages` 与 `run_stages`

```python
from oms_multimodal import parse_stages, run_stages

# None 或空字符串 = 打开全部步骤
parse_stages(None)

# 只跑解析 + 语音识别（适合先验证联网能力）
parse_stages("extract,asr")

# 别名：transcribe 等同于 asr
parse_stages("extract,transcribe")

result = run_stages(
    ctx,
    bag_path,
    client,
    stages=parse_stages("extract,asr"),
    model_backend="api",
)
print(result.stages_done)          # 实际跑完的步骤名列表
print(result.extract_clip_rows)    # 解析出的片段数
print(result.errors)               # 步骤内收集到的错误
```

`run_stages` 返回对象 `StagesResult` 的常用字段：

| 字段 | 含义 |
|------|------|
| `stages_done` | 已完成的步骤名列表 |
| `errors` | 错误明细列表 |
| `preview_ok` | 预览目录是否看起来有效 |
| `extract_clip_rows` | 解析出的片段行数 |
| `label_rows` | 标签行数 |
| `embedding_rows` | 向量行数 |

### 6.4 建议的试用顺序

1. `examples/01_inspect_bag.py`：确认 bag 能打开  
2. `examples/02_extract_only.py`：确认本地解析正常  
3. `examples/03_run_stages.py extract,asr`：确认语音识别密钥与网络正常  
4. `examples/03_run_stages.py`：跑完整步骤  
5. （进阶 / DataWorks）`examples/05_dpe_apply_chunk_concurrency.py`：UDF、`apply_chunk`、`batch_rows` / `dpe_parallel` 注释示例（需粘贴到 PyODPS3，本机通常不能直接跑通）

在阿里云 DataWorks 等大数据平台上批量跑的说明，见单独文档 [DATAWORKS_SDK.md](DATAWORKS_SDK.md)（那是进阶话题，不影响你本机学会本 SDK）。

---

## 7. 客户端 API（OmsMultimodalClient）

### 构造函数

```python
OmsMultimodalClient(
    *,
    api_key: str | None = None,
    workspace_id: str | None = None,
    region: str | None = None,
    taxonomy_path: str | Path | None = None,
    work_dir: str | Path | None = None,
    omni_model: str | None = None,
    embedding_model: str | None = None,
    embedding_dimension: int | None = None,
    acoustic_panel_config: AcousticPanelConfig | None = None,
    config: ClientConfig | None = None,
    load_dotenv: bool = True,
)
```

### 方法一览

| 方法 | 云端调用 | 说明 |
|------|----------|------|
| `inspect_bag(bag_path)` | 否 | 列出 topic 与 modality |
| `iter_clips(bag_path, clip_config=...)` | 否 | 迭代 `Clip` 对象 |
| `extract_bag(bag_path, ...)` | 否 | 提取 clip 元数据到 JSONL |
| `process_bag(bag_path, ...)` | 是 | 完整打标 + embedding |
| `label_clip(clip)` | 是 | 单 clip Omni 打标 |
| `embed_clip(clip, extra_text=...)` | 是 | 单 clip fusion 向量 |
| `process_clip(clip)` | 是 | 单 clip 打标 + embedding |
| `render_acoustic_panel(wav_path, output_path)` | 否 | 独立渲染声学面板 PNG |
| `render_acoustic_assets(wav_path, panel_path, ...)` | 否 | PNG + Mel 矩阵 + feature text |
| `resolve_bags(manifest_path)` | 否 | 静态方法，解析 manifest |

---

### `inspect_bag(bag_path) -> list[TopicInfo]`

```python
topics = client.inspect_bag("rosbag/output.bag")
for t in topics:
    print(t.name, t.modality, t.message_count)
```

---

### `iter_clips(bag_path, *, clip_config=None) -> Iterator[Clip]`

```python
from oms_multimodal import ClipConfig

for clip in client.iter_clips("rosbag/output.bag", clip_config=ClipConfig(max_clips=5)):
    print(clip.clip_id, clip.duration_sec, clip.acoustic_panel_path)
```

---

### `extract_bag(bag_path, *, clip_config=None, output=None) -> BagProcessResult`

```python
from oms_multimodal import OutputConfig

result = client.extract_bag(
    "rosbag/output.bag",
    output=OutputConfig(clips_out="output/clips.jsonl"),
)
# result.clip_rows, result.clips_out
```

---

### `process_bag(bag_path, *, clip_config=None, output=None) -> BagProcessResult`

```python
result = client.process_bag(
    "rosbag/output.bag",
    clip_config=ClipConfig(min_sec=15, max_sec=20, sample_fps=1.0),
    output=OutputConfig(
        embeddings_out="output/fusion_embeddings.jsonl",
        labels_out="output/labels.jsonl",
    ),
)

if result.errors:
    for err in result.errors:
        print(err["clip_id"], err["error"])
```

返回 `BagProcessResult`：

| 字段 | 说明 |
|------|------|
| `bag` | bag 路径 |
| `topics` | topic 列表 |
| `embedding_rows` / `label_rows` | 成功写入行数 |
| `errors` | `[{"clip_id": "...", "error": "..."}]` |
| `to_dict()` | 转为 JSON 可序列化 dict |

---

### `label_clip(clip) -> dict`

```python
clip = next(client.iter_clips("rosbag/output.bag"))
label_row = client.label_clip(clip)
print(label_row["scene_summary"])
print(label_row["labels"]["L2.3.fatigue_level"])
```

---

### `embed_clip(clip, *, extra_text="") -> dict`

```python
embedding_row = client.embed_clip(clip, extra_text="驾驶员轻微疲劳")
vector = embedding_row["embedding"]  # list[float], len=dimension
```

---

### `process_clip(clip) -> tuple[dict, dict]`

```python
label_row, embedding_row = client.process_clip(clip)
```

---

### `render_acoustic_panel(wav_path, output_path, *, config=None) -> str`

```python
path = client.render_acoustic_panel("clip.wav", "panel.png")
```

### `render_acoustic_assets(wav_path, output_dir, *, config=None) -> dict`

一次写出声学面板 PNG、`mel_matrix.csv` / `.meta.json`，以及注入模型的 `mel_feature_text`：

```python
assets = client.render_acoustic_assets("clip.wav", "clips/demo")
# assets["acoustic_panel_path"] / assets["mel_matrix_path"] / assets["mel_feature_text"]
```

---

## 8. 配置类参考

### `ClipConfig`

```python
@dataclass
class ClipConfig:
    min_sec: float = 15.0      # 最短 clip（秒）
    max_sec: float = 20.0      # 最长 clip（秒）
    sample_fps: float = 1.0    # Omni 每路相机采样帧率
    max_clips: int | None = None
```

### `OutputConfig`

```python
@dataclass
class OutputConfig:
    embeddings_out: Path = Path("output/fusion_embeddings.jsonl")
    labels_out: Path = Path("output/labels.jsonl")
    clips_out: Path = Path("output/clips.jsonl")
    videos_out: Path = Path("output/clip_videos.jsonl")
```

### `ClipVideoConfig`

```python
@dataclass
class ClipVideoConfig:
    enabled: bool = True
    filename: str = "clip_preview.mp4"
    max_width: int = 1280
    max_height: int = 720
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 23
    camera_topic: str | None = None  # 默认取 clip 内字典序第一路相机

    @classmethod
    def from_env(cls) -> ClipVideoConfig: ...
    def to_dict(self) -> dict: ...
```

预览 MP4 使用 **`Clip.video_frames`（clip 时间范围内全量帧）**，与 Omni 的 `sample_fps` 无关；多相机时默认只编码 **一路**（可用 `CLIP_VIDEO_CAMERA_TOPIC` 指定），帧间隔按 ROS 时间戳计算。

预览文件默认路径：`{work_dir}/clips/{clip_id}/clip_preview.mp4`。依赖系统 `ffmpeg` 或 pip 包 `imageio-ffmpeg`。

### `AcousticPanelConfig`

```python
@dataclass
class AcousticPanelConfig:
    panel_type: Literal["stft", "mel"] = "mel"
    n_fft: int = 2048
    hop_length: int = 512
    n_mels: int = 128           # 仅 mel 模式
    fmin: float = 20.0          # 仅 mel 模式
    fmax: float | None = None   # None = Nyquist
    target_width: int = 768
    target_height: int = 256
    # Mel 矩阵 → 打标 / 向量化特征
    export_mel_matrix: bool = True
    mel_matrix_csv: bool = True
    mel_matrix_npy: bool = False
    mel_feature_max_frames: int = 32   # 时间轴下采样帧数上限
    mel_feature_max_chars: int = 6000  # feature text 字符上限

    @classmethod
    def from_env(cls) -> AcousticPanelConfig: ...
    def to_dict(self) -> dict: ...
```

环境变量：`ACOUSTIC_EXPORT_MEL_MATRIX`、`ACOUSTIC_MEL_MATRIX_CSV`、`ACOUSTIC_MEL_MATRIX_NPY`、`ACOUSTIC_MEL_FEATURE_MAX_FRAMES`、`ACOUSTIC_MEL_FEATURE_MAX_CHARS`。

---

## 9. 低级 API

如需绕过 `OmsMultimodalClient` 直接组合模块：

```python
from oms_multimodal import (
    RosbagExtractor,
    OmniLabelClient,
    FusionEmbeddingClient,
    load_taxonomy,
    AcousticPanelConfig,
)

taxonomy = load_taxonomy("oms_label_taxonomy.yaml")
extractor = RosbagExtractor("rosbag/output.bag", "output/work/output")

omni = OmniLabelClient()
embedding = FusionEmbeddingClient(dimension=1024)

for clip in extractor.iter_clips(acoustic_panel_config=AcousticPanelConfig()):
    label = omni.label_clip(clip, taxonomy)
    vec = embedding.embed_clip(clip, extra_text=label["scene_summary"])
```

### 公开模块

| 模块 | 主要符号 |
|------|----------|
| `oms_multimodal.client` | `OmsMultimodalClient` |
| `oms_multimodal.config` | `ClientConfig`, `ClipConfig`, `OutputConfig`, `BagProcessResult` |
| `oms_multimodal.rosbag_parser` | `Clip`, `RosbagExtractor`, `inspect_bag`, `TopicInfo` |
| `oms_multimodal.omni_client` | `OmniLabelClient` |
| `oms_multimodal.embedding_client` | `FusionEmbeddingClient` |
| `oms_multimodal.acoustic_panel` | `AcousticPanelConfig`, `render_acoustic_panel`, `render_acoustic_assets`, `compute_mel_matrix`, `save_mel_matrix`, `mel_matrix_to_feature_text` |
| `oms_multimodal.clip_video` | `ClipVideoConfig`, `encode_clip_mp4`, `render_clip_preview_video` |
| `oms_multimodal.taxonomy` | `load_taxonomy`, `parse_label_json` |
| `oms_multimodal.pipeline` | `LabelEmbeddingPipeline`, `resolve_bags` |
| `oms_multimodal.exceptions` | `OmsMultimodalError`, `ConfigurationError`, `ApiError` |

### 向后兼容

旧代码 `from src.pipeline import LabelEmbeddingPipeline` 仍可用（薄 re-export 层），建议迁移至 `oms_multimodal`。

---

## 10. 命令行工具

**推荐入口**（不依赖 PATH）：

```bash
python -m oms_multimodal --help
```

也可使用 `oms-multimodal`（Scripts 已在 PATH 时）或项目根目录的 `python main.py`。

```bash
# 查看 topic
python -m oms_multimodal inspect --bag rosbag/output.bag

# 完整流水线
python -m oms_multimodal run --bag rosbag/output.bag

# 仅本地提取
python -m oms_multimodal run --bag rosbag/output.bag --extract-only

# 自定义 clip 与声学面板
python -m oms_multimodal run --bag rosbag/output.bag ^
  --clip-min-sec 15 --clip-max-sec 20 --sample-fps 1 ^
  --acoustic-panel-type mel --acoustic-n-mels 128

# 从 manifest 批量处理
python -m oms_multimodal run --manifest rosbag/manifest.json
```

### 常用 CLI 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--bag` | — | 单个 .bag 路径 |
| `--manifest` | `rosbag/manifest.json` | 批量 bag 清单 |
| `--taxonomy` | `oms_label_taxonomy.yaml` | 打标 taxonomy |
| `--work-dir` | `output/work` | 中间文件目录 |
| `--embeddings-out` | `output/fusion_embeddings.jsonl` | 向量输出 |
| `--labels-out` | `output/labels.jsonl` | 打标输出 |
| `--clips-out` | `output/clips.jsonl` | clip 元数据输出 |
| `--videos-out` | `output/clip_videos.jsonl` | clip 预览 MP4 索引 |
| `--no-clip-video` | false | 关闭帧+WAV 合成 MP4 |
| `--extract-only` | false | 跳过云端调用 |
| `--clip-min-sec` / `--clip-max-sec` | 15 / 20 | clip 时长 |
| `--sample-fps` | 1.0 | Omni 帧采样率 |
| `--max-clips` | 无限制 | 最多处理 clip 数 |
| `--acoustic-panel-*` | 见环境变量 | 声学面板参数 |

---

## 11. 输出文件格式

### fusion_embeddings.jsonl

```json
{
  "clip_id": "output_0000",
  "model": "qwen3-vl-embedding",
  "dimension": 1024,
  "embedding_type": "fusion",
  "embedding": [0.01, -0.02],
  "inputs": {
    "text": "事件文本\n场景摘要\n[audio_duration_sec=13.76]\n[mel_feature ...]",
    "embedding_frame_count": 4,
    "acoustic_panel_path": ".../acoustic_panel.png",
    "acoustic_panel_config": {"panel_type": "mel", "n_mels": 128},
    "mel_matrix_path": ".../mel_matrix.csv",
    "mel_matrix_shape": [128, 256],
    "mel_feature_text": "[mel_feature ...]",
    "clip_video_path": ".../clips/output_0000/clip_preview.mp4"
  }
}
```

### labels.jsonl

```json
{
  "clip_id": "output_0000",
  "scene_summary": "场景自然语言摘要",
  "labels": {
    "L2.3.fatigue_level": {
      "value": "mild_fatigue",
      "confidence": 0.85,
      "evidence": "..."
    }
  }
}
```

### clips.jsonl（extract-only）

```json
{
  "clip_id": "output_0000",
  "duration_sec": 13.767,
  "frame_count": 56,
  "embedding_frame_count": 4,
  "acoustic_panel_path": ".../acoustic_panel.png",
  "acoustic_panel_config": {"panel_type": "mel", "n_mels": 128},
  "mel_matrix_path": ".../mel_matrix.csv",
  "mel_matrix_shape": [128, 256],
  "mel_feature_text": "[mel_feature n_mels=128 ...]",
  "clip_video_path": ".../clips/output_0000/clip_preview.mp4"
}
```

### clip_videos.jsonl

与 `clips.jsonl` 同时写入（`extract_bag` / `process_bag`），每行对应一个 clip 的 MP4 路径与编码参数：

```json
{
  "clip_id": "output_0000",
  "clip_video_path": ".../output/work/clips/output_0000/clip_preview.mp4",
  "clip_video_config": {"enabled": true, "filename": "clip_preview.mp4", "crf": 23}
}
```

若编码失败，`clip_video_path` 为 `null`，可在日志中看到 warning（`DEBUG` 级别含堆栈）。

---

## 12. 错误处理

### 异常类型

```python
from oms_multimodal import ConfigurationError, OmsMultimodalError

try:
    client = OmsMultimodalClient()  # 无 taxonomy
    client.label_clip(clip)
except ConfigurationError as e:
    print("配置错误:", e)
```

| 异常 | 场景 |
|------|------|
| `ConfigurationError` | 缺少 API Key / workspace / taxonomy |
| `ApiError` | 云端 API 失败（预留） |
| `ParseError` | rosbag 或模型 JSON 解析失败（预留） |
| `RuntimeError` | Omni / Embedding 调用失败 |
| `ValueError` | clip 无可用内容 |

### 批量处理容错

`process_bag()` 对单个 clip 失败**不中断**，错误收集在 `result.errors`：

```python
result = client.process_bag("rosbag/output.bag")
assert result.embedding_rows + len(result.errors) <= total_clips
```

---

## 13. 更多代码示例

> 更完整、可直接跑的脚本见 **`examples/`** 目录。

### 示例 E：只跑解析 + 语音识别

```python
from pathlib import Path
from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path, parse_stages, run_stages

bag = Path("rosbag/output.bag")
run_dir = Path("output/asr_probe")
client = OmsMultimodalClient(
    taxonomy_path=bundled_taxonomy_path(),
    work_dir=run_dir / "_sdk_work",
    model_backend="api",
)
ctx = client.make_run_context(run_dir, media_mode="local")
try:
    out = run_stages(ctx, bag, client, stages=parse_stages("extract,asr"), model_backend="api")
    print(out.stages_done, (run_dir / "asr.jsonl").read_text(encoding="utf-8")[:200])
finally:
    client.close()
```

### 示例 A：逐 clip 自定义后处理

```python
import json
from oms_multimodal import OmsMultimodalClient, ClipConfig

client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")

embeddings = []
labels = []

for clip in client.iter_clips("rosbag/output.bag", clip_config=ClipConfig(max_clips=10)):
    try:
        label_row, emb_row = client.process_clip(clip)
        labels.append(label_row)
        embeddings.append(emb_row)
    except Exception as exc:
        print(f"skip {clip.clip_id}: {exc}")

with open("my_labels.jsonl", "w", encoding="utf-8") as f:
    for row in labels:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
```

### 示例 B：多 bag 批处理

```python
from pathlib import Path
from oms_multimodal import OmsMultimodalClient, OutputConfig

client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")

for bag in Path("rosbag").glob("*.bag"):
    result = client.process_bag(
        bag,
        output=OutputConfig(
            embeddings_out=Path("output") / f"{bag.stem}_embeddings.jsonl",
            labels_out=Path("output") / f"{bag.stem}_labels.jsonl",
        ),
    )
    print(bag.name, result.to_dict())
```

### 示例 C：仅向量、不打标

```python
from oms_multimodal import OmsMultimodalClient

client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")

for clip in client.iter_clips("rosbag/output.bag"):
    row = client.embed_clip(clip, extra_text="in-cabin monitoring clip")
    print(len(row["embedding"]))
```

### 示例 D：独立声学面板工具

```python
from oms_multimodal import AcousticPanelConfig, render_acoustic_panel

render_acoustic_panel(
    "clip.wav",
    "panel.png",
    config=AcousticPanelConfig(panel_type="mel", n_mels=64, target_width=512),
)
```

---

## 14. 架构与限制

### Rosbag Topic 约定

| Topic | 类型 | modality |
|-------|------|----------|
| `/camera0~3/image_raw/compressed` | CompressedImage | image |
| `/audio` | AudioData | audio |
| `/audio_info` | AudioInfo | other（元数据） |
| `/event_label` | String | text |

### 模型限制

1. **Embedding API 不支持原始 audio** — 音频通过声学面板 PNG 进入 VL-embedding
2. **Embedding 单次最多 5 张图** — 4 路相机代表帧 + 1 声学面板
3. **Omni 必须 `stream=True`** — SDK 内部已处理
4. **声学面板是可视化近似** — 不等同于专用音频 embedding 模型

### 工作目录结构

```
output/work/{bag_stem}/
  frames/           # 解码后的相机帧
  clips/{clip_id}/
    audio.wav
    acoustic_panel.png
```

---

## 附录：从旧 `src` 包迁移

| 旧 import | 新 import |
|-----------|-----------|
| `from src.pipeline import LabelEmbeddingPipeline` | `from oms_multimodal import LabelEmbeddingPipeline` |
| `from src.rosbag_parser import Clip` | `from oms_multimodal import Clip` |
| `from src.acoustic_panel import AcousticPanelConfig` | `from oms_multimodal import AcousticPanelConfig` |
| `python main.py run ...` | `oms-multimodal run ...` |

旧 `src.*` 路径保留 re-export 兼容层，后续版本可能移除。

---

## 15. 术语表

| 说法 | 完整含义 |
|------|----------|
| SDK | Software Development Kit，软件开发工具包；这里特指本 Python 包 |
| bag / rosbag | ROS 录制文件（`.bag`） |
| ROS / ROS1 | Robot Operating System（机器人操作系统）；本 SDK 读的是 ROS1 录制格式 |
| clip | 从 bag 切出的一小段时间窗口（默认约 15～20 秒） |
| topic / 话题 | bag 里一类消息通道，例如某路摄像头图像 |
| modality / 模态 | 消息类型归属：图像、音频、文本等 |
| ASR | Automatic Speech Recognition，自动语音识别（语音转文字） |
| Omni | 文中指用于场景打标的多模态大模型（默认 `qwen3.5-omni-plus`） |
| embedding / 向量 | 把一段多媒体内容映射成的数值向量，便于相似度搜索 |
| taxonomy / 标签体系 | 定义有哪些标签、如何解释的 YAML 文件 |
| Mel / Mel 谱 | 一种更符合人耳感知的音频频谱表示 |
| DashScope / 百炼 | 阿里云提供大模型 HTTP 调用的产品 |
| MaxCompute | 阿里云大数据计算服务；`MODEL_BACKEND=mc` 时走这条路径 |
| `MODEL_BACKEND=api` | 用百炼 HTTP 调用模型（本机试用默认） |
| `MODEL_BACKEND=mc` | 用 MaxCompute / MaxFrame AI 调用模型（进阶） |
| `run_stages` | 按步骤名组合执行流水线的推荐入口 |
| `jsonl` | JSON Lines：每行一个 JSON 对象的文本文件 |
| ffmpeg | 常用的音视频转码工具；生成预览 MP4 时可能用到 |

