# MaxCompute / OSS CLI 操作手册（本机 Agent 用）

> **Canonical（Agent 优先读）：** `.cursor/skills/cloud-cli-ops/SKILL.md` + `reference.md`  
> 本文档与 `archive/ref/cloud-cli-ops/` 历史内容；修改 CLI 约定时请同步 `.cursor/skills/cloud-cli-ops/`。

> 适用环境：Windows · 仓库根 `rosbag_to_labels_pipline/` · 区域 `cn_shanghai`  
> **管线脚本**默认在 `pipeline/` 目录执行（`pipeline/scripts/`）。  
> 凭证来源：仓库根目录 `.env`（勿提交 Git）  
> 最后验证：2026-06-11（ossutil 2.3.0 实测通过）

## 1. 工具安装路径（本机）

| 工具 | 可执行文件 | 配置位置 |
|------|-----------|----------|
| **ossutil** 2.3.0 | `D:\ossutil-2.3.0-windows-amd64\ossutil.exe` | `%USERPROFILE%\.ossutilconfig` |
| **odpscmd** | `D:\odpscmd_public\bin\odpscmd.bat` | `D:\odpscmd_public\conf\odps_config.ini` |

PATH 已加入系统变量时，新开的 **PowerShell / CMD** 可直接调用 `ossutil`、`odpscmd`。  
**Cursor 内置终端**若报「找不到命令」，用上面完整路径，或重启 Cursor。

### odpscmd 前置：Java

`odpscmd.bat` 依赖 **Java 8+**。未装或未进 PATH 时会报 `no java found`。

```powershell
java -version   # 必须成功
```

