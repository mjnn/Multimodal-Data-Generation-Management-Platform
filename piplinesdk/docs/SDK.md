# OMS Multimodal SDK 文档

> 版本：`0.3.2` · 包名：`oms-multimodal-sdk` · Python ≥ 3.10

## 目录

1. [概述](#1-概述)
2. [安装](#2-安装)
3. [快速开始](#3-快速开始)
4. [认证与配置](#4-认证与配置)
5. [核心概念](#5-核心概念)
6. [OmsMultimodalClient API](#6-omsmultimodalclient-api)
7. [配置类参考](#7-配置类参考)
8. [低级 API](#8-低级-api)
9. [CLI 参考](#9-cli-参考)
10. [输出数据结构](#10-输出数据结构)
11. [错误处理](#11-错误处理)
12. [完整示例](#12-完整示例)
13. [架构与限制](#13-架构与限制)

---

## 1. 概述

**OMS Multimodal SDK** 将从 ROS1 rosbag 提取多模态 clip、调用阿里云 Qwen 模型打标与生成融合向量封装为可 `pip install` 的 Python 包。

### 能力矩阵

| 能力 | 模型 | SDK 方法 |
|------|------|----------|
| Rosbag 解析 & clip 切分 | 本地 | `iter_clips()` / `extract_bag()` |
| 声学面板渲染 | 本地 | `render_acoustic_panel()` / `render_acoustic_assets()` |
| **Mel 矩阵导出** | **本地** | `compute_mel_matrix()` / `save_mel_matrix()` → `mel_matrix.csv` |
| **Clip 预览 MP4** | **本地 ffmpeg** | `render_clip_preview_video()` / `encode_clip_mp4()` |
| **音频 ASR 文本** | **qwen3-asr-flash** | `transcribe_clip()` / 流水线默认 |
| OMS 场景理解 + 打标 | Qwen3.5-Omni-Plus | `label_clip()` / `process_bag()` |
| 多模态融合向量 | qwen3-vl-embedding | `embed_clip()` / `process_bag()` |

### 数据流

```
rosbag (.bag)
    │
    ▼
RosbagExtractor.iter_clips()
    │  15–20s clip：多相机全量帧 + WAV + Omni 采样帧
    │  + 声学面板 PNG + Mel 矩阵 (csv) + mel_feature_text + 单路全帧 MP4
    ▼
AsrClient (qwen3-asr-flash) → clip.asr_text
    ▼
┌─────────────────────┬──────────────────────┐
│  OmniLabelClient    │  FusionEmbeddingClient│
│  video + audio +    │  代表帧 + 声学面板 +  │
│  ASR + events +     │  ASR + events +       │
│  mel_feature_text + │  mel_feature_text +   │
│  taxonomy prompt    │  scene_summary 文本   │
└─────────┬───────────┴──────────┬───────────┘
          ▼                      ▼
    labels.jsonl         fusion_embeddings.jsonl
```

Mel 矩阵默认随 extract 写出 `clips/{clip_id}/mel_matrix.csv`（及 `.meta.json`）。压缩后的 `mel_feature_text` 经 `Clip.speech_context_text()` 同时注入 **Omni 打标**与 **fusion embedding** 的 text 侧；PNG 仍作为 VL-embedding 的 image 输入。

---

## 2. 安装

### 开发模式（推荐）

在项目根目录：

```bash
pip install -e .
```

安装后可使用：

- Python：`import oms_multimodal`
- CLI（推荐）：`python -m oms_multimodal`
- CLI（需 PATH）：`oms-multimodal`

### Windows：CLI 找不到命令

`pip install` 会把 `oms-multimodal.exe` 装到 Python 的 **Scripts** 目录（例如 `C:\Users\<user>\AppData\Local\Python\pythoncore-3.14-64\Scripts`）。若该目录不在 PATH，直接敲 `oms-multimodal` 会失败。

**方案 A（推荐）**：始终用模块方式调用，无需改 PATH：

```bash
python -m oms_multimodal --help
python -m oms_multimodal inspect --bag rosbag/output.bag
```

**方案 B**：把 Scripts 目录加入用户 PATH 后新开终端，即可使用 `oms-multimodal`。

**方案 C**：在项目根目录仍可用 `python main.py`。

### 仅依赖安装

```bash
pip install -r requirements.txt
# 需将项目根目录加入 PYTHONPATH，或 pip install -e .
```

### 验证安装

```bash
python -c "from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path, __version__; print(__version__, bundled_taxonomy_path())"
python -m oms_multimodal --help
```

### 安装包内资源（wheel 自带）

pip 安装后可在包目录找到：

| 文件 | 访问方式 |
|------|----------|
| `oms_label_taxonomy.yaml` | `from oms_multimodal import bundled_taxonomy_path` |
| `SDK.md` | `from oms_multimodal import bundled_sdk_doc_path` |

路径示例：`site-packages/oms_multimodal/bundled/oms_label_taxonomy.yaml`

---

## 3. 快速开始

### 3.1 环境准备

复制并填写 `.env`：

```bash
cp .env.example .env
```

必需变量：

```env
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_WORKSPACE_ID=ws-...
DASHSCOPE_REGION=cn-beijing
```

### 3.2 三行代码跑通

```python
from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path

client = OmsMultimodalClient(taxonomy_path=bundled_taxonomy_path())
result = client.process_bag("rosbag/output.bag")

print(f"embeddings: {result.embedding_rows}, labels: {result.label_rows}")
print(f"errors: {result.errors}")
```

### 3.3 仅本地提取（不调云端）

```python
from oms_multimodal import OmsMultimodalClient, ClipConfig, OutputConfig

client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")
result = client.extract_bag(
    "rosbag/output.bag",
    clip_config=ClipConfig(min_sec=15, max_sec=20),
    output=OutputConfig(clips_out="output/clips.jsonl"),
)
print(result.clip_rows)
```

---

## 4. 认证与配置

### 4.1 环境变量

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `DASHSCOPE_API_KEY` | 是 | — | 百炼 API Key，Embedding 与 Omni 共用 |
| `DASHSCOPE_WORKSPACE_ID` | Omni 必需 | — | 业务空间 ID |
| `DASHSCOPE_REGION` | 否 | `cn-beijing` | 区域 |
| `EMBEDDING_MODEL` | 否 | `qwen3-vl-embedding` | 向量模型 |
| `EMBEDDING_DIMENSION` | 否 | `1024` | 向量维度 |
| `OMNI_MODEL` | 否 | `qwen3.5-omni-plus` | 打标模型 |
| `ASR_ENABLED` | 否 | `true` | 是否启用 clip ASR |
| `ASR_MODEL` | 否 | `qwen3-asr-flash` | ASR 模型（Qwen3-ASR-Flash） |
| `ASR_LANGUAGE` | 否 | `zh` | ASR 语言提示 |
| `ASR_ENABLE_ITN` | 否 | `false` | 逆文本归一化 |
| `CLIP_VIDEO_ENABLED` | 否 | `true` | 是否生成 clip 预览 MP4 |
| `CLIP_VIDEO_FILENAME` | 否 | `clip_preview.mp4` | 每个 clip 目录下的 MP4 文件名 |
| `CLIP_VIDEO_MAX_WIDTH` / `MAX_HEIGHT` | 否 | `1280` / `720` | 帧 letterbox 画布尺寸 |
| `CLIP_VIDEO_CODEC` / `AUDIO_CODEC` | 否 | `libx264` / `aac` | ffmpeg 编码器 |
| `CLIP_VIDEO_CRF` | 否 | `23` | 视频质量（x264 CRF） |
| `MODEL_BACKEND` | 否 | `api` | 模型调用后端：`api`（DashScope/MaaS，**当前默认**）或 `mc`（MaxCompute 模型集，Omni 未上架前不可用） |
| `ACOUSTIC_PANEL_TYPE` | 否 | `mel` | 声学面板类型：`stft` / `mel` |
| `ACOUSTIC_PANEL_N_FFT` | 否 | `2048` | FFT 大小 |
| `ACOUSTIC_PANEL_HOP_LENGTH` | 否 | `512` | STFT hop |
| `ACOUSTIC_PANEL_N_MELS` | 否 | `128` | Mel 滤波器数量 |
| `ACOUSTIC_PANEL_FMIN` | 否 | `20` | Mel 最低频率 (Hz) |
| `ACOUSTIC_PANEL_FMAX` | 否 | 空（Nyquist） | Mel 最高频率 (Hz) |
| `ACOUSTIC_PANEL_WIDTH` | 否 | `768` | 面板宽度 (px) |
| `ACOUSTIC_PANEL_HEIGHT` | 否 | `256` | 面板高度 (px) |

### 4.2 代码内显式配置

环境变量可被构造函数参数覆盖：

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
    load_dotenv=True,  # 是否自动加载 .env
)
```

### 4.3 ClientConfig 批量配置

```python
from oms_multimodal import ClientConfig, OmsMultimodalClient

config = ClientConfig.from_env(taxonomy_path="oms_label_taxonomy.yaml")
config.embedding_dimension = 2048
client = OmsMultimodalClient(config=config)
```

---

## 5. 核心概念

### 5.1 Clip

最小处理单元，默认 **15–20 秒**。短于 20 秒的 bag 整体作为 1 个 clip。

| 字段 | 类型 | 说明 |
|------|------|------|
| `clip_id` | `str` | `{bag_stem}_{序号}` |
| `frames` | `list[FramePayload]` | 按 `sample_fps` 采样的多相机帧（Omni video 输入） |
| `embedding_frames` | `list[FramePayload]` | 每路相机 1 张代表帧，最多 4 张（embedding 输入） |
| `audio` | `AudioPayload \| None` | clip 级拼接 WAV |
| `acoustic_panel_path` | `str \| None` | log 频谱 / Mel 谱 PNG 路径 |
| `mel_matrix_path` | `str \| None` | Mel 矩阵 CSV 路径（默认导出） |
| `mel_feature_text` | `str \| None` | 压缩 Mel 特征文本（打标 / 向量化 text 输入） |
| `events` | `list[TextPayload]` | clip 时间范围内的事件文本 |
| `duration_sec` | `float` | clip 时长 |

### 5.2 TopicInfo

`inspect_bag()` 返回的 topic 元数据：

```python
TopicInfo(name="/camera0/image_raw/compressed", msgtype="...", modality="image", message_count=455)
```

modality 取值：`image` | `audio` | `text` | `other`

### 5.3 Taxonomy

打标标签定义在 YAML 文件（默认 `oms_label_taxonomy.yaml`），当前 68 个 OMS 标签。SDK 将其转为 Omni prompt，并解析模型返回的 JSON。

---

## 6. OmsMultimodalClient API

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

## 7. 配置类参考

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

## 8. 低级 API

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

## 9. CLI 参考

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

## 10. 输出数据结构

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

## 11. 错误处理

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

## 12. 完整示例

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

## 13. 架构与限制

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
