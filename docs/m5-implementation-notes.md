# M5 实现说明 — 联调验收 + 文档

| 字段 | 内容 |
|------|------|
| 版本 | v1.0 |
| 对应 PRD | v0.2 附录 **C**、§12 **M5** |
| 里程碑 | **M5** |
| 目标一句话 | PRD 附录 C 正向/负向全量 API 回归 + 文档补齐；不新增业务功能 |
| 前置 | **M4 已出口**（`acceptance/M4.md`） |

---

## 1. 范围

### 1.1 必做（Done 定义）

| # | 能力 | 对应 PRD |
|---|------|----------|
| 1 | 单一出口脚本覆盖 **C1–C8**、**N1–N6**（API 级） | 附录 C |
| 2 | `docs/WIKI.md` §8 路由表补全 taxonomy / review / datasets | M5 交付 |
| 3 | bootstrap / 运维 runbook 补充（admin 初始化、角色说明） | PRD §12 |
| 4 | `acceptance/M5.md` 里程碑签字文档 | 出口 |

### 1.2 明确不做

- 新业务能力（训练 UI、GET `/audit` 等留 backlog）
- Job0–Job4 管线改造
- cloud MC 行数自动化（**H-1**：需 MaxCompute 环境人工点测）

### 1.3 附录 C 映射（脚本断言）

| ID | 断言方式 |
|----|----------|
| C1 | admin 创建 reviewer → 新用户登录 → OSS 403 / clips 200 |
| C2 | YAML import → clone v2 → edit → publish → `GET /label-taxonomy?version_id=` |
| C3 | enqueue → queue pending + AI labels |
| C4 | save reviewed + `audit_log` clip.review |
| C5 | dataset_manager create → ready，仅 reviewed clip |
| C6 | OSS manifest 行数 = clip_count（local）；cloud MC 见 H-1 |
| C7 | trainer list/detail/download；写 review/taxonomy/dataset → 403 |
| C8 | 登录后 GET `/clips`、`/search/clusters` |
| N1 | 未登录 `/api/clips` → 401 |
| N2 | reviewer `POST /admin/users` → 403 |
| N3 | published taxonomy `PUT nodes` → 409 |
| N4 | dataset 默认不含 pending_review clip |
| N5 | stale `updated_at` PUT review → 409 |
| N6 | trainer `PUT /review/clips/{id}` → 403 |

---

## 2. 工单表

| ID | 名称 | 依赖 | 产出 |
|----|------|------|------|
| DOC-M5 | 本说明 + tracking | M4 | 本文档 |
| M5.1 | 附录 C 全量 API 集成脚本 | DOC-M5, M4 | `test_prd_appendix_c.py` |
| M5.2 | WIKI §8/§9 路由与 API 表 | M5.1 | `docs/WIKI.md` 更新 |
| M5.3 | M5 里程碑出口 | M5.1, M5.2 | `acceptance/M5.md` |

---

## 3. 测试最低集

| 类型 | 内容 |
|------|------|
| 脚本 | `py -3 hmi/backend/scripts/test_prd_appendix_c.py`（M5.1） |
| Spot | 各里程碑出口脚本仍可独立运行（m1/m2/m3/m4） |
| E2E | 已有 `e2e/*-admin.spec.ts` 入库；M5 不强制全跑 |
| H | cloud C6 MC 行数一致 |

---

## 4. 完成口径

**M5 出口**：`test_prd_appendix_c.py` 全绿 + WIKI 路由表更新 + `acceptance/M5.md` 全绿。
