# DataWorks 参数手册

> **clip-omni v2（当前推荐）**：十节点 · 桶 `rosbag-labels-pipeline-bucket2` · dispatch 六步  
> **Legacy 十节点**：下文 §Job2 sample / Job3 label / Job4 embed 仍保留供旧工作流参考。

配置方式：工作流或节点「参数」面板 → **参数名**与**参数值**分两列填写。  
工作流级参数对所有子节点生效；节点参数可覆盖同名 key。  
代码读取顺序：`args`（节点参数）→ `SKYNET_ARGS` → 代码内 `_PROJECT_DEFAULTS`。

---

## clip-omni v2 速查（2026-07）

### 工作流级（v2 必填/推荐）

```properties
oss_bucket=rosbag-labels-pipeline-bucket2
pipeline_version=clip_omni_v2
dispatch_oss_key=pipeline/dispatch/latest.json
cloud_region=cn_shanghai
table_prefix=aig_rosbag__
scan_prefix=rosbags/
oss_prefix_template=clips/{clip_id}/
oss_runs_subdir=runs/{run_id}/
ds=${bizdate}
dpe_image=sq_maxframe
oss_ram_role_arn=acs:ram::<账号>:role/<角色名>
agreement_threshold=0.7
label_taxonomy_oss_key=config/taxonomy/latest.json
```

### v2 节点专属

| 节点 | 关键参数 | 输出 OSS |
|------|----------|----------|
| `job0_dispatch` | `pipeline_version=clip_omni_v2` | `pipeline/dispatch/latest.json` |
| `job1_parse` | `clip_id`, `bag_oss_key`, `run_id` | `parsed/` |
| `job1_align` | 同 Job1 `clip_id`/`run_id` | `aligned/timeline.json`, `sync_manifest.jsonl` |
| `job2_labeling` | `primary_model`, `label_taxonomy_oss_key` | `ai/labels_primary.json` |
| `job2_embedding` | `embed_model`, `embedding_dim=768` | `ai/embedding.json` |
| `job3_labeling_by_other_model` | `secondary_model`, `label_taxonomy_oss_key` | `ai/labels_secondary.json` |
| `job4_label_merge_and_compare` | `agreement_threshold=0.7` | `ai/labels_merged.json`, `ai/consensus_meta.json` |
| `job4_mc_write` | — | —（写 MC：`fact_clip_label`, `fact_clip_embedding`，待实现） |

### dispatch 去重步骤（v2）

`job1_parse` · `job1_align` · `job2_labeling` · `job2_embedding` · `job3_labeling_by_other_model` · `job4_label_merge_and_compare`（见 `pipeline_dispatch.REQUIRED_PIPELINE_STEPS`）

### 验收

```bash
py -3 pipeline/scripts/verify_pipeline_run.py --clip-id sha256:... --run-id <uuid>   # v2 默认
py -3 pipeline/scripts/verify_pipeline_run.py --legacy ...                          # 旧十节点
```

详编排：`WORKFLOW.md` · `WORKFLOW_COMPLETE.md` · `workflow-params.example`

---

