---
name: rosbag-sdk-pipeline
description: >
  开发本仓库 SDK v1 管线与 DataWorks 上云时使用：oms-multimodal-sdk 阶段、sdk_v1 OSS 树、
  aig_sdk__ 表、单 Driver hybrid、DPE pickle、dispatch OSS、验数脚本。
  不适用于：HMI DataType 配方/源湖 UI、本机 ossutil 只读（用 cloud-cli-ops）、
  为新 bag 扩展 clip-omni v2 Job1–4。
---

# SDK v1 与 DataWorks

新数据默认：**OMS Multimodal SDK + sdk_v1 + `aig_sdk__`**。  
生产粘贴：`pipeline/dataworks/bundled/sdk_pipeline_driver_node.py`。

## Gotchas

1. **DPE UDF 用 dataclass/自定义 class** — pickle 失败 `Can't get attribute on __main__`。**纠正：只用 dict/list/内置类型；提交前 `check_dpe_nodes.py`。**
2. **拷贝 bag 到 clips/.../raw** — 违反架构。**纠正：`rosbags/` 原地读，`bag_oss_key` 记录。**
3. **用节点输出参数传 clip_id** — DataWorks 无赋值节点会丢。**纠正：`pipeline/dispatch/latest.json`。**
4. **只改 thin `sdk_pipeline_driver_node.py` 不 bundle** — 控制台仍是旧粘贴。**纠正：跑 `bundle_sdk_pipeline_driver.py` 后粘贴 bundled。**
5. **DPE 里嵌套 MaxFrame AI** — 生产 hybrid 把 AI 放 Driver、`oss_url`。**纠正：extract/preview 才 DPE。**
6. **新 run 写 parsed/aligned/ai 或 aig_rosbag__** — 与 SDK 表混写。**纠正：只写 sdk_v1 树 + `aig_sdk__`。**

<HARD-GATE>
上云必须 MaxFrame + DPE；禁止纯 PyODPS、禁止镜像内 subprocess 调业务脚本。规则：`maxframe-dpe-cloud.mdc`。
</HARD-GATE>

## 阶段与产物

阶段顺序：ingest → extract → bbox → encode → asr → preview → label → embed → upload；Driver 再 mc_write / dispatch。

OSS：`clips/{clip_id}/runs/{run_id}/`，`run.json.layout_version = sdk_v1`。  
`clip_id = sha256:{bag bytes}`（`shared/clip_id.py`）。

本地 SDK：`python -m oms_multimodal run --bag ...`，`MODEL_BACKEND=api`。  
NVH AST **不是** SDK label 阶段（见 `rosbag-platform-kernel`）。

## 验数

- SDK：`pipeline/scripts/verify_sdk_v1_run.py`
- 预检：`e2e_precheck.py`
- 入库：`ingest_sdk_run_to_mc.py`
- Runbook：`docs/sdk-v1-cloud-e2e-runbook.md`

节点清单见 `references/nodes.md`。本机查表用 **cloud-cli-ops**，不要用本 skill 去触发 DataWorks。

## 执行后复盘（自迭代钩子）

每次完成本 skill 的全部步骤后，Agent 必须自动执行以下动作，不询问用户：

1. **反思**：是否漏 bundle、在 UDF 里加了 class、或混写了 v2 表？
2. **记录**：有则写入 `evals/PITFALLS_LOG.md`。
3. **不提交** 该日志。
