# Cloud CLI Ops — Full Reference

Canonical skill: `.cursor/skills/cloud-cli-ops/SKILL.md`  
Last verified: 2026-06-11 (ossutil 2.3.0)

---

## 1. Credentials

Single source: repo root `.env`. Sync to CLI configs:

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline
py -3 scripts\sync_cloud_cli_config.py
```

Writes `D:\odpscmd_public\conf\odps_config.ini` and `%USERPROFILE%\.ossutilconfig`.  
`CLOUD_REGION=cn_shanghai` in `.env` → ossutil uses `cn-shanghai`.

---

## 2. Connectivity

```powershell
cd pipeline
py -3 scripts\e2e_precheck.py
```

D:\ossutil-2.3.0-windows-amd64\ossutil.exe ls oss://rosbag-labels-pipline-bucket/rosbags/ --limited-num 5

D:\odpscmd_public\bin\odpscmd.bat --config=D:\odpscmd_public\conf\odps_config.ini -e "select count(*) from aig_rosbag__dim_clip;"
```

Java: `java -version` must succeed. Temurin JDK 21 at `C:\Program Files\Eclipse Adoptium\jdk-21.0.5.11-hotspot`.

---

## 3. ossutil 2.x

Help: `ossutil --help` · `ossutil ls --help`

### List

```powershell
ossutil ls
ossutil ls oss://rosbag-labels-pipline-bucket/rosbags/
ossutil ls "oss://rosbag-labels-pipline-bucket/clips/sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b/runs/" --limited-num 50
ossutil ls "oss://rosbag-labels-pipline-bucket/clips/" -d
```

### Read

```powershell
ossutil cat oss://rosbag-labels-pipline-bucket/pipeline/dispatch/latest.json
ossutil cat "oss://.../job2/job2_sample_payload.json" --head 4096
```

### Copy / sync

```powershell
ossutil cp D:\local\output.bag oss://rosbag-labels-pipline-bucket/rosbags/2026-06-05_13-27-07/output.bag
ossutil cp "oss://.../job3/frame_labels.jsonl" .\frame_labels.jsonl
ossutil sync .\local_dir "oss://rosbag-labels-pipline-bucket/config/" --update
```

### Stat / delete

```powershell
ossutil stat oss://rosbag-labels-pipline-bucket/rosbags/2026-06-05_13-27-07/output.bag
ossutil rm oss://rosbag-labels-pipline-bucket/path/to/object
ossutil rm -r -f "oss://.../runs/<run_id>/"
```

### Flags

| Flag | Meaning |
|------|---------|
| `-f` | Force overwrite |
| `-r` | Recursive |
| `--limited-num N` | Cap list count |
| `--update` | Sync newer only |

### OSS layout

```
oss://rosbag-labels-pipline-bucket/
├── rosbags/{clip_dir_name}/*.bag
├── config/oms_label_taxonomy.yaml
├── pipeline/dispatch/latest.json
└── clips/{clip_id}/runs/{run_id}/
    ├── parsed/
    ├── job2/
    ├── job3/
    └── job4/
```

---

## 4. odpscmd

Config: `--config=D:\odpscmd_public\conf\odps_config.ini`

### Non-interactive SQL (preferred for agents)

```powershell
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "desc aig_rosbag__dim_clip;"

odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select clip_id, active_run_id, bag_oss_key from aig_rosbag__dim_clip limit 10;"

odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select count(*) from aig_rosbag__fact_frame where clip_id='sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b' and run_id='6a2f479e-64b4-443e-a73c-47a0cc23d81f';"

odpscmd --config=... -e "select step_id, status from aig_rosbag__pipeline_step where run_id='6a2f479e-64b4-443e-a73c-47a0cc23d81f' and ds='20260609' order by step_id;"
```

PowerShell: wrap SQL in double quotes; string literals in SQL use single quotes.

### Interactive

```powershell
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini
```

### Partitions / DDL

```powershell
odpscmd --config=... -e "show partitions aig_rosbag__fact_frame;"
py -3 scripts\apply_mc_ddl.py
odpscmd --config=... -e "truncate table aig_rosbag__dim_clip;"   # test only
```

### Tunnel

```powershell
odpscmd --config=... -e "tunnel download aig_rosbag__dim_clip dim_clip.csv;"
odpscmd --config=... -e "tunnel upload data.csv aig_rosbag__dim_clip;"
```

### MC table list

