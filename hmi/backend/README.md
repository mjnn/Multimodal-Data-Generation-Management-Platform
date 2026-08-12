# Rosbag HMI Backend

FastAPI 服务；支持 **本地**（`hmi/data/hmi_runtime/`：SQLite + artifacts）与 **在线**（MaxCompute `aig_sdk__*` + OSS bucket2）。

## 安装

在仓库根目录：

```bash
cd hmi/backend
pip install -r requirements.txt
```

SDK 联调（editable）：

```bash
cd hmi
pip install -r requirements-dev.txt
```

使用项目根目录 `.env`（与管线验数相同）：

- `ODPS_PROJECT` / `ODPS_ACCESS_ID` / `ODPS_ACCESS_KEY`
- `OSS_BUCKET`（sdk_v1：`rosbag-labels-pipeline-bucket2`）/ `OSS_ENDPOINT`

`shared/config.yaml` → `cloud.maxcompute.table_prefix: aig_sdk__`（HMI `get_settings()` 读取）。

## 在线模式（读 aig_sdk__ + bucket2）

```bash
# 可选：环境变量强制在线（否则 UI 侧栏切「在线」）
set HMI_DATA_SOURCE=cloud
cd hmi/backend && python run.py
```

- 总览 / clip 标签：`aig_sdk__dim_clip`、`fact_clip_label`、`fact_clip_embedding`、`fact_audio_segment`
- OSS preview：`clips/{clip_id}/runs/{run_id}/preview/`（MP4 主观验收见 M9.3 H-2）
- 帧级 `fact_image_label` / `fact_frame` **不在** sdk 表集；在线帧检索/相似会空返回

### 在线触发 DataWorks 管线（管线管理）

HMI「在线」下「上传并触发云端管线」会：上传 bag → OSS → `RunManualDagNodes` 启动已发布的**手动业务流程**（hybrid `sdk_pipeline_driver`）→ 队列轮询 MC/`dispatch` + Dag 状态。

在仓库根 `.env` 配置（AK 复用 `ODPS_ACCESS_ID` / `ODPS_ACCESS_KEY`，需具备 DataWorks 运维权限）：

```bash
DATAWORKS_PROJECT_NAME=<工作空间英文标识，非显示名>
DATAWORKS_TRIGGER_MODE=smoke        # smoke=CreateDagTest（周期节点如 p0）；manual=RunManualDagNodes；auto=有 FLOW 先 manual 失败回退 smoke
DATAWORKS_FLOW_NAME=                # manual/auto 时填已发布「手动业务流程」名；smoke 可留空
DATAWORKS_NODE_ID=<Driver 节点数字 ID>
DATAWORKS_PROJECT_ENV=PROD          # 或 DEV
DATAWORKS_REGION_ID=cn-shanghai
# 可选：DPE_IMAGE / OSS_RAM_ROLE_ARN（写入节点参数）；DATAWORKS_EXTRA_PARAMS=ai_media_mode=oss_url
```

非密钥默认参数：`hmi/backend/hmi/services/dataworks_sdk_pipeline_defaults.yaml`（可用 `DATAWORKS_DEFAULT_PARAMS` 指向自定义 YAML）。

依赖：`pip install -r hmi/backend/requirements.txt`（含 `alibabacloud_dataworks_public20200518`）。

API：`POST/GET /api/pipeline/executions`（cloud 分支）；缺配置时 POST 返回 **503**（不再 501）。

### 孤儿 bag 兜底轮询

主路径是 HMI「上传并触发」。另有后台轮询扫描 OSS，补触发「已上传但未走 OpenAPI」的 bag（例如仅 `POST /api/upload/rosbag`、触发失败留下的对象）。

```bash
HMI_CLOUD_BAG_POLL_ENABLED=1          # 默认开；FORCE_OFF=1 可关
HMI_CLOUD_BAG_POLL_INTERVAL_SEC=60
HMI_CLOUD_BAG_POLL_MIN_AGE_SEC=180    # 宽限期，避免与 API 触发竞态
HMI_CLOUD_BAG_POLL_MAX_AGE_SEC=604800 # 默认 7 天内
HMI_CLOUD_BAG_POLL_MAX_BAGS=4         # 每轮最多触发个数
# HMI_CLOUD_BAG_POLL_PREFIXES=rosbags/,other/   # 默认：oss_data_prefix + rosbags/
```

状态：`GET /api/health` → `cloud_bag_poller`；`GET /api/pipeline/cloud-bag-poller`；手动扫：`POST /api/pipeline/cloud-bag-poller/scan`。

判定：不在 `cloud_pipeline_jobs.json`、且 MC `dim_clip` 无该 `bag_oss_key`、且超过宽限期 → `RunManualDagNodes`。

## 本地数据源

从云端同步 MC 表 + OSS 产物到本地（需 `.env` 中 ODPS/OSS 凭证）：

```bash
cd hmi
python scripts/sync_hmi_local.py --clip-id sha256:...
# 仅同步表、不下载 OSS：--skip-oss
```

本地图像/音频由 `GET /api/local-files/clips/{clip_id}/runs/{run_id}/...` 提供。

### ECS 自动 sync（方案 B：轮询 OSS dispatch）

DataWorks 工作流无需回调公网。HMI 后台轮询 `pipeline/dispatch/latest.json`，发现新 `clip_id/run_id` 后执行 `sync_hmi_local.py`。

在 ECS `.env` 或 `compose` 环境变量中启用：

```bash
HMI_OSS_SYNC_POLL_ENABLED=1
HMI_OSS_SYNC_POLL_INTERVAL_SEC=30   # 默认 30
HMI_OSS_SYNC_AUTO_LOCAL=1           # sync 成功后切 local（默认开；若当前已是 cloud/在线则跳过，避免冲掉在线浏览）
```

状态：`GET /api/sync/poller` · `GET /api/health` 的 `oss_sync_poller` 字段。

## 启动

```bash
# 项目根目录已配置 .env 时
cd hmi/backend
python run.py
# → http://127.0.0.1:8000/api/health
```

## 前端联调

```bash
# 终端 1（仓库根）
cd hmi/backend && python run.py

# 终端 2
cd hmi/frontend && npm run dev
```

## API 与 MC 表映射（sdk_v1 / 在线）

| 端点 | MC / OSS |
|------|----------|
| `GET /api/clips` | `aig_sdk__dim_clip` + `pipeline_*` + `fact_clip_label` |
| `GET /api/clips/{id}/timeline-meta` | clip 标签 + `fact_audio_segment`（无帧表时 frames 空） |
| `GET /api/similar` | sdk 表集暂无帧向量（空列表） |

遗留 v2 帧表（`fact_image_label` / `fact_embedding`）仅在非 `aig_sdk__` 前缀时使用。
