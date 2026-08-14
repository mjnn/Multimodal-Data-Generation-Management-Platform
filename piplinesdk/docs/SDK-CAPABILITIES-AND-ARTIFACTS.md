# OMS Multimodal SDK：能力与产物说明（小白版）

> 包名：`oms-multimodal-sdk` · 目录：`piplinesdk/`  
> 读者：第一次接触本 SDK、不要求懂 ROS / DataWorks / MaxCompute  
> 更细的 API / 环境变量：见同目录 [SDK.md](./SDK.md)

---

## 1. 一句话：这 SDK 干什么？

把一份 **车载录制（`.bag`）**，或你上传的 **视频 / 音频 / 文本**，切成一段段短片（叫 **clip**），再产出：

- 给人看的画面与声音（预览）
- （可选）画面上「框出了什么物体」的检测结果
- （可选）语音转成的文字
- （可选）场景标签（按你的标签表）
- （可选）一段数字向量（用来做相似检索）

你可以只做「拆开 bag、导出媒体」（完全离线），也可以再打开云端 AI 步骤。

---

## 2. 先搞懂 4 个词

| 词 | 通俗意思 |
|----|----------|
| **Bag** | 一整段 ROS 录制文件（`.bag`），里面有多路相机、麦克风等「话题」 |
| **Clip** | 从 bag 里切出来的一小段时间（常见约 15～20 秒），后续处理的基本单位 |
| **能力（Capability）** | SDK 里的一步工序，例如「检测画框」「语音识别」「打标」 |
| **产物（Artifact）** | 某一步写到磁盘上的文件，例如 `labels.jsonl`、`preview/*.mp4` |

**运行目录 `run_dir`**：这次任务的结果都落在这里（jsonl、preview、run.json）。  
**工作目录 `work_dir`**：中间媒体（按 clip 分的帧图、wav 等），通常在 `run_dir` 旁边或内部。

---

## 3. 整体流水线（一张图）

```text
输入：.bag  或  原始视频/音频/文本
        │
        ▼
 ┌─ 入库 / 解析 ─────────────────────────────┐
 │  ingest（上传媒体） 或  extract（解析 bag） │
 │  → 得到 clips_index + 帧 / 音频 /（常有）预览片 │
 └──────────────────────┬────────────────────┘
                        │
        （可选）annotate_bbox → bboxes.jsonl + *_bbox.jpg
                        │
        （可选）encode_preview → 无框预览 MP4（plain）
                        │
        （可选）ASR 语音识别 → asr.jsonl
                        │
        （可选）Label 场景打标 → labels.jsonl
                        │
        （可选）Embed 融合向量 → fusion_embeddings.jsonl
                        │
        materialize_preview → preview/ 给人看的目录
                        │
                        ▼
                   run.json（本次跑了哪些步）
```

**重要（2026-08 起）**：SDK **不再烧录「带框预览 MP4」**。  
框的权威数据是 `bboxes.jsonl`；HMI 总览/校核用「原图 + 叠加框」显示，不依赖 `clip_preview_bbox_*.mp4`。

---

## 4. 能力一览（每个能力做什么、要不要联网、产出什么）

下表按 **推荐执行顺序** 排列。步骤名是短名（给 `run_stages` / CLI 用）；函数名是 Python API。

