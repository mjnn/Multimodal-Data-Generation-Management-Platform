# Monorepo: OMS 数据管线 + 校核 HMI + Multimodal SDK

**目录说明（必读）：** [docs/REPO_LAYOUT.md](docs/REPO_LAYOUT.md)

| 目录 | 职责 |
|------|------|
| [`piplinesdk/`](piplinesdk/) | `oms-multimodal-sdk` 源码与 wheel |
| [`pipeline/`](pipeline/) | DataWorks / MC / OSS / 本地 parse |
| [`hmi/`](hmi/) | FastAPI + React 校核 UI |
| [`shared/`](shared/) | `config.yaml`、Taxonomy、`cloud_config` |
| [`archive/`](archive/) | 已归档脚本与参考，非主路径 |

## 快速开始（HMI 本地）

```powershell
cd hmi
py -3 -m pip install -r requirements-dev.txt
cd backend
py -3 run.py
# 另开终端: cd hmi\frontend && npm run dev
```

## Git

仓库根即本目录。`.gitignore` 已忽略 `hmi/data/hmi_local/`、`hmi/frontend/node_modules/`、本地 DB 等。

## 历史

2026-07：由单层 `rosbag_to_labels_pipline/rosbag_to_labels_pipline/` 拆为 **pipeline / hmi / shared / piplinesdk**；SDK 自 `labeling_and_embedding_test` 迁入 `piplinesdk/`。
