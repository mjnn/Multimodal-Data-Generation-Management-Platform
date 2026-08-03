# 当前进度指针（跨会话权威入口）

> 最后更新：2026-07-31  
> 更新人：Agent（M10.10 Hub diff/impact/lineage UI）

---

## 一眼看懂

| 字段 | 当前值 |
|------|--------|
| 当前里程碑 | **M10 已出口** · Taxonomy 语义中枢 |
| 推荐下一个工单 | **M7.5 全链 E2E** · 维护回归 · M9.3 待 DataWorks |
| 禁止抢跑 | 无 P0 阻塞项 |

---

## 新会话开场白

```text
M8.5 派生向导已支持标签树裁剪（克隆 draft taxonomy + 导出 y 列过滤）、按标签筛选 clip、类别平衡；M9.3 待 DataWorks；可选 M7.5 zip 全链 E2E。
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

## 延期 / 可选

| ID | 标题 |
|----|------|
| M9.3 | sdk_v1 cloud 全链验收 (H-1) |
| M7.5 | Parquet 全链 E2E（创建→ready→zip 含 parquet） |