| 顺序 | 步骤名 | Python 能力 | 要联网？ | 一句话 | 主要产物 |
|:----:|--------|-------------|---------|--------|----------|
| 0 | （工具） | `inspect_bag` | 否 | 只看 bag 里有哪些话题，不写结果 | （无文件，返回列表） |
| 1a | `ingest` | `ingest_sources` | 否 | 没有 bag、只有视频/音频/文本时：抽帧、拷贝音频，做成 clip | `clips_index.jsonl`、媒体目录；已有 MP4 时常 **跳过** 再编码 |
| 1b | `extract` | `extract_clips` | 否 | 解析 `.bag`，切 clip，导出多路帧、音频、声学图等 | `clips_index.jsonl`、`clip_videos.jsonl`、各 clip 媒体 |
| 2 | `bbox` | `annotate_bboxes` | 否（本机检测） | 在帧上检测物体/人脸等，画框（原图不改） | `bboxes.jsonl`、同目录 `*_bbox.jpg` |
| 3 | `encode` | `encode_preview_videos` | 否 | 把帧编成 **无框** 预览 MP4 | 更新 `clip_videos.jsonl`；各路 `clip_preview_cameraN.mp4` |
| 4 | `asr` | `transcribe_clips` | **是** | 语音 → 文字 | `asr.jsonl` |
| 5 | `preview` | `materialize_preview` | 否 | 把预览视频/音频整理到统一 `preview/` | `preview/manifest.json`、`preview/*.mp4`、`preview/audio.wav` 等 |
| 6 | `label` | `label_clips` | **是** | 多模态模型按 Taxonomy 打场景标签 | `labels.jsonl` |
| 7 | `embed` | `embed_clips` | **是** | 多模态融合向量（检索用） | `fusion_embeddings.jsonl` |
| — | （编排） | `run_stages` / `plan_and_run` | 视步骤 | 按你选的步骤串起来跑 | 上述产物的组合 |
| — | （一键） | `infer_full` | 视配置 | 常见全链路复合（extract→可选 bbox→encode→asr→label→embed→preview） | 同上 |
| — | （元数据） | `write_run_json` | 否 | 记录本次跑了什么 | `run.json` |

### 4.1 开关怎么理解？

| 你想开的 | 怎么开（环境变量 / HMI 设置） | 说明 |
|----------|-------------------------------|------|
| 帧级检测 | `BBOX_ENABLED=1` + `BBOX_DETECTOR=opencv\|yolo\|stub\|noop` | 写 `bboxes.jsonl`；**不**再烧带框视频 |
| 无框预览 MP4 | `ENCODE_PLAIN=1`（默认常开） | 总览「原图预览」用的片源 |
| 带框预览 MP4 | ~~`ENCODE_BBOX`~~ | **已废弃**，设置了也会被忽略 |
| 打标时参考检测结果 | `BBOX_IN_LABEL_PROMPT=1` | 把检出元素摘要塞进 Omni 提示 |
| 云端模型走哪条路 | `MODEL_BACKEND=api`（试用）或 `mc`（MaxCompute） | 影响 ASR / Label / Embed |

### 4.2 检测器（bbox）简表

| 检测器 | 适合 | 额外依赖 |
|--------|------|----------|
| `noop` | 占位，几乎不检出 | 无 |
| `stub` | 本机冒烟测试（假框） | 无 |
| `opencv` | 人脸等（可带性别/年龄属性） | OpenCV；权重可自动下载 |
| `yolo` | 通用物体（COCO 类） | `pip install -e ".[bbox]"`（ultralytics） |

检测框里的对象叫 **element（元素）**，和业务 **Taxonomy 标签树** 不是同一套东西。

---

## 5. 产物清单（磁盘上会长什么样）

### 5.1 运行目录根上的「结果表」（jsonl = 一行一条 JSON）

| 文件 | 谁写的 | 小白怎么理解 |
|------|--------|--------------|
| `clips_index.jsonl` | ingest / extract | 「这次有哪些 clip、各自时长/路径」的总目录 |
| `clip_videos.jsonl` | extract / encode | 每个 clip 的预览 MP4 路径登记 |
| `bboxes.jsonl` | bbox | **框的权威数据**（相机、时间戳、坐标、element、分数…） |
| `asr.jsonl` | asr | 这段 clip 里人说了什么 |
| `labels.jsonl` | label | 场景标签（按你的 Taxonomy） |
| `fusion_embeddings.jsonl` | embed | 一段向量 + 用了哪些图/文输入的说明 |
| `run.json` | 编排结束 | 本次步骤、版本、错误摘要 |

### 5.2 每个 clip 的工作媒体（示意）

路径因配置略有不同，常见形态：

```text
work/…/clips/output_0000/          # 或类似结构
  camera0/…/*.jpg                  # 原图帧（不覆盖）
  *_bbox.jpg                       # 画了框的旁路图（可选）
  audio.wav                        # 音频
  acoustic_panel.png               # 声学频谱图（可选）
  mel_matrix.csv                   # Mel 特征（可选）
  clip_preview_camera0.mp4         # 无框预览（encode / extract 配置打开时）
  …
```