## 测试资产（E2E 联调）

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
clip_dir_name=2026-06-05_13-27-07
bag_oss_key=rosbags/2026-06-05_13-27-07/output.bag
run_id=<Job1 解析日志 NEXT_NODE_PARAM run_id= 后的 UUID>
```

整条链路 **Job1~Job2 必须使用同一个 `run_id`**（legacy 十节点则为 Job1~Job4）。

---

## 一、工作流级参数（Legacy 十节点 + 全局共用）

> v2 环境请将 `oss_bucket` 改为 `rosbag-labels-pipeline-bucket2`，并增加 `pipeline_version=clip_omni_v2`。  
> 以下参数 legacy / v2 Job0~Job1 共用。

以下参数建议在工作流根节点配置；单节点可覆盖。

### OSS / 区域

```properties
oss_bucket=rosbag-labels-pipeline-bucket2
```

| 项 | 说明 |
|----|------|
| **作用** | OSS 桶名；Job0 扫描 bag、Job1+ DPE 挂载读写的目标桶 |
| **必填** | 是（Job0/Job1+ 代码 `require_arg`） |
| **可填值** | 与 `shared/config.yaml` → `cloud.oss.bucket`、`.env` → `OSS_BUCKET` 一致；**v2**：`rosbag-labels-pipeline-bucket2`；legacy：`rosbag-labels-pipline-bucket` |
| **使用节点** | 全部 |

---

```properties
cloud_region=cn_shanghai
```

| 项 | 说明 |
|----|------|
| **作用** | 区域简写，决定 OSS **内网** endpoint（`oss-cn-shanghai-internal`） |
| **必填** | 否（默认 `cn_shanghai`） |
| **可填值** | `cn_shanghai` 或 `cn-shanghai`（代码会归一化） |
| **注意** | 须与 MaxCompute 项目、OSS 桶同区域（华东2 上海） |
| **使用节点** | 全部 |

---

```properties
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
```

| 项 | 说明 |
|----|------|
| **作用** | DPE `@with_fs_mount` 挂载 OSS 时使用的 RAM **角色 ARN**（STS 临时凭证） |
| **必填** | 强烈推荐（留空则回退 `o.account` AK/SK，DataWorks Driver AK 通常无法直连 OSS） |
| **可填值** | `acs:ram::<阿里云账号ID>:role/<角色名>`；**必须是 role**，不能写 `user/xxx` |
| **RAM 要求** | 信任策略 Principal 含 `odps.aliyuncs.com`；角色有桶读写权限；MC 项目已登记该角色 |
| **使用节点** | Job0~Job4 全部 DPE 节点 |

---

```properties
oss_mount_prefix=
```

| 项 | 说明 |
|----|------|
| **作用** | 挂载 OSS 时的子路径前缀；空表示挂载**整桶根目录** |
| **必填** | 否（默认空） |
| **可填值** | 留空（推荐）；或 `clips/`（仅当所有读写都在 clips 下时） |
| **注意** | 若填 `clips/`，Job1 **读不到** `rosbags/` 下的 bag |
| **使用节点** | Job0~Job4 |

---

```properties
oss_prefix_template=clips/{clip_id}/
```

| 项 | 说明 |
|----|------|
| **作用** | 解析/Job2~4 产物在 OSS 上的 clip 级目录模板 |
| **必填** | 否（默认 `clips/{clip_id}/`） |
| **可填值** | 含 `{clip_id}` 占位符的路径模板，如 `clips/{clip_id}/` |
| **产物示例** | `clips/sha256:abc.../runs/<run_id>/parsed/` |
| **使用节点** | Job1 解析、Job1~4 写 MC、Job2~4 算子 |

---

```properties
oss_runs_subdir=runs/{run_id}/
```

| 项 | 说明 |
|----|------|
| **作用** | Job1 解析产物 run 子目录模板（相对 `oss_prefix_template`） |
| **必填** | 否（默认 `runs/{run_id}/`） |
| **可填值** | 含 `{run_id}` 的路径片段 |
| **使用节点** | Job1 解析 |

---

### MaxCompute 表

```properties
table_prefix=aig_rosbag__
```

| 项 | 说明 |
|----|------|
| **作用** | MC 表名前缀，与 DDL `pipeline/sql/maxcompute/aig_rosbag__ddl.sql` 一致 |
| **必填** | 否（默认 `aig_rosbag__`） |
| **可填值** | 固定 `aig_rosbag__`，除非重建整套表 |
| **使用节点** | Job0、Job1~4 写 MC |

---

```properties
ds=${bizdate}
```

| 项 | 说明 |
|----|------|
| **作用** | 分区表（`fact_*`、`pipeline_*`）的分区字段，格式 `yyyyMMdd` |
| **必填** | 写 MC 节点需要 |
| **可填值** | 定时调度：`${bizdate}`；手动测试：`20260608` |
| **注意** | 手动跑时 `${bizdate}` 可能未展开；写 MC 节点代码会回退环境变量 `SKYNET_BIZDATE` |
| **使用节点** | Job1~4 写 MC |

---

### Job0 扫描

```properties
scan_prefix=rosbags/
```

| 项 | 说明 |
|----|------|
| **作用** | Job0 在 OSS 挂载目录下扫描 bag 的前缀 |
| **必填** | 否（默认 `rosbags/`） |
| **可填值** | `rosbags/`（与 `shared/config.yaml` → `cloud.oss.data_prefix` 一致） |
| **使用节点** | Job0 |

---

```properties
clip_id_format=sha256:{hex}
```

| 项 | 说明 |
|----|------|
| **作用** | 由 bag 内容 hash 生成 `clip_id` 的格式字符串 |
| **必填** | 否（默认 `sha256:{hex}`） |
| **可填值** | 含 `{hex}` 占位符；与本地 `clip_id.py` 一致 |
| **使用节点** | Job0 |

---

### DPE 运行时

```properties
dpe_image=sq_maxframe
```

| 项 | 说明 |
|----|------|
| **作用** | MaxCompute 镜像管理登记的 **DPE Worker 镜像名**（非 ACR 完整 URL） |
| **必填** | 强烈推荐 Job1+（含 rosbags/pyyaml/ossfs2） |
| **可填值** | 当前环境：`sq_maxframe` |
| **代码效果** | 设置 `mf_options.sql.settings["odps.session.image"]` |
| **使用节点** | Job0~Job4 全部 DPE 节点 |

---

```properties
dpe_mount_path=/mnt/oss
```

| 项 | 说明 |
|----|------|
| **作用** | OSS 挂载到 DPE 容器内的本地路径；代码用 `Path(mount_path) / <oss_key>` 读文件 |
| **必填** | 否（默认 `/mnt/oss`） |
| **可填值** | 任意合法绝对路径 |
| **使用节点** | Job0~Job4 |

---

```properties
dpe_cpu=4
dpe_memory_gb=16
```

| 项 | 说明 |
|----|------|
| **作用** | DPE 单 Worker 的 CPU 核数 / 内存 GB（`@with_running_options`） |
| **必填** | 否 |
| **推荐值** | Job0：2 / 8；Job1 解析：4 / 16；Job2~4 算子：2 / 8；写 MC：1 / 4 |
| **可填值** | 正整数 |
| **注意** | 工作流只配一组时，写 MC 节点也会继承；可按节点覆盖为更小值 |

---

### MaxFrame AI Function（Job2 ASR / Job3 打标 / Job4 向量化）

模型名非空时生效；工作流级配一次，Job2/3/4 节点可覆盖。

```properties
ai_modelset_project=bigdata_public_modelset
ai_cu_quota_name=mf_cpu_quota
ai_gu_quota_name=mf_gu_quota
ai_parallel_partitions=4
ai_memory=8G
total_rpm_limit=12000
request_timeout=300
```

```properties
total_rpm_limit=12000
```

| 项 | 说明 |
|----|------|
| **作用** | MaxFrame AI `running_options.total_rpm_limit`（全任务 RPM 上限） |
| **必填** | 否（默认 `12000`） |
| **可填值** | 正整数；`0` 表示不传该选项（不限流） |
| **使用节点** | `job2_asr` · `job3_label` · `job4_embed` |
| **注意** | 旧名 `ai_rpm_limit` 已废弃，请用 `total_rpm_limit` |

---

```properties
request_timeout=300
```

| 项 | 说明 |
|----|------|
| **作用** | MaxFrame AI `running_options.request_timeout`（单次请求超时，秒） |
| **必填** | 否（默认 `300`） |
| **可填值** | 正整数；`0` 表示不传该选项 |
| **使用节点** | `job2_asr` · `job3_label` · `job4_embed` |
| **调优** | Job3 VL 打标慢时可调到 `600` 或更高 |
| **注意** | 旧名 `timeout` 已废弃，请用 `request_timeout` |

---

## Job0 dispatch · OSS 传参（`job0_dispatch_node.py`）

PyODPS 无法把运行时 `clip_id` 传给下游节点参数；**本仓库采用 OSS manifest**（全版本 DW 可用）。

```
job0_dispatch → 写 oss://rosbag-labels-pipeline-bucket2/pipeline/dispatch/latest.json
job1_parse    → resolve_pipeline_context() 读 OSS
```

| 项 | 说明 |
|----|------|
| **job0 必做** | 重贴 `bundled/job0_dispatch_node.py`；去掉 `write_dispatch_oss=false` |
| **job1~4** | 只需 `oss_bucket`；**不必**配节点上下文 clip_id |
| **验收** | job0 日志含 `Job0 dispatch OSS manifest:`；job1 日志含 `loaded dispatch from OSS` |

完整说明：`pipeline/dataworks/DISPATCH_PARAMS.md`

---

## 二、Job0 发现（`job0_discover_node.py`）

### 节点专属参数

```properties
max_scan=200
```

| 项 | 说明 |
|----|------|
| **作用** | 单轮最多扫描并 hash 的 `.bag` 数量，防止大桶超时 |
| **必填** | 否（默认 `200`） |
| **可填值** | 正整数 |

---

```properties
dry_run=false
```

| 项 | 说明 |
|----|------|
| **作用** | 为 `true` 时只打印 `DISCOVERED_JSON`，**不写** MC `dim_clip` |
| **必填** | 否（默认 `false`） |
| **可填值** | `true` / `false` / `1` / `yes` |

---

```properties
bag_suffix=.bag
```

| 项 | 说明 |
|----|------|
| **作用** | 扫描时匹配的文件后缀 |
| **必填** | 否（默认 `.bag`） |
| **可填值** | 如 `.bag` |

---

### Job0 最小配置示例

```properties
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
table_prefix=aig_rosbag__
scan_prefix=rosbags/
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
dpe_image=sq_maxframe
dpe_cpu=2
dpe_memory_gb=8
dpe_mount_path=/mnt/oss
oss_mount_prefix=
max_scan=200
dry_run=false
```

---

## 三、Job1 解析（`job1_parse_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
```

| 项 | 说明 |
|----|------|
| **作用** | 待解析 clip 的内容 hash ID，须与 bag 实际 hash 一致 |
| **必填** | 是 |
| **来源** | Job0 日志 `DISCOVERED clip_id=` 或 `pipeline/scripts/upload_clip_to_oss.py` 输出 |

---

```properties
clip_dir_name=2026-06-05_13-27-07
```

| 项 | 说明 |
|----|------|
| **作用** | 采集目录名，写入 MC `dim_clip.clip_dir_name` |
| **必填** | 是 |
| **可填值** | 一般等于 OSS 路径 `rosbags/<目录名>/output.bag` 中的 `<目录名>` |

---

```properties
bag_oss_key=rosbags/2026-06-05_13-27-07/output.bag
```

| 项 | 说明 |
|----|------|
| **作用** | bag 在 OSS 的 object key（相对桶根） |
| **必填** | 条件必填：节点未填时从 MC `dim_clip.bag_oss_key` 查询 |
| **可填值** | 如 `rosbags/2026-06-05_13-27-07/output.bag` |

---

```properties
run_id=
```

| 项 | 说明 |
|----|------|
| **作用** | 本次 pipeline 版本 UUID；决定 OSS 产物目录 `runs/<run_id>/` |
| **必填** | 否（留空则节点内自动生成 UUID） |
| **可填值** | UUID 字符串，或留空 |
| **注意** | 生成后须抄给 Job1 写 MC 及 Job2 v2 / legacy Job2~4；日志有 `NEXT_NODE_PARAM run_id=` |

---

### 节点可选

```properties
pipeline_config_json=
```

| 项 | 说明 |
|----|------|
| **作用** | 覆盖 Job1 解析配置（topics、output 路径、audio 格式等） |
| **必填** | 否 |
| **可填值** | 完整 JSON 对象字符串；留空用节点内置 `DEFAULT_PIPELINE_CONFIG` |

---

### Job1 解析完整示例

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
clip_dir_name=2026-06-05_13-27-07
bag_oss_key=rosbags/2026-06-05_13-27-07/output.bag
run_id=
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_mount_prefix=
oss_prefix_template=clips/{clip_id}/
oss_runs_subdir=runs/{run_id}/
dpe_image=sq_maxframe
dpe_cpu=4
dpe_memory_gb=16
dpe_mount_path=/mnt/oss
```

