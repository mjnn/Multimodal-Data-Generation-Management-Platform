# Local SDK MC 联调（MaxFrame AI Function）

本目录对齐 **DataWorks sdk_* 节点**，在本地串行跑 SDK 原子能力；**默认 `MODEL_BACKEND=mc`**（MaxCompute AI Function），不是 DashScope API。

## 文件

| 文件 | 说明 |
|------|------|
| `sdk_full_pipeline_demo.ipynb` | Jupyter 全量演示（中间产物 + MC 打标/向量） |
| `run_pipeline.py` | 命令行串行：`extract → asr → preview → label → embed` |
| `sdk_*_node.py` | 与 DataWorks 同结构的单节点脚本 |
| `sdk_node_common.py` | `.env` 加载、`build_sdk_client()`、MC 校验 |
| `.env.example` | **MC + ODPS + OSS** 环境变量模板 |

## 准备

1. Python **3.11 / 3.12**（不要用 3.14 装 `[mc]`）
2. 在本目录或 `piplinesdk/` 安装 SDK：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\piplinesdk
pip install -e ".[mc]"
pip install jupyter ipykernel matplotlib python-dotenv
```

3. 配置环境变量：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline\local_sdk_mc_test
copy .env.example .env
# 填 ODPS_ACCESS_ID/KEY、OSS_BUCKET、可选 DPE_IMAGE / OSS_RAM_ROLE_ARN
```

也可在仓库根 `.env` 填 `ODPS_*` / `OSS_*`，本目录 `.env` 只补 `MODEL_BACKEND=mc` 与 `BAG_LOCAL_PATH`。

4. 同步 ossutil/odpscmd（改根 `.env` 后）：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline
py -3 scripts\sync_cloud_cli_config.py
```

## 运行

**Notebook（MC atomic capabilities，推荐）：**

```powershell
jupyter notebook sdk_full_pipeline_demo.ipynb
```

**命令行（与 DW 节点一致）：**

```powershell
py -3 run_pipeline.py              # 全链 atomic
py -3 run_pipeline.py extract asr  # 指定节点
py -3 sdk_label_node.py
```

产物默认在 `output/` 或 `.env` 的 `RUN_OUT_DIR`。

## MC 必填项

| 变量 | 用途 |
|------|------|
| `MODEL_BACKEND=mc` | 走 MaxFrame AI Function |
| `ODPS_PROJECT` / `ODPS_ACCESS_ID` / `ODPS_ACCESS_KEY` / `ODPS_ENDPOINT` | PyODPS session |
| `OSS_BUCKET` | modelset / OSS URL 模式 |
| `DPE_IMAGE` | MaxFrame DPE UDF（上云；本机 extract 可不跑 DPE） |
| `OSS_RAM_ROLE_ARN` | DPE `@with_fs_mount`（上云） |
| `MC_MODELSET_PROJECT` | 默认 `bigdata_public_modelset` |

API 模式不在本目录演示范围内（HMI `local_sdk_worker` 使用 `MODEL_BACKEND=api`）。
