# HMI（校核 Web）

FastAPI + React；默认 **local** 数据源（`data/hmi_local/`）。管线与 OSS 见 [`../pipeline/README.md`](../pipeline/README.md)。

## 目录

| 路径 | 说明 |
|------|------|
| `backend/` | API · `python run.py`（默认 8000） |
| `frontend/` | Vite + React · `npm run dev` |
| `data/hmi_local/` | SQLite + sdk_v1 artifacts |
| `data/real_data/` | SDK 跑批导入源 |
| `scripts/` | `sync_hmi_local`、`import_real_data_clips` |
| `deploy/` | 生产 Docker / nginx |

## 安装

```powershell
cd hmi
py -3 -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 以 editable 方式安装 `oms-multimodal-sdk[bbox]`（含 **ultralytics**）。管线参数选 `BBOX_DETECTOR=yolo` 时需要该 extra；缺省会在保存设置 / 跑批前给出明确错误。

仅装核心 SDK（无 YOLO）时：`pip install -e ../piplinesdk`。

## 运行

```powershell
# 终端 1
cd hmi\backend
py -3 run.py

# 终端 2
cd hmi\frontend
npm run dev
```

## 同步与导入

```powershell
cd hmi
py -3 scripts\sync_hmi_local.py --clip-id sha256:...
py -3 scripts\import_real_data_clips.py --source pipeline_latest --reset
```

配置与 MC/OSS 凭证：仓库根 `.env` + [`../shared/config.yaml`](../shared/config.yaml)。

## 文档

- [`backend/README.md`](backend/README.md)
- [`frontend/README.md`](frontend/README.md)
- [`../docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md)