**成功日志**：`Job1 parse done` · **OSS**：`clips/.../runs/<run_id>/parsed/job1_mc_payload.json`

---

## 四、Job1 写 MC（`job1_mc_write_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
```

| 参数 | 说明 |
|------|------|
| `clip_id` | 与 Job1 解析相同 |
| `run_id` | **必须与 Job1 解析完全一致**（日志 `NEXT_NODE_PARAM run_id=`） |

---

### 工作流级（写 MC 共用）

```properties
ds=${bizdate}
table_prefix=aig_rosbag__
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_prefix_template=clips/{clip_id}/
oss_mount_prefix=
dpe_image=sq_maxframe
dpe_cpu=1
dpe_memory_gb=4
dpe_mount_path=/mnt/oss
```

| 项 | 说明 |
|----|------|
| **作用** | DPE 读 `job1_mc_payload.json`；Driver 写 `dim_clip`、`fact_frame`、`fact_audio_chunk` 等 |
| **禁止** | 节点内 **不要** `import oss2` |

**成功日志**：`MC write done` · **MC**：`dim_clip.active_run_id` 更新为 `run_id`

---

## 四-b、Job1 对齐（`job1_align_node.py`）— clip-omni v2

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=<与 Job1 相同>
```

| 参数 | 说明 |
|------|------|
| `clip_id` / `run_id` | 与 Job1 解析一致；定时任务留空走 dispatch |