| Table | Purpose |
|-------|---------|
| `aig_rosbag__dim_clip` | clip dim, active_run_id |
| `aig_rosbag__pipeline_run` / `pipeline_step` | run state machine |
| `aig_rosbag__fact_message_timeline` | Job1 timeline |
| `aig_rosbag__fact_frame` / `fact_audio_chunk` / `fact_event` | Job1 facts |
| `aig_rosbag__clip_parse_summary` | Job1 summary |
| `aig_rosbag__fact_sample_policy` | Job2 sample |
| `aig_rosbag__fact_audio_segment` | Job2 ASR |
| `aig_rosbag__fact_image_label` | Job3 labels |
| `aig_rosbag__fact_embedding` | Job4 embeddings |

---

## 5. Project scripts

Run from **`pipeline/`** unless noted.

| Script | Purpose |
|--------|---------|
| `pipeline/scripts/sync_cloud_cli_config.py` | `.env` → CLI configs |
| `pipeline/scripts/e2e_precheck.py` | SDK connectivity |
| `pipeline/scripts/apply_mc_ddl.py` | MC DDL from `pipeline/sql/maxcompute/` |
| `pipeline/scripts/verify_pipeline_run.py` | OSS+MC full run check |
| `pipeline/scripts/reset_cloud_test_env.py` | Clear test clips/runs |
| `hmi/scripts/sync_hmi_local.py` | MC+OSS → local HMI (run from `hmi/`) |

### verify_pipeline_run.py

```powershell
cd pipeline
py -3 scripts\verify_pipeline_run.py --clip-id sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
```

### reset_cloud_test_env.py

```powershell
cd pipeline
py -3 scripts\reset_cloud_test_env.py --dry-run
py -3 scripts\reset_cloud_test_env.py --yes
```

---

## 6. Agent decision matrix (detailed)

| User intent | Tool | Anti-pattern |
|-------------|------|--------------|
| "有哪些 bag" | ossutil ls `rosbags/` | odpscmd |
| "dim_clip 多少条" | odpscmd count | writing Python |
| "dispatch 内容" | ossutil cat manifest | — |
| "pipeline 跑完整了吗" | `pipeline/scripts/verify_pipeline_run.py` | manual ls + 10 SQLs |
| "重跑 Job0" | Tell user: DataWorks | ossutil/odpscmd |
| AccessDenied | sync_cloud_cli_config.py | retry blindly |

---

## 7. Troubleshooting

| Symptom | Action |
|---------|--------|
| ossutil cmdlet not found | `D:\ossutil-2.3.0-windows-amd64\ossutil.exe` |
| no java found | JDK + PATH / JAVA_HOME |
| AccessDenied | sync config; RAM bucket/project scope |
| odpscmd connect fail | `project_name`, `end_point` in ini |
| sha256: parse error | Quote full URI |
| MC data, no OSS files | `active_run_id` vs dispatch manifest |

---

## 8. Security

- No secrets in Git, rules, or chat logs
- `ls` before `rm -r`
- Production: no truncate / reset without explicit approval

---

## 9. External links

- [ossutil 2.0](https://help.aliyun.com/zh/oss/developer-reference/ossutil-overview/)
- [odpscmd](https://help.aliyun.com/zh/maxcompute/user-guide/odpscmd)
- `dataworks/WORKFLOW.md`
- `.cursor/rules/dataworks-e2e-verify.mdc`

---

## 10. Skill eval cases (agent self-check)

### Case 1: List bags
Prompt: "看一下 rosbag-labels-pipline-bucket 里有哪些 bag"  
Expect: ossutil ls `rosbags/` with `--limited-num`, not odpscmd.

### Case 2: Count dim_clip
Prompt: "dim_clip 有多少条"  
Expect: odpscmd `-e` with `--config=...`, `select count(*)`.

### Case 3: Trigger Job0
Prompt: "重跑 Job0"  
Expect: DataWorks guidance; no CLI trigger.

### Case 4: AccessDenied
Expect: `sync_cloud_cli_config.py`, `.env`, RAM.

### Case 5: Verify pipeline
Prompt: "验证 clip pipeline 产物"  
Expect: `verify_pipeline_run.py --clip-id`, not manual ls+SQL only.

### Should trigger
OSS, odpscmd, MaxCompute, dispatch manifest, rosbag-labels-pipline-bucket, fact_frame, cloud cli, sync cli config.

### Should NOT trigger
DataWorks job run, write Python OSS client, AWS CLI, SQL window function tutorial, rosbag format theory.