### 5.3 `preview/`（给人点开看的目录）

由 `materialize_preview` 整理，常见内容：

| 路径 | 含义 |
|------|------|
| `preview/manifest.json` | 预览清单（相机、相对路径、fps 等） |
| `preview/clip_preview_cameraN.mp4` | 各路无框预览 |
| `preview/audio.wav` | 预览用音频 |

> 历史跑批可能还留有 `clip_preview_bbox_cameraN.mp4`；**新管线不再生成**。看框请用 `bboxes.jsonl`（或 HMI 叠加层）。

### 5.4 输入不是 bag 时（ingest）

若 `source_manifest.json` 指向视频/音频/文本：

- 有视频 → 抽帧给 VL，原 MP4 常直接当预览（**不再**走 encode）
- 有音频 → 供 ASR
- 有文本 → 可作为打标上下文

---

## 6. 三种常见用法（对照表）

| 场景 | 建议步骤 | 你会得到 |
|------|----------|----------|
| 只想拆开 bag 看看 | `extract`（+ 可选 `preview`） | 帧、wav、clips_index；可选 preview |
| 本机检测 + 预览，不调大模型 | `extract,bbox,encode,preview` | jsonl 框 + 无框 MP4 + preview/ |
| 全链路打标检索 | `extract` →（可选 bbox）→ `encode` → `asr` → `label` → `embed` → `preview` | 上表几乎全部产物 |
| 上传了现成 MP4 | `ingest` → asr/label/embed… | 跳过 bag 解析；通常跳过 encode |

PowerShell 示例（本机 stub 检测，不需密钥）：

```powershell
cd piplinesdk
$env:BBOX_ENABLED = "1"
$env:BBOX_DETECTOR = "stub"
$env:ENCODE_PLAIN = "1"
py -3.11 examples\03_run_stages.py extract,bbox,encode,preview
```

需要 ASR / 打标 / 向量时，再配置 `DASHSCOPE_API_KEY`（`MODEL_BACKEND=api`）或 MaxCompute（`mc`）。

---

## 7. 和本仓库 HMI 的关系（记一句就够）

| HMI 页面 | 看什么 |
|----------|--------|
| 数据总览 · 原图预览 | plain MP4，无框 |
| 数据总览 · 带识别框预览 | plain MP4 + **只读**读 `bboxes.jsonl` 叠加 |
| 校核 · 原图参考 | plain，无框 |
| 校核 · 带可编辑框 | plain + **可编辑** jsonl，保存写回 `bboxes.jsonl` |

管线参数面板里的「启用 BBox」对应 SDK 的 `annotate_bbox`，**不是**「再烧一条带框视频」。

---

## 8. 不要和这些搞混

| 容易混的 | 澄清 |
|----------|------|
| `bboxes.jsonl` vs 烧录带框 MP4 | **jsonl 才是框数据**；带框 MP4 能力已去掉 |
| element vs Taxonomy 标签 | 检测元素 ≠ 场景标签树 |
| `work/` 媒体 vs `preview/` | work 是加工原料；preview 是整理后给人看的入口 |
| `api` vs `mc` | 两种调模型后端，产物文件名相同，调用路径不同 |
| 旧 clip-omni v2 管线 | 新数据以本 SDK + `aig_sdk__*` 为准（见仓库管线文档） |

---

## 9. 还想继续读哪里？

| 文档 | 内容 |
|------|------|
| [SDK.md](./SDK.md) | 安装、配置、API、jsonl 字段样例 |
| [examples/README.md](../examples/README.md) | 可运行脚本 |
| [DATAWORKS_SDK.md](./DATAWORKS_SDK.md) | 上云 / MaxFrame 节点 |
| 仓库 `project-management/acceptance/HMI-BBOX-OVERLAY.md` | HMI 叠加框验收说明 |

---

*文档反映当前能力：预览编码仅 plain；框以 `bboxes.jsonl` 为准（2026-08）。*