### 输入 / 输出

| 方向 | OSS 路径 |
|------|----------|
| 读 | `clips/{clip_id}/runs/{run_id}/parsed/` |
| 写 | `aligned/timeline.json` |
| 写 | `aligned/sync_manifest.jsonl` |

**成功验收**：`verify_pipeline_run.py`（v2 默认）检查 `aligned/timeline.json` 存在。

当前节点为 **Driver stub**（`write_aligned_artifacts()`）；上云需 bundle 为完整 DPE 节点。

---

## 四-c、Job2 主模型打标（`job2_labeling_node.py`）— clip-omni v2

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=<与 Job1 相同>
label_taxonomy_oss_key=config/taxonomy/latest.json
primary_model=
primary_model_version=
```

| 参数 | 说明 |
|------|------|
| `label_taxonomy_oss_key` | 发布版 taxonomy；与 HMI publish 写入 OSS 的路径一致 |
| `primary_model` | MaxFrame VL/Omni 模型 Catalog 名；留空 = stub |
| `primary_model_version` | 模型版本；可选 |

### 输入 / 输出

| 方向 | OSS 路径 |
|------|----------|
| 读 | `aligned/timeline.json`, `aligned/sync_manifest.jsonl` |
| 读 | taxonomy / `config/taxonomy/latest.json` |
| 写 | `ai/labels_primary.json` |

**禁止**：不写 `reviews/`。

---

## 四-d、Job2 向量（`job2_embedding_node.py`）— clip-omni v2

### 节点参数

```properties
clip_id=<与 Job1 相同>
run_id=<与 Job1 相同>
embed_model=
embed_model_version=
embedding_dim=768
```

| 参数 | 说明 |
|------|------|
| `embed_model` | clip 向量模型；留空 = stub（零向量） |
| `embedding_dim` | 向量维度 |

### 输入 / 输出

| 方向 | OSS 路径 |
|------|----------|
| 读 | `aligned/`（+ 可选 `parsed/`） |
| 写 | `ai/embedding.json` |

可与 `job2_labeling` · `job3_labeling_by_other_model` **并行**（均依赖 align）。

---

## 四-e、Job3 副模型打标（`job3_labeling_by_other_model_node.py`）— clip-omni v2

### 节点参数

```properties
clip_id=<与 Job1 相同>
run_id=<与 Job1 相同>
label_taxonomy_oss_key=config/taxonomy/latest.json
secondary_model=
secondary_model_version=
```

| 参数 | 说明 |
|------|------|
| `secondary_model` | 与 primary 不同的模型；留空 = stub |
| 其余 | 同 job2_labeling |

### 输入 / 输出

| 方向 | OSS 路径 |
|------|----------|
| 读 | 同 job2_labeling |
| 写 | `ai/labels_secondary.json` |

---

## 四-f、Job4 合并（`job4_label_merge_and_compare_node.py`）— clip-omni v2

### 节点参数

```properties
clip_id=<与 Job1 相同>
run_id=<与 Job1 相同>
agreement_threshold=0.7
```

| 参数 | 说明 |
|------|------|
| `agreement_threshold` | clip 一致率阈值；默认 `0.7`（与 `shared/config.yaml` 一致） |

### 输入 / 输出

| 方向 | OSS 路径 |
|------|----------|
| 读 | `ai/labels_primary.json`, `ai/labels_secondary.json` |
| 写 | `ai/labels_merged.json`, `ai/consensus_meta.json`, `ai/labels.json`（别名） |

**合并规则**：一致率 ≥ 阈值 → 合并（冲突取 primary）；< 阈值 → 争议字段留空，`gate_passed=false`。

---

## 四-g、Job4 写 MC（v2 `job4_mc_write`，待实现）

| 项 | 说明 |
|----|------|
| **读 OSS** | `ai/labels_merged.json`, `ai/embedding.json`, `ai/consensus_meta.json` |
| **写 MC** | `fact_clip_label`（含 `multi_ai_meta_json`）, `fact_clip_embedding` |
| **注意** | 现有 `job4_mc_write_node.py` 为 legacy 帧级向量；v2 需单独实现 |

---

## 四-h、Job2 clip omni（`job2_clip_omni_node.py`）— **已废弃**

> ⚠️ 单体 omni 节点已 deprecated，请改用 §四-c ~ §四-f 四节点组合。

---

## 五、Job2 抽样（`job2_sample_node.py`）— Legacy

> ⚠️ **Legacy 十节点**，v2 工作流 **不使用** 本节点。

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
```