安装 [Temurin JDK 17](https://adoptium.net/) 或 Oracle JDK，并把 `java.exe` 所在目录加入 PATH。

---

## 2. 项目云资源常量

从 `shared/config.yaml` + 仓库根 `.env` 读取，Agent 操作前应先确认：

| 项 | 值 |
|----|-----|
| MC Project | `rogbag_label_pipline` |
| MC Endpoint | `https://service.cn-shanghai.maxcompute.aliyun.com/api` |
| OSS Bucket | `rosbag-labels-pipline-bucket` |
| OSS Region | `cn-shanghai` |
| OSS Endpoint | `https://oss-cn-shanghai.aliyuncs.com` |
| 表前缀 | `aig_rosbag__` |
| Bag 扫描前缀 | `rosbags/` |
| Clip 产物前缀 | `clips/{clip_id}/runs/{run_id}/` |
| Dispatch manifest | `pipeline/dispatch/latest.json` |

**测试 clip（E2E 常用）**

- `clip_id`: `sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b`
- `clip_dir_name`: `2026-06-05_13-27-07`
- `bag_oss_key`: `rosbags/2026-06-05_13-27-07/output.bag`

---

## 3. 凭证同步（单一来源：`.env`）

CLI 配置文件含明文 AK/SK，**禁止提交 Git**。改 `.env` 后执行：

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline
py -3 scripts\sync_cloud_cli_config.py
```

会写入：

- `D:\odpscmd_public\conf\odps_config.ini`
- `%USERPROFILE%\.ossutilconfig`

注意：`.env` 里 `CLOUD_REGION=cn_shanghai` 会自动转为 ossutil 所需的 `cn-shanghai`。

---

## 4. 连通性自检

```powershell
# Python SDK（推荐首选）
py -3 scripts\e2e_precheck.py

# ossutil
D:\ossutil-2.3.0-windows-amd64\ossutil.exe ls oss://rosbag-labels-pipline-bucket/rosbags/ --limited-num 5

# odpscmd（需 Java）
D:\odpscmd_public\bin\odpscmd.bat --config=D:\odpscmd_public\conf\odps_config.ini -e "select count(*) from aig_rosbag__dim_clip;"
```

---

## 5. ossutil 2.x 常用命令

全局帮助：`ossutil --help` · 子命令：`ossutil ls --help`

### 5.1 列举

```powershell
# 所有 bucket
ossutil ls

# bag 区
ossutil ls oss://rosbag-labels-pipline-bucket/rosbags/

# 某 clip 的 run 产物（前缀含 sha256: 时用引号）
ossutil ls "oss://rosbag-labels-pipline-bucket/clips/sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b/runs/" --limited-num 50

# 只看「目录」层（前缀下直接子项，大桶较慢）
ossutil ls "oss://rosbag-labels-pipline-bucket/clips/" -d
```

### 5.2 读文本 / JSON

```powershell
# dispatch manifest（Job0 写、Job1~4 读）
ossutil cat oss://rosbag-labels-pipline-bucket/pipeline/dispatch/latest.json

# 查看 payload 前几 KB
ossutil cat "oss://rosbag-labels-pipline-bucket/clips/sha256:.../runs/<run_id>/job2/job2_sample_payload.json" --head 4096
```

### 5.3 上传 / 下载

```powershell
# 上传 bag（等价于 upload_clip_to_oss.py 的单文件路径）
ossutil cp D:\local\output.bag oss://rosbag-labels-pipline-bucket/rosbags/2026-06-05_13-27-07/output.bag

# 下载某 run 的 jsonl
ossutil cp "oss://rosbag-labels-pipline-bucket/clips/sha256:.../runs/<run_id>/job3/frame_labels.jsonl" .\frame_labels.jsonl

# 递归同步目录
ossutil sync .\local_dir "oss://rosbag-labels-pipline-bucket/config/" --update
```

常用 flags：

| Flag | 含义 |
|------|------|
| `-f` / `--force` | 覆盖已存在对象 |
| `-r` / `--recursive` | 递归（cp/rm/sync） |
| `--limited-num N` | 最多列 N 个对象 |
| `--update` | sync 时只传较新的 |

### 5.4 元信息与删除

```powershell
ossutil stat oss://rosbag-labels-pipline-bucket/rosbags/2026-06-05_13-27-07/output.bag

# 删单个对象（慎用）
ossutil rm oss://rosbag-labels-pipline-bucket/path/to/object

# 删前缀下全部（非常慎用，先 ls 确认）
ossutil rm -r -f "oss://rosbag-labels-pipline-bucket/clips/sha256:.../runs/<run_id>/"
```

### 5.5 本项目 OSS 路径速查

```
oss://rosbag-labels-pipline-bucket/
├── rosbags/{clip_dir_name}/*.bag          # Job0 扫描、Job1 读 bag
├── config/oms_label_taxonomy.yaml         # Job3 打标 taxonomy
├── pipeline/dispatch/latest.json          # dispatch manifest
└── clips/{clip_id}/runs/{run_id}/
    ├── parsed/                            # Job1
    ├── job2/                              # sample + asr
    ├── job3/                              # VL labels
    └── job4/                              # embeddings
```

**一次 run 应有产物（验数用）** — 也可用 `py -3 scripts\verify_pipeline_run.py`：

- `parsed/job1_mc_payload.json`
- `job2/sample_manifest.jsonl`、`job2/job2_*_payload.json`
- `job3/frame_labels.jsonl`、`job3/job3_mc_payload.json`
- `job4/embeddings.jsonl`、`job4/job4_mc_payload.json`

---

## 6. odpscmd 常用命令

配置文件：`--config=D:\odpscmd_public\conf\odps_config.ini`（或用 `-project` 覆盖 project）。

### 6.1 非交互执行 SQL（Agent 首选）

```powershell
# 查 dim_clip
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "desc aig_rosbag__dim_clip;"

odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select clip_id, active_run_id, bag_oss_key, pipeline_status from aig_rosbag__dim_clip limit 10;"

# 按 clip + run 查 fact 表行数
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini -e "select count(*) from aig_rosbag__fact_frame where clip_id='sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b' and run_id='6a2f479e-64b4-443e-a73c-47a0cc23d81f';"
```

PowerShell 引号：SQL 用双引号包裹；SQL 内字符串用单引号。

### 6.2 交互模式

```powershell
odpscmd --config=D:\odpscmd_public\conf\odps_config.ini
# 进入后输入 SQL，以分号结尾
```

### 6.3 表结构 / 分区

```powershell
odpscmd --config=... -e "desc aig_rosbag__fact_message_timeline;"
odpscmd --config=... -e "show partitions aig_rosbag__fact_frame;"
```

### 6.4 建表 / DDL

优先用项目脚本（与 `sql/maxcompute/aig_rosbag__ddl.sql` 一致）：

```powershell
py -3 scripts\apply_mc_ddl.py
```

手工 truncate（测试重置，慎用）：

```powershell
odpscmd --config=... -e "truncate table aig_rosbag__dim_clip;"
```

完整重置 OSS+MC 测试环境：

```powershell
py -3 scripts\reset_cloud_test_env.py --dry-run
py -3 scripts\reset_cloud_test_env.py --yes
```

### 6.5 Tunnel 导入导出

```powershell
# 下载表到本地 CSV（小表调试）
odpscmd --config=... -e "tunnel download aig_rosbag__dim_clip dim_clip.csv;"

# 上传
odpscmd --config=... -e "tunnel upload data.csv aig_rosbag__dim_clip;"
```

### 6.6 本项目 MC 表清单

| 表 | 用途 |
|----|------|
| `aig_rosbag__dim_clip` | clip 维表、active_run_id |
| `aig_rosbag__pipeline_run` / `pipeline_step` | run 状态机 |
| `aig_rosbag__fact_message_timeline` | Job1 时间轴 |
| `aig_rosbag__fact_frame` / `fact_audio_chunk` / `fact_event` | Job1 事实 |
| `aig_rosbag__clip_parse_summary` | Job1 摘要 |
| `aig_rosbag__fact_sample_policy` | Job2 抽样 |
| `aig_rosbag__fact_audio_segment` | Job2 ASR |
| `aig_rosbag__fact_image_label` | Job3 打标 |
| `aig_rosbag__fact_embedding` | Job4 向量 |

---

## 7. Agent 决策：用 CLI 还是 Python 脚本？

| 场景 | 推荐 |
|------|------|
| 快速看 OSS 文件列表 / 读 JSON | **ossutil** `ls` / `cat` |
| 上传单个 bag | `pipeline/scripts/upload_clip_to_oss.py` 或 **ossutil** `cp` |
| 跑 MC SQL / 查表 | **odpscmd** `-e` 或 **PyODPS**（`e2e_precheck.py`） |
| 建表 / 跑 DDL | `pipeline/scripts/apply_mc_ddl.py` |
| 验整条 pipeline run | `pipeline/scripts/verify_pipeline_run.py` |
| 重置测试环境 | `pipeline/scripts/reset_cloud_test_env.py` |
| 触发 Job0~4 MaxFrame 计算 | **DataWorks 控制台**（CLI 不在本文范围） |

Agent 执行顺序建议：

1. `py -3 scripts\sync_cloud_cli_config.py`（若刚改 `.env`）
2. `py -3 scripts\e2e_precheck.py` 或 ossutil ls
3. 具体操作（ossutil / odpscmd / 项目 scripts）
4. `py -3 scripts\verify_pipeline_run.py --clip-id ...` 验收

---

## 8. 故障排查

| 现象 | 处理 |
|------|------|
| `无法将 ossutil 识别为 cmdlet` | 用完整路径 `D:\ossutil-2.3.0-windows-amd64\ossutil.exe`，或重启 Cursor |
| `no java found` | 安装 JDK 8+ 并加入 PATH |
| ossutil AccessDenied | `py -3 scripts\sync_cloud_cli_config.py` 同步 AK；检查 RAM 权限 |
| odpscmd 连不上 project | 检查 `odps_config.ini` 的 `project_name` / `end_point` |
| 路径含 `sha256:` 报错 | PowerShell 中用双引号包住整个 `oss://...` URI |
| MC 有数据 OSS 无文件 | 查 `active_run_id` 是否对应正确 run；用 dispatch manifest 对齐 |

---

## 9. 安全

- `.env`、`odps_config.ini`、`.ossutilconfig` 均含明文密钥，**不得入 Git**
- 删 OSS 前缀前必须 `ls` 确认；生产数据禁止 `reset_cloud_test_env.py --yes`
- 优先 RAM 子账号 + 最小权限（指定 bucket + MC project）

---

## 10. 参考链接

- [ossutil 2.0 用户指南](https://help.aliyun.com/zh/oss/developer-reference/ossutil-overview/)
- [odpscmd 使用说明](https://help.aliyun.com/zh/maxcompute/user-guide/odpscmd)
- 项目编排：`dataworks/WORKFLOW.md`
- E2E 验收：`.cursor/rules/dataworks-e2e-verify.mdc`
