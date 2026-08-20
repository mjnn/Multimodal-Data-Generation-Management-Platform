# PLAT-PRODUCT-LINEAGE · 产物缓存键血缘 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 日期：2026-08-20  

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-PRODUCT-LINEAGE |
| Agent 自动化摘要 | `platform_product` 补 `artifact_path`/`run_id`；`GET /api/platform/lineage`；worker 预处理写 product 行；缓存命中 `skipped` |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · lineage_for_source + cache skip

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py -v`（`TestProductLineage`）
2. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py -v`（product cache）

**期望结果**
- `lookup_or_record_product` 首次写入、二次 `skipped=True`
- `lineage_for_source` 返回含 `op_id` / `artifact_path` 的 products

**通过判断标准**
- 相关 unittest 全绿

**执行记录**
- 2026-08-20：bind `5/5`、kernel `15/15`

#### A-2 · API 入口

**操作步骤**
1. 代码审查：`GET /api/platform/lineage?source_id=` / `?product_key=`；`POST /products/lookup`

**期望结果**
- router 暴露查询与 lookup；worker `_run_audio_array_spec` 写 mel/stft/spl 等 product 边

**通过判断标准**
- 入口存在且单测覆盖 store 路径

**执行记录**
- 2026-08-20：通过

### A-E2E

- 本切片无血缘图 UI；湖页开跑 A-E2E 见 `PLAT-LAKE-RUN-BIND.md`

## 二、人工签字 / 主观（H）

| 编号 | 摘要 |
|------|------|
| H-0 | 无 |

## 三、不在本工单范围

- 血缘可视化图（第二切片）；跨 run 强制跳过算子（lookup 已具备，全量 skip 编排可后续）

## 四、点测结论

- [x] A — 可标 done