---

### 节点可选

```properties
sample_policy=uniform
```

| 项 | 说明 |
|----|------|
| **作用** | 帧抽样策略名 |
| **必填** | 否（默认 `uniform`） |
| **可填值** | `uniform` · `event_dense` · `hybrid_default` |

---

```properties
job2_config_json=
```

| 项 | 说明 |
|----|------|
| **作用** | 整段覆盖 `cloud.job2` 配置（抽样策略列表等） |
| **必填** | 否 |

---

### Job2 抽样完整示例

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
sample_policy=uniform
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_mount_prefix=
oss_prefix_template=clips/{clip_id}/
dpe_image=sq_maxframe
dpe_cpu=4
dpe_memory_gb=16
dpe_mount_path=/mnt/oss
```

**成功日志**：`Job2 sample done` · **OSS**：`job2/sample_manifest.jsonl`、`job2/job2_sample_payload.json`

---

## 六、Job2 ASR（`job2_asr_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
```

可与 Job2 抽样 **并行** 启动（均依赖 Job1）。

---

### 节点可选

```properties
asr_segment_sec=30
```

| 项 | 说明 |
|----|------|
| **作用** | 音频分段时长（秒） |
| **必填** | 否（默认 `30`） |

---

```properties
asr_model=
asr_model_version=
asr_language=zh-CN
```

| 项 | 说明 |
|----|------|
| **作用** | MaxCompute AI ASR 模型 |
| **E2E stub** | `asr_model` 留空 → 只切 wav + 写分段元数据，`asr_text` 为空 |
| **真实 ASR** | 使用 MaxFrame AI Function（`asr_model` 非空） |

---

```properties
total_rpm_limit=12000
request_timeout=300
```

| 项 | 说明 |
|----|------|
| **作用** | MaxFrame AI `running_options` 限流与超时 |
| **必填** | 否（默认 12000 / 300；`0`=不传） |
| **详见** | 上文「MaxFrame AI Function」 |

---

```properties
asr_sql_template=
```

| 项 | 说明 |
|----|------|
| **作用** | Driver 侧调用 MC AI 的 SQL 模板 |
| **占位符** | `{model}` · `{model_version}` · `{language}` · `{audio_url}` |
| **必填** | `asr_model` 非空时 **必填** |
| **示例** | 按你在 MC 登记的 ASR Function 改写，例如：<br>`SELECT asr('{audio_url}', '{language}') AS text, 1.0 AS confidence` |

> `audio_url` 为 OSS 内网 URL（`oss://oss-cn-shanghai-internal.aliyuncs.com/rosbag-labels-pipline-bucket/clips/.../asr_segments/0000.wav`），须确保 MC AI 可访问该桶。

