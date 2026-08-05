# 当前进度指针（跨会话权威入口）

> 最后更新：2026-08-05  
> 更新人：Agent（P0 前置已就绪，待 DW 跑探针）

---

## 一眼看懂

| 字段 | 当前值 |
|------|--------|
| 当前里程碑 | **M10 已出口** · Taxonomy 语义中枢 |
| 推荐下一个工单 | **P0 DataWorks 探针**：粘贴 `bundled/sdk_pipeline_driver_node.py` + `workflow-params-sdk-pipeline-p0.example` |
| 本机前置 | **已就绪**：bucket2 bag+taxonomy、`aig_sdk__*` DDL、`e2e_precheck` OK、Driver bundle 已生成 |
| 禁止抢跑 | P0 mc-in-DPE 未过前勿宣称 M9.3 出口；`dpe_image` 须含 `oms-multimodal-sdk[mc]` |

---

## 新会话开场白

```text
SDK v1 主路径已切单节点 sdk_pipeline_driver（apply_chunk + stages）。代码 Task 1–5 已入库；runbook/CURRENT 已对齐。
下一步：DataWorks P0 探针（mc ASR in DPE）→ P1 verify_sdk_v1_run → M9.3 A-C/H。
多节点 sdk_* 工作流冻结，仅参考/回退。
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
| M9.3 | sdk_v1 cloud 全链（H-1） | **in_progress** — 单 Driver 代码 done；**P0 DW 探针待跑**；A-C/H 待 P1 |
| M7.5 | Parquet 全链 E2E | 可选 |

**M9.3 入口**：`docs/sdk-v1-cloud-e2e-runbook.md` · `acceptance/M9.3.md` · 设计 `docs/superpowers/specs/2026-08-04-sdk-single-driver-apply-chunk-design.md`
