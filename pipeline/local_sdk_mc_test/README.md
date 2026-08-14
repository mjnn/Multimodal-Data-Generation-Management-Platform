# Local SDK 联调（优先本机；MC / DataWorks 可选）

本目录对齐 SDK 原子能力；**默认可先无 MC** 调通 extract / bbox / encode / taxonomy，再开 `MODEL_BACKEND=mc`。

## 文件

| 文件 | 说明 |
|------|------|
| **`run_local_sdk_smoke.py`** | **推荐起步**：无 MC — taxonomy 树检查 + `extract→bbox→encode` |
| `sdk_full_pipeline_demo.ipynb` | Jupyter 全量演示（可接 MC 打标/向量） |
| `run_pipeline.py` | 命令行串行：`extract → encode → asr → …`（可插入 `bbox`） |
| `run_mc_oss_verify.py` | 本机 MC + OSS + MC ingest（需要 ODPS） |
| `sdk_*_node.py` | 单节点脚本（含 `sdk_bbox_node` / `sdk_encode_node`） |
| `sdk_node_common.py` | `.env` 加载、`build_sdk_client()` |
| `.env.example` | 环境变量模板（含 taxonomy 深度 / bbox 元素） |

## 准备（本地无 MC）

1. Python **3.11 / 3.12**
2. 安装 SDK（不必装 `[mc]`）：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\piplinesdk
pip install -e .
```

3. 配置：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline\local_sdk_mc_test
copy .env.example .env
# 至少填：BAG_LOCAL_PATH、RUN_OUT_DIR
```

## 本地冒烟（taxonomy + bbox，不跑 ASR/Label）

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline\local_sdk_mc_test
py -3.11 run_local_sdk_smoke.py --taxonomy-only          # 只验取值树裁剪
py -3.11 run_local_sdk_smoke.py --detector stub            # extract→bbox→encode
py -3.11 run_local_sdk_smoke.py --detector opencv          # OpenCV Haar，元素名见 BBOX_ELEMENT
py -3.11 run_local_sdk_smoke.py --skip-extract --detector stub
```

相关 `.env`：

| 变量 | 说明 |
|------|------|
| `LABEL_TAXONOMY_DEPTH` | `0` 全树；`1` 仅粗粒度 |
| `LABEL_TAXONOMY_DEPTH_BY_DIM` | 如 `L1.3=2,L1.1=1` |
| `LABEL_TREE_OUTPUT` | `leaf` / `path` / `ancestors` |
| `BBOX_DETECTOR` | `noop` / `stub` / `opencv` / `yolo`（`yolo` 需 `pip install -e "../../piplinesdk[bbox]"`） |
| `BBOX_ELEMENT` | 通用元素名（默认 `element`） |
| `ENCODE_PLAIN` / `ENCODE_BBOX` | 是否出原视频 / 带框视频（**ENCODE_BBOX 已废弃忽略**） |

SDK 提供 **取值树脚手架**（`enum_tree_node` / `make_enum_tree_schema` / `tree_depth` / 深度裁剪）；业务树由平台作者维护。仓库可不维护完整业务树（可选保留 `L1.3.weather` 一条最小示例）。

## 带 AI 的全链（可选 MC）

**Notebook：**

```powershell
jupyter notebook sdk_full_pipeline_demo.ipynb
```

**命令行：**

```powershell
py -3 run_pipeline.py extract bbox encode asr preview label embed
py -3 run_pipeline.py extract encode
```

**本机 MC + OSS 验数（需要 ODPS）：**

```powershell
pip install -e "D:\cursor_project\rosbag_to_labels_pipline\piplinesdk\.[mc]"
py -3.11 run_mc_oss_verify.py --with-extract
```

产物默认在 `output/` 或 `.env` 的 `RUN_OUT_DIR`。

**MaxFrame AI 多分区并发探针：**

```powershell
py -3.11 run_mf_ai_concurrency_probe.py --rows 4 --partitions 4
```

## MC 必填项（仅当 MODEL_BACKEND=mc）

| 变量 | 用途 |
|------|------|
| `MODEL_BACKEND=mc` | 走 MaxFrame AI Function |
| `ODPS_PROJECT` / `ODPS_ACCESS_ID` / `ODPS_ACCESS_KEY` / `ODPS_ENDPOINT` | PyODPS session |
| `OSS_BUCKET` | modelset / OSS URL 模式 |
| `DPE_IMAGE` | MaxFrame DPE UDF（上云；本机 extract 可不跑 DPE） |
| `OSS_RAM_ROLE_ARN` | DPE `@with_fs_mount`（上云） |
| `MC_MODELSET_PROJECT` | 默认 `bigdata_public_modelset` |
| `MC_OMNI_NATIVE_MEDIA` | 默认 `true`；Omni：`cp.video` + `cp.audio` + `cp.text`（含 ASR） |

**MaxFrame 2.8+ 验数字段**（`labels.jsonl` / `asr.jsonl`）：

| 字段 | 期望 |
|------|------|
| `asr.jsonl` → `mc_mode` | `content_part_audio` |
| `labels.jsonl` → `mc_mode` | `omni_native`（有 clip MP4 + WAV） |
| `labels.jsonl` → `mc_has_video` / `mc_has_audio_part` | `true` |
| `labels.jsonl` → `mc_has_asr_in_text` | `true`（`cp.text` 含 ASR 全文） |

关闭原生 media 做 A/B：`MC_OMNI_NATIVE_MEDIA=false`（回退 image 抽帧 + 文本 ASR）。

API 模式不在本目录演示范围内（HMI `local_sdk_worker` 使用 `MODEL_BACKEND=api`）。
