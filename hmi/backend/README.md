# Rosbag HMI Backend

FastAPI 服务；HMI 浏览固定 **local**（`data/hmi_local/`：SQLite + 本地 artifacts），对接真实 sync 数据。

## 安装

```bash
cd backend
pip install -r requirements.txt
```

SDK 联调（editable）：

```bash
cd hmi
pip install -r requirements-dev.txt
```

使用项目根目录 `.env`（与 `scripts/verify_pipeline_run.py` 相同）：

- `ODPS_PROJECT` / `ODPS_ACCESS_ID` / `ODPS_ACCESS_KEY`
- `OSS_BUCKET` / `OSS_ENDPOINT`

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
HMI_OSS_SYNC_AUTO_LOCAL=1           # sync 成功后切 local+real（默认开）
```

状态：`GET /api/sync/poller` · `GET /api/health` 的 `oss_sync_poller` 字段。

## 启动

```bash
# 项目根目录已配置 .env 时
cd backend
python run.py
# → http://127.0.0.1:8000/api/health
```

## 前端联调

```bash
# 终端 1
cd backend && python run.py

# 终端 2（默认已对接 /api，Vite 代理到 8000）
cd frontend && npm run dev
```

## API 与 MC 表映射

| 端点 | MC / OSS |
|------|----------|
| `GET /api/clips` | `dim_clip` + 各 fact 表聚合 |
| `GET /api/clips/{id}/timeline` | `fact_frame` ±window + `fact_image_label` + `fact_audio_segment` + `fact_event` |
| `GET /api/clips/{id}/timeline-meta` | 抽样时间戳 + 事件 + ASR 段 |
| `GET /api/search/clusters` | `fact_image_label` |
| `GET /api/similar` | `fact_embedding`（NumPy 余弦） |
| `POST /api/upload/rosbag` | OSS `rosbags/` + 轮询 `dim_clip` / `pipeline_step` |

图像 URL：`clips/{clip_id}/runs/{run_id}/{image_path}` 预签名。
