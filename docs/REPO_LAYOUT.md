# 仓库目录说明（Monorepo）

Git 根目录：`rosbag_to_labels_pipline/`（本文件所在仓库根下的 `docs/`）。

## 顶层一览

```text
rosbag_to_labels_pipline/
├── README.md                 # 仓库入口
├── docs/                     # 产品 / 管线 / HMI 文档（含 WIKI、PRD、sdk-first 设计）
├── shared/                   # 跨模块配置与工具
│   ├── config.yaml           # OSS / MC / Job 配置（project_root → pipeline/）
│   ├── config/               # Taxonomy 等
│   ├── cloud_config.py
│   ├── clip_id.py
│   └── repo_paths.py         # REPO_ROOT / HMI_ROOT / PIPELINE_ROOT 常量
├── piplinesdk/               # oms-multimodal-sdk 源码 + wheel
├── pipeline/                 # 云端 Job0–4、SDK 上云、本地 parse、MC DDL
│   ├── README.md
│   ├── dataworks/            # DataWorks 节点与 bundled
│   ├── sql/                  # MaxCompute DDL
│   ├── docker/               # DPE 镜像
│   ├── cloud/                # 本地提交 MaxFrame 等
│   ├── clips/                # 本地 clip 样本（含 rosbag）
│   ├── data/                 # parse_records.db、timeline.db
│   └── scripts/              # 上云、验数、bundle、ingest_sdk_run_to_mc 等
├── hmi/                      # 校核 Web（FastAPI + React）
│   ├── README.md
│   ├── backend/              # `python run.py` 入口
│   ├── frontend/
│   ├── deploy/               # Docker / nginx
│   ├── data/                 # hmi_local、hmi_runtime、real_data、app.db
│   └── scripts/              # sync_hmi_local、import_real_data_clips 等
├── archive/                  # 不再维护的脚本与历史参考
│   ├── legacy-scripts/       # mock Job2–4、uniform_sync 测试等
│   ├── ref/                  # 旧 spec / notebook
│   └── workspace-scratch/    # 根目录临时 py、reset-cloud-env
├── project-management/       # 工单与 CURRENT.md（见 AGENTS.md）
└── .cursor/rules/            # Cursor 项目规则
```

## 路径约定（代码）

| 常量 | 含义 |
|------|------|
| `REPO_ROOT` | Git 仓库根 |
| `shared/config.yaml` | 云端 bucket、表前缀、`aig_sdk__` 等 |
| `PIPELINE_ROOT` | `pipeline/` — Job 节点、clips、parse DB |
| `HMI_ROOT` | `hmi/` — 后端、前端、本地 SQLite 与 artifacts |

Python 入口脚本应：

```python
REPO_ROOT = Path(__file__).resolve().parents[2]  # 位于 hmi/scripts 或 pipeline/scripts
sys.path.insert(0, str(REPO_ROOT / "shared"))
from repo_paths import CONFIG_PATH, ENV_PATH
```

HMI 后端：`hmi/backend/hmi/config.py` 已指向 `shared/config.yaml`。

## 开发命令

```powershell
# 全量（HMI + 管线依赖 + editable SDK）
cd hmi
py -3 -m pip install -r requirements-dev.txt

# 后端
cd hmi\backend
py -3 run.py

# 前端
cd hmi\frontend
npm run dev

# 同步 MC+OSS → 本地
cd hmi
py -3 scripts\sync_hmi_local.py --clip-id sha256:...

# 导入 real_data → 本地 sdk_v1
py -3 scripts\import_real_data_clips.py --source pipeline_latest --reset

# 本地 Job1 解析（legacy）
cd pipeline
py -3 parse_rosbag.py --config ..\shared\config.yaml
```

## 相关说明

- **SDK 主路径**：`piplinesdk` + `pipeline/dataworks/sdk_infer_node.py` + `aig_sdk__`
- **Legacy Job1–4 / clip-omni v2**：节点仍在 `pipeline/dataworks/`，新数据勿写 `parsed/aligned/ai`；mock 脚本在 `archive/legacy-scripts/`

## 文档索引

| 主题 | 路径 |
|------|------|
| 总览 | `docs/WIKI.md` |
| 目录 | `docs/REPO_LAYOUT.md` |
| SDK-first | `docs/sdk-first-pipeline-design.md` |
| DataWorks | `pipeline/dataworks/WORKFLOW.md` |
| HMI 后端 | `hmi/backend/README.md` |
| SDK | `piplinesdk/README.md` |
| Agent 工单 | `AGENTS.md` · `project-management/CURRENT.md` |