---

### Job2 ASR 完整示例（真实 ASR）

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
asr_segment_sec=30
asr_model=<你的 MC AI ASR 模型名>
asr_model_version=v1
asr_language=zh-CN
asr_sql_template=SELECT your_asr_udf('{audio_url}', '{language}') AS text, 1.0 AS confidence
total_rpm_limit=12000
request_timeout=300
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
dpe_image=sq_maxframe
dpe_cpu=4
dpe_memory_gb=16
dpe_mount_path=/mnt/oss
```

**成功日志**：`Job2 ASR done` · **OSS**：`job2/asr_segments/*.wav`、`job2/job2_asr_payload.json`

---

## 七、Job2 写 MC（`job2_mc_write_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
ds=${bizdate}
```

| 项 | 说明 |
|----|------|
| **作用** | 读 `job2_sample_payload.json` + `job2_asr_payload.json`，合并写 `job2_mc_payload.json`，再写 MC |
| **MC 表** | `aig_rosbag__fact_sample_policy`、`aig_rosbag__fact_audio_segment` |

**成功日志**：`Job2 MC write done`

---

## 八、Job3 打标（`job3_label_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
```

---

### 节点可选

```properties
label_model=
label_model_version=
```

| 项 | 说明 |
|----|------|
| **作用** | MaxCompute AI 视觉打标模型 |
| **E2E stub** | 留空 → OMS 结构 `labels_json`，`values: {}` |
| **可填值** | MC AI 模型名（待接入） |

---

```properties
label_batch_size=32
```

| 项 | 说明 |
|----|------|
| **作用** | 打标批大小 |
| **必填** | 否（默认 `32`） |
| **可填值** | 正整数 |

---

```properties
total_rpm_limit=12000
request_timeout=300
```

| 项 | 说明 |
|----|------|
| **作用** | VL generate 的 MaxFrame AI `running_options` |
| **必填** | 否（默认 12000 / 300） |
| **详见** | 上文「MaxFrame AI Function」 |

---

```properties
label_taxonomy_oss_key=config/oms_label_taxonomy.yaml
```

| 项 | 说明 |
|----|------|
| **作用** | OMS 标签 taxonomy 在 OSS 上的 object key（相对桶根） |
| **必填** | 否（默认 `config/oms_label_taxonomy.yaml`） |
| **前置** | 须先将本地 `config/oms_label_taxonomy.yaml` 上传到桶根同路径 |

---

```properties
label_taxonomy_json=
```

| 项 | 说明 |
|----|------|
| **作用** | 直接传入 taxonomy JSON，**优先于** OSS 文件 |
| **必填** | 否 |
| **可填值** | 完整 taxonomy JSON 字符串 |

---

```properties
exclude_labels=L1.1.timestamp
```

| 项 | 说明 |
|----|------|
| **作用** | 打标时排除的标签 ID 列表 |
| **必填** | 否 |
| **可填值** | 逗号分隔，如 `L1.1.timestamp,L2.3.foo` |

---

```properties
job3_config_json=
```

| 项 | 说明 |
|----|------|
| **作用** | 覆盖 `cloud.job3_label` 整段配置 |
| **必填** | 否 |

---

### Job3 完整示例

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
label_model=
label_model_version=
label_batch_size=32
label_taxonomy_oss_key=config/oms_label_taxonomy.yaml
total_rpm_limit=12000
request_timeout=300
exclude_labels=
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_mount_prefix=
oss_prefix_template=clips/{clip_id}/
dpe_image=sq_maxframe
dpe_cpu=4
dpe_memory_gb=16
dpe_mount_path=/mnt/oss
```

**成功日志**：`Job3 label done` · **OSS**：`job3/frame_labels.jsonl`、`job3/job3_mc_payload.json`

---

## 九、Job3 写 MC（`job3_mc_write_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
ds=${bizdate}
```

| 项 | 说明 |
|----|------|
| **作用** | 读 `job3_mc_payload.json`，写 `fact_image_label`、`pipeline_step`（`job3_label`） |

**成功日志**：`Job3 MC write done`

---

## 十、Job4 向量化（`job4_embed_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
```

---

### 节点可选

```properties
storage_mode=separate
```

| 项 | 说明 |
|----|------|
| **作用** | 向量存储模式 |
| **必填** | 否（默认 `separate`） |
| **可填值** | `separate`（帧/文本分模型）· `unified`（同一向量空间）· `both`（两套都写） |

---

```properties
embed_batch_size=64
```

| 项 | 说明 |
|----|------|
| **作用** | 向量化批大小 |
| **必填** | 否（默认 `64`） |

---

```properties
total_rpm_limit=12000
request_timeout=300
```

| 项 | 说明 |
|----|------|
| **作用** | embedding AI Function 的 MaxFrame AI `running_options` |
| **必填** | 否（默认 12000 / 300） |
| **详见** | 上文「MaxFrame AI Function」 |

---

```properties
image_embed_model=
text_embed_model=
unified_embed_model=
```

| 项 | 说明 |
|----|------|
| **作用** | 图像 / 文本 / 统一空间的 embedding 模型名 |
| **E2E stub** | 留空 → 零向量，`model_version=none` |
| **可填值** | MC AI 模型名（待接入） |

---

```properties
image_embed_model_version=
text_embed_model_version=
unified_embed_model_version=
```

| 项 | 说明 |
|----|------|
| **作用** | 对应模型版本号 |
| **必填** | 否 |

---

```properties
job4_config_json=
```

| 项 | 说明 |
|----|------|
| **作用** | 覆盖 `cloud.job4_embed` 整段配置 |
| **必填** | 否 |

---

### Job4 完整示例

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
storage_mode=separate
embed_batch_size=64
total_rpm_limit=12000
request_timeout=300
image_embed_model=
text_embed_model=
unified_embed_model=
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_mount_prefix=
oss_prefix_template=clips/{clip_id}/
dpe_image=sq_maxframe
dpe_cpu=4
dpe_memory_gb=16
dpe_mount_path=/mnt/oss
```

**成功日志**：`Job4 embed done` · `PIPELINE_DONE clip_id=... run_id=...`

---

## 十一、Job4 写 MC（`job4_mc_write_node.py`）

### 节点必填

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=f2b396bf-d46c-4435-9fce-af4cfb07e653
ds=${bizdate}
```

| 项 | 说明 |
|----|------|
| **作用** | 读 `job4_mc_payload.json`，写 `fact_embedding`、`pipeline_step`（`job4_embed`） |

**成功日志**：`Job4 MC write done`

---

## 十二、参数传递关系（串行 E2E）

```
Job0  → dim_clip（clip_id, bag_oss_key）
Job0 dispatch → 输出 action/clip_id/run_id/... → 下游节点输入参数
Job1 解析 → OSS job1_mc_payload.json
Job1 写 MC → clip_id + run_id + ds
...
```

**定时任务（v2 推荐）**：工作流级 `clip_id` / `run_id` **留空** → `job0_dispatch` 写 OSS manifest → 下游 `resolve_pipeline_context()` 自动读。**无需**节点上下文绑定。

**单 clip 手动测试**：工作流级或节点参数直接填 `clip_id`/`run_id`，覆盖 dispatch。

---

## 十三、工作流一键模板（单 clip E2E）

```properties
oss_bucket=rosbag-labels-pipline-bucket
cloud_region=cn_shanghai
table_prefix=aig_rosbag__
scan_prefix=rosbags/
clip_id_format=sha256:{hex}
oss_ram_role_arn=acs:ram::1413495213520409:role/maxframe-rosbag-oss
oss_mount_prefix=
oss_prefix_template=clips/{clip_id}/
oss_runs_subdir=runs/{run_id}/
dpe_image=sq_maxframe
dpe_mount_path=/mnt/oss
dpe_cpu=4
dpe_memory_gb=16
ds=${bizdate}
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
clip_dir_name=2026-06-05_13-27-07
bag_oss_key=rosbags/2026-06-05_13-27-07/output.bag
run_id=
sample_policy=uniform
label_taxonomy_oss_key=config/oms_label_taxonomy.yaml
storage_mode=separate
total_rpm_limit=12000
request_timeout=300
```

各节点仅需覆盖与自己相关的参数；Job1 解析后把 `run_id` 填回工作流或后续节点。

---

## 相关文档

- 编排顺序：`pipeline/dataworks/WORKFLOW.md`
- E2E 验收：`/.cursor/rules/dataworks-e2e-verify.mdc`
- 运维排错：`/.cursor/rules/dataworks-ops.mdc`
- 参数模板（简版）：`pipeline/dataworks/workflow-params.example`
