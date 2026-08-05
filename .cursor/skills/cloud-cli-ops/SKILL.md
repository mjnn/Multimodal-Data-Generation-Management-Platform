---
name: cloud-cli-ops
description: Operates Alibaba Cloud OSS (ossutil) and MaxCompute (odpscmd) for rosbag_to_labels_pipline—list bags, query MC tables, read dispatch manifest, verify pipeline runs. Use when the user mentions ossutil, odpscmd, OSS, MaxCompute, MC query, pipeline artifacts, dispatch manifest, rosbag-labels-pipline-bucket, rogbag_label_pipline, cloud CLI, verify run, or reset test env. Does not cover triggering DataWorks/MaxFrame jobs.
---

# Cloud CLI Ops (OSS + MaxCompute)

Project: `rogbag_label_pipline` · Region: `cn_shanghai` · Credentials: repo root `.env` (never commit).

## Scope

| In scope | Out of scope |
|----------|--------------|
| ossutil / odpscmd on **本机** | DataWorks 触发 Job0~4 |
| Python 验数/DDL/重置脚本 | 写 DataWorks 节点代码 |
| 读 `pipeline/dispatch/latest.json` | Driver 内网 OSS（见 `dataworks-dispatch-oss.mdc`） |

## Tool paths (Windows)

| Tool | Path |
|------|------|
| ossutil 2.3.0 | `D:\ossutil-2.3.0-windows-amd64\ossutil.exe` |
| odpscmd | `D:\odpscmd_public\bin\odpscmd.bat` |
| odpscmd config | `D:\odpscmd_public\conf\odps_config.ini` |
| ossutil config | `%USERPROFILE%\.ossutilconfig` |

PATH 未生效时用完整路径。odpscmd 需要 **Java 8+**（本机 Temurin JDK 21）。

## Cloud constants

| Item | Value |
|------|-------|
| MC project | `rogbag_label_pipline` |
| MC endpoint | `https://service.cn-shanghai.maxcompute.aliyun.com/api` |
| OSS bucket | `rosbag-labels-pipline-bucket` |
| OSS endpoint (本机 CLI) | `https://oss-cn-shanghai.aliyuncs.com` |
| Table prefix | `aig_rosbag__` |
| Bag prefix | `rosbags/` |
| Run prefix | `clips/{clip_id}/runs/{run_id}/` |
| Dispatch manifest | `pipeline/dispatch/latest.json` |

## Decision: CLI vs script

| Scenario | Use |
|----------|-----|
| List/read OSS objects, cat JSON | **ossutil** `ls` / `cat` |
| MC SQL / table inspect | **odpscmd** `-e` |
| Connectivity check | `python scripts/e2e_precheck.py` |
| Apply DDL | `python scripts/apply_mc_ddl.py` |
| Verify full pipeline run | `python scripts/verify_pipeline_run.py` |
| Verify **SDK v1** run | `python scripts/verify_sdk_v1_run.py` |
| Reset test OSS+MC | `python scripts/reset_cloud_test_env.py` (--dry-run first) |
| Upload bag | `scripts/upload_clip_to_oss.py` or ossutil `cp` |
| Upload taxonomy | `python scripts/upload_taxonomy_to_oss.py` |
| Trigger Job0~4 | **DataWorks console** — not CLI |

**Rule:** One-shot inspect → CLI. Multi-step OSS+MC checks → `verify_pipeline_run.py`.

## Standard workflow

```powershell
cd pipeline

# 1. After .env change (repo root .env)
py -3 scripts\sync_cloud_cli_config.py

# 2. Preflight
py -3 scripts\e2e_precheck.py

# 4. If pipeline-related
py -3 scripts\verify_pipeline_run.py --clip-id sha256:...
```

配置：`shared/config.yaml` · 布局：`docs/REPO_LAYOUT.md`

## Quick commands

```powershell
# OSS
ossutil ls oss://rosbag-labels-pipline-bucket/rosbags/ --limited-num 10
ossutil cat oss://rosbag-labels-pipline-bucket/pipeline/dispatch/latest.json
ossutil ls "oss://rosbag-labels-pipline-bucket/clips/sha256:.../runs/" --limited-num 50

# MC (PowerShell: outer double quotes, inner single quotes)
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select clip_id, active_run_id from aig_rosbag__dim_clip limit 5;"
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select step_id, status from aig_rosbag__pipeline_step where run_id='...' and ds='20260609';"
```

**PowerShell:** URI 含 `sha256:` 时必须用双引号包裹整个 `oss://...`。

## Test clip (E2E)

| Field | Value |
|-------|-------|
| clip_id | `sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b` |
| clip_dir_name | `2026-06-05_13-27-07` |
| bag_oss_key | `rosbags/2026-06-05_13-27-07/output.bag` |
| active run_id (stub E2E passed) | `6a2f479e-64b4-443e-a73c-47a0cc23d81f` |
| ds | `20260609` |

## MC tables (by Job)

| Table | Job |
|-------|-----|
| `dim_clip`, `pipeline_run`, `pipeline_step` | global |
| `fact_message_timeline`, `fact_frame`, `fact_audio_chunk`, `clip_parse_summary` | Job1 |
| `fact_sample_policy`, `fact_audio_segment` | Job2 |
| `fact_image_label` | Job3 |
| `fact_embedding` | Job4 |

## OSS run artifacts (verify checklist)

Under `clips/{clip_id}/runs/{run_id}/`:

- `parsed/job1_mc_payload.json`
- `job2/sample_manifest.jsonl`, `job2/job2_sample_payload.json`, `job2/job2_asr_payload.json`, `job2/job2_mc_payload.json`
- `job3/frame_labels.jsonl`, `job3/job3_mc_payload.json`
- `job4/embeddings.jsonl`, `job4/job4_mc_payload.json`

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| ossutil not found | Full path to exe, or restart Cursor |
| no java found | Install JDK 8+, set JAVA_HOME |
| ossutil AccessDenied | `sync_cloud_cli_config.py`; check RAM on bucket |
| odpscmd project error | Check `odps_config.ini` project_name / end_point |
| sha256: path error | Double-quote full OSS URI |
| MC rows but no OSS files | Match `dim_clip.active_run_id` to dispatch manifest |

## Security

- Never commit `.env`, `odps_config.ini`, `.ossutilconfig`
- `ls` before any `ossutil rm -r`
- No `reset_cloud_test_env.py --yes` on production

## Related rules

- Pipeline E2E: `.cursor/rules/dataworks-e2e-verify.mdc`
- Dispatch OSS (上云): `.cursor/rules/dataworks-dispatch-oss.mdc`
- DataWorks workflow: `dataworks/WORKFLOW.md`

## Full reference

Command details, tunnel, flags, eval cases: [reference.md](reference.md)
