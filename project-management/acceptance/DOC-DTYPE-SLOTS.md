# DOC-DTYPE-SLOTS · DataType 槽位 / Sample 内部化 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 日期：2026-08-20  
> 规格：`docs/superpowers/specs/2026-08-18-platform-datatype-kernel-design.md`

| 字段 | 内容 |
|------|------|
| 工单 | DOC-DTYPE-SLOTS |
| Agent 自动化摘要 | 内核 design 增补 D9–D11：采集批展示、开跑多选绑定、产物血缘；Sample 保留为内部实体 |

---

## 一、Agent / 自动化

### A · 文档 / 构建

#### A-1 · 规格含拍板项

**操作步骤**
1. 阅读 `docs/superpowers/specs/2026-08-18-platform-datatype-kernel-design.md` 决策表与 §5.2

**期望结果**
- D9 采集批展示、D10 开跑多选自动 Sample、D11 产物血缘
- Sample 主路径内部化；`slots` / `products` 配方字段说明；UI-DTYPE-EDITOR 后置

**通过判断标准**
- 文档含上述条款且与实现工单一致

**执行记录**
- 2026-08-20：已修订并对照 PLAT-LAKE-RUN-BIND / PLAT-PRODUCT-LINEAGE

### A-E2E

- 无（纯文档）

## 二、人工签字 / 主观（H）

| 编号 | 摘要 |
|------|------|
| H-0 | 无 |

## 三、不在本工单范围

- 可视化新建 DataType 向导（UI-DTYPE-EDITOR）
- publish `audio_nvh-v2` / DataWorks

## 四、点测结论

- [x] A — 可标 done
