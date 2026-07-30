# 本地测试运行时（local runtime）

HMI **本地模式**默认使用本目录（可通过环境变量 `HMI_RUNTIME_ROOT` 覆盖，ECS 上同样指向磁盘路径即可）。

## 布局

```text
hmi_runtime/
├── config.json          # data_source: local | cloud（UI 切换会写入）
├── hmi.db               # SQLite，镜像 MaxCompute 表（本地模式读此库）
├── artifacts/clips/     # HMI 播放与校核用的 run 产物（SDK 管线 + import 写入）
├── work/sdk_runs/       # SDK 单次推理工作目录（worker 临时）
└── oss/                 # 模拟 OSS 桶前缀（rosbags/ clips/ pipeline/ …）
    ├── rosbags/         # HMI 上传的 .bag（本地 SDK 轮询入口）
    ├── clips/
    ├── pipeline/
    ├── config/
    ├── reviews/
    └── datasets/
```

## 初始化

```powershell
cd hmi
py -3 scripts\init_local_runtime.py
py -3 scripts\seed_demo_clip_data.py --reset   # 可选：写入演示 Clip
```

## 本地管线（上传 → SDK → 总览）

1. HMI 侧栏选 **本地模式**，在 OSS/上传页上传 `.bag` → 写入 `oss/rosbags/<集合名>/`。
2. 后端 **local SDK poller**（`HMI_LOCAL_SDK_POLL_ENABLED`，默认开）发现 `pipeline_run.status=pending` 的 clip，调用本仓库 **OMS Multimodal SDK** 跑 infer，再 `import_real_data_clips.py --from-path` 落盘到 `artifacts/clips/` 并更新 `pipeline_step`。
3. **数据总览** 读 SQLite 中的 `pipeline_run` / `pipeline_step` 展示进度（运行中页面会自动刷新）。

可选：一次性导入历史批次（仍用 import，不再维护独立 sync 脚本）：

```powershell
py -3 scripts\import_real_data_clips.py --from-path D:\path\to\pipeline_latest --reset
```

## 与在线模式

| 模式 | 元数据 | 文件 |
|------|--------|------|
| **本地** | `hmi.db` | `artifacts/`（runtime，OSS 同步后） + `oss/`（模拟云端桶） |

SDK 跑完后产物先写入 **`oss/clips/{clip_id}/runs/{run_id}/`**（与云端 sdk_v1 布局一致），并更新 `oss/pipeline/dispatch/latest.json`。打开 OSS 管理里的 **「OSS 同步到本地」** 后，轮询会把 `oss/clips/…` 同步到 `artifacts/` 并刷新 `hmi.db`。

在 HMI 侧栏切换「本地模式 / 在线模式」会调用 `POST /api/config/data-source` 并刷新页面。

## 环境变量（常用）

| 变量 | 说明 |
|------|------|
| `HMI_RUNTIME_ROOT` | 本目录绝对路径 |
| `HMI_DATA_SOURCE` | `local` / `cloud` |
| `HMI_LOCAL_SDK_POLL_ENABLED` | `1` 开启本地 SDK 轮询（默认 local 下为开） |
| `HMI_LOCAL_SDK_POLL_INTERVAL_SEC` | 轮询间隔秒（默认 20） |
| `HMI_LOCAL_SDK_PARALLEL` | 同时跑 SDK 的 clip 数（1–8）。**未设置时**使用 HMI「执行参数」里的 **SDK 并发 clip 数**（`pipeline_settings.json`）；设置本变量则**覆盖**界面配置 |
| `STORAGE_BACKEND` | SDK 存储后端 `local` / `cloud` |
