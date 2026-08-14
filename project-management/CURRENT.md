# 当前进度指针（跨会话权威入口）

> 最后更新：2026-08-14  
> 更新人：Agent（HMI-BBOX-OVERLAY · 可编辑 jsonl 叠加层；下一步仍建议 HMI 在线 H-2）

---

## 一眼看懂

| 字段 | 当前值 |
|------|--------|
| 当前里程碑 | **M10 已出口** · Taxonomy 语义中枢 |
| 刚完成 | **HMI-BBOX-OVERLAY**：原图 SVG 叠加编辑 `bboxes.jsonl` + PUT 写回；烧录 MP4 降级为「烧录预览」 |
| 推荐下一个工单 | **HMI 在线模式**读 `aig_sdk__*` + OSS `rosbag-labels-pipeline-bucket2`（H-2 主观签字） |
| M9.3 | **A-C 基本闭合**（hybrid 单 Driver · verify 18/18）；**H-2 待人工** |
| 禁止抢跑 | 勿宣称 M9.3 全出口至 H-2 签字；勿再编排旧多节点 sdk_* 工作流 |

---

## 新会话开场白

```text
HMI-BBOX-OVERLAY（local）：Explorer 原图叠加可编辑框，源为 bboxes.jsonl；PUT upsert_frame 写回 artifact。
下一步仍建议：HMI 切「在线」读 aig_sdk__ + bucket2，打开 clip1 做 H-2 主观验收。
锚点 clip=sha256:9a4ac3a2704dd052630c9b3cd320760b9214febc22c53cf14b41b0806f4d81ed run=bb319286-3cad-4b56-93f9-32cc25329bb9。
可选：本地有 jsonl 的 clip 上做 H-1 叠加编辑手感。
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
| HMI-BBOX-OVERLAY | 可编辑 BBox 叠加层（jsonl） | **done（A）** — `acceptance/HMI-BBOX-OVERLAY.md`；H-1 待人工 |
| HMI-SDK-MODALITY | 原始媒体上传 + Planner 模态编排 | **done（A）** — `acceptance/HMI-SDK-MODALITY.md`；H-1 待人工；云端媒体未做 |
| HMI-SDK-BBOX | SDK BBox + enum_tree → HMI local | **done（A）** — `acceptance/HMI-SDK-BBOX.md`；H-1/H-2 待人工 |
| HMI-TEST-MODE | 测试模式开关 + 重置测试数据 | **done** — `acceptance/HMI-TEST-MODE.md`（H-1/H-2 待人工） |
| M9.3 | sdk_v1 cloud 全链（hybrid） | **in_progress** — A-C-1/2 pass；A-C-3 sync **可选**（在线直读 MC）；**H-2 待签** |
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
