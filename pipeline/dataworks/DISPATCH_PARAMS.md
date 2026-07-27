# Job0 Dispatch → 下游参数传递（OSS 方案）

适用于 **无法使用赋值节点**（需 DataWorks 标准版+）的环境。

## 拓扑（clip-omni v2，十节点）

```
job0_discover → job0_dispatch
  → job1_parse → job1_mc_write → job1_align
  → job2_labeling ──┐
  → job2_embedding ─┼→ job4_label_merge_and_compare → job4_mc_write
  → job3_labeling_by_other_model ─┘
```

1. **job0_dispatch**：挑选 clip，写 OSS `pipeline/dispatch/latest.json`（含 `pipeline_version=clip_omni_v2`）
2. **job1_parse** 及下游：`resolve_pipeline_context()` 读 OSS manifest

**不需要**配置 job0_dispatch 的「本节点输出参数」，**不需要**下游「本节点输入参数」绑定 clip_id。

## job0_dispatch 配置

- 代码：`pipeline/dataworks/bundled/job0_dispatch_node.py`
- 工作流参数：
  - `oss_bucket=rosbag-labels-pipeline-bucket2`
  - `pipeline_version=clip_omni_v2`
- **不要**设 `write_dispatch_oss=false`（已废弃；dispatch 始终写 OSS，除非 `dry_run=true`）
- 成功日志：

```
Job0 dispatch OSS manifest: oss://rosbag-labels-pipeline-bucket2/pipeline/dispatch/latest.json
DISPATCH clip_id=sha256:... run_id=...
```

### Dispatch manifest 示例

```json
{
  "action": "run",
  "reason": "new_run",
  "clip_id": "sha256:...",
  "run_id": "00000000-0001-4000-8000-000000000001",
  "clip_dir_name": "demo_morning_city",
  "bag_oss_key": "rosbags/demo_morning_city/output.bag",
  "pipeline_version": "clip_omni_v2",
  "taxonomy_version_id": "...",
  "taxonomy_oss_key": "config/taxonomy/latest.json",
  "dispatched_at": "2026-07-22T03:00:00Z"
}
```

## 下游节点配置

只需保证工作流里有 **`oss_bucket`**（与 job0 相同），代码会自动读 manifest。

| 项 | 要不要配 |
|----|----------|
| 本节点输入参数 `clip_id` ← job0_dispatch | **不要**（PyODPS 解析不了） |
| 节点参数 `clip_id=...` | 仅 **单 clip 手工调试** 时需要 |
| `oss_bucket` | **要**（工作流级或节点级） |
| `pipeline_version` | **推荐**工作流级 `clip_omni_v2` |

下游 `main()` 开头日志应类似：

```
resolve_pipeline_context: no clip_id in args; reading OSS oss://rosbag-labels-pipeline-bucket2/pipeline/dispatch/latest.json
resolve_pipeline_context: loaded dispatch from OSS (action=run)
```

## dispatch 去重（v2）

`pick_dispatch_target()` 检查 `pipeline_step` 中以下 **六步**是否均为 `completed`：

- `job1_parse`
- `job1_align`
- `job2_labeling`
- `job2_embedding`
- `job3_labeling_by_other_model`
- `job4_label_merge_and_compare`

全部完成 → 跳过该 clip 的 `active_run_id`，或为无 run 的 clip 分配新 `run_id`。

Legacy 五步见 `pipeline_dispatch.py` → `LEGACY_PIPELINE_STEPS`（`--legacy` 工作流）。

## 运行顺序

必须 **同一工作流实例内** 先成功跑完 `job0_dispatch`，再跑 `job1_parse`：

1. 整链从 `job0_dispatch` 起运行，或
2. 补数据时按依赖顺序跑

若单独跑 job1 而 OSS 上还没有 manifest，会报：

```
Dispatch OSS manifest missing: oss://rosbag-labels-pipeline-bucket2/pipeline/dispatch/latest.json
```

## 单 clip 手工调试（可选）

在 job1 节点参数面板直接写（跳过 OSS）：

```properties
clip_id=sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b
run_id=your-uuid-here
bag_oss_key=rosbags/2026-06-05_13-27-07/output.bag
```

## 为何不用节点上下文

PyODPS3 不能把运行时计算的 `clip_id` 写到「本节点输出参数」；下游 `SKYNET_TASK_INPUT` 会一直是 `${clip_id}` 字面量。OSS manifest 是各版本 DW 都可行的桥接方式。

## 可选：赋值节点方案（需标准版+）

若日后升级 DW，见 `pipeline/dataworks/job0_dispatch_out.sql` 与官方 [赋值节点](https://help.aliyun.com/zh/dataworks/user-guide/assignment-node) 文档。

## Legacy 十节点

旧拓扑 `job1_parse → job2_sample → job2_asr → job3_label → job4_embed` 仍可使用 legacy 节点；dispatch 去重五步、桶名可能仍为 `rosbag-labels-pipline-bucket`（迁移前环境）。新环境统一 **bucket2 + clip_omni_v2**。

## 已废弃

- **`job2_clip_omni`**：单体 omni 节点已 deprecated，dispatch 三步（parse/align/clip_omni）不再适用 v2 工作流。
