# 当前进度指针（跨会话权威入口）

> 最后更新：2026-08-20  
> 更新人：Agent（DOC-DTYPE-SLOTS + PLAT-LAKE-RUN-BIND + PLAT-PRODUCT-LINEAGE · Sample 内部化开跑）

---

## 一眼看懂

| 字段 | 当前值 |
|------|--------|
| 当前里程碑 | **平台内核重构进行中** |
| 刚完成 | **UI IA**：源湖=入库+OSS；管线管理「源湖开跑」；侧栏无独立 OSS |
| 推荐下一个工单 | **UI-NVH-REVIEW-SAVE**（语义 L6 人工写回）或 **UI-DTYPE-EDITOR**（后置）；勿 publish `audio_nvh-v2` |
| M9.3 | A-C 基本闭合；**H-2 暂停，不排期** |
| 禁止抢跑 | 勿做 HMI 在线 H-2；勿 **publish** `audio_nvh-v2`；勿宣称 IVI 业务打标已完成；勿用 VL 打 bbox；勿改 DataWorks |

---

## 新会话开场白

```text
当前重点是重构平台内核，不要做 HMI 在线 H-2。

刚完成 UI 信息架构调整：源湖只负责入湖+OSS；选类型/筛源/开跑在管线管理「源湖开跑」。
不要 publish audio_nvh-v2。

规格：docs/superpowers/specs/2026-08-18-platform-datatype-kernel-design.md（D9–D11）。
```

---

## M10 工单（已全部完成）

| ID | 标题 |
|----|------|
| DOC-M10 / M10-U | 实现说明 + UI 定稿 |
| M10.1–M10.3 | context/coverage/diff/impact/lineage/proposals API |
| M10.4–M10.8 | Hub Tabs、ContextBar、Dataset 契约、Similar 提案 |
| M10.9 | test_taxonomy_m10.py + e2e/taxonomy-hub.spec.ts |
| M10.10 | Hub 版本血缘 + Drawer diff/impact + 发布前 impact 确认 |

**验收**：`acceptance/M10.md`

---

## 进行中 / 可选

| ID | 标题 | 状态 |
|----|------|------|
| DOC-DTYPE-SLOTS | Sample 内部化 / slots / lineage 规格 | **done（A）** — `acceptance/DOC-DTYPE-SLOTS.md` |
| PLAT-LAKE-RUN-BIND | 开跑多选自动 Sample | **done（A + A-E2E）** — `acceptance/PLAT-LAKE-RUN-BIND.md` |
| PLAT-PRODUCT-LINEAGE | 产物血缘 API + worker 写入 | **done（A）** — `acceptance/PLAT-PRODUCT-LINEAGE.md` |
| UI-DTYPE-EDITOR | 新建 DataType 表单 | **后置 todo** |
| PLAT-DTYPE-LAKE-REUSE | 列表/多选复用已入库 Source | **done**（已被开跑绑定 UX 替代主路径组 Sample） |
| UI-NVH-REVIEW-SAVE | 语义 L6 人工写回 | 推荐下一 |
| M9.3-H-2 | HMI 在线主观 | **暂停不排期** |
| M9.3 | sdk_v1 cloud 全链（hybrid） | **in_progress** — A-C-1/2 pass；**H-2 待签** |
| M7.5 | Parquet 全链 E2E | 可选 |

**M9.3 入口**：`docs/sdk-v1-cloud-e2e-runbook.md` · `acceptance/M9.3.md`

**Cloud 验数锚点（2026-08-10 · hybrid 4-bag）**

| 项 | 值 |
|----|-----|
| bucket | `rosbag-labels-pipeline-bucket2` |
| ds | `20260810` |
| clip1 | `sha256:9a4ac3a2704dd052630c9b3cd320760b9214febc22c53cf14b41b0806f4d81ed` |
| run1 | `bb319286-3cad-4b56-93f9-32cc25329bb9` |
| 架构 | DPE extract+preview（`dpe_parallel=4`）+ Driver MaxFrame AI asr/label/embed（`ai_media_mode=oss_url`）+ mc_write + dispatch |
| verify | `Summary: 18/18 passed` |
| 节点粘贴 | `pipeline/dataworks/bundled/sdk_pipeline_driver_node.py` |
