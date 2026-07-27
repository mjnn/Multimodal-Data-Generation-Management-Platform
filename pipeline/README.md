# Pipeline（云端 + 本地解析）

MaxCompute / OSS / DataWorks 管线与 **SDK v1** 上云脚本。HMI 见 [`../hmi/README.md`](../hmi/README.md)。

## 目录

| 路径 | 说明 |
|------|------|
| `dataworks/` | Job0–4 与 `sdk_infer_node.py`、bundled 粘贴包 |
| `sql/maxcompute/` | `aig_sdk__` / `aig_rosbag__` DDL |
| `clips/` | 本地 clip + rosbag（Job1 开发） |
| `data/` | `parse_records.db`、`timeline.db` |
| `scripts/` | `ingest_sdk_run_to_mc`、`publish_sdk_dispatch`、`verify_pipeline_run`、bundle |

## 配置

- 主配置：[`../shared/config.yaml`](../shared/config.yaml)（`project_root: ../pipeline`）
- 环境变量：仓库根 [`.env`](../.env)（勿提交）

## 常用命令

```powershell
cd pipeline
py -3 parse_rosbag.py --config ..\shared\config.yaml
py -3 scripts\verify_pipeline_run.py --clip-id sha256:...
py -3 scripts\bundle_all_dataworks.py
py -3 scripts\ingest_sdk_run_to_mc.py --clip-id sha256:... --run-id ... --ds yyyyMMdd
```

## 文档

- [`dataworks/WORKFLOW.md`](dataworks/WORKFLOW.md)
- [`dataworks/PIPELINE_DEVELOPER_GUIDE.md`](dataworks/PIPELINE_DEVELOPER_GUIDE.md)
- [`../docs/sdk-first-pipeline-design.md`](../docs/sdk-first-pipeline-design.md)
