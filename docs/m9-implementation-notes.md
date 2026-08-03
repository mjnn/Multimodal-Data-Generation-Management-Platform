# M9 实现说明 — 部署与治理

| 字段 | 内容 |
|------|------|
| 版本 | v1.0 |
| 对应 PRD | v0.2 R10、审计、多环境 |
| 里程碑 | **M9** |
| 目标一句话 | 提供 **admin 审计只读 API + UI**、**taxonomy 版本差异提示（R10）**；PostgreSQL / cloud E2E 仅文档与 H 项 |
| 前置 | **M8 已出口** |

---

## 1. 范围

### 1.1 必做（M9.1 + M9.4）

| # | 能力 | 说明 |
|---|------|------|
| 1 | **GET `/api/admin/audit`** | admin-only；筛选 `action` / `resource_type` / `resource_id` / `actor_id`；分页 |
| 2 | **`query_audit_logs`** | `audit.py` 扩展；JOIN `app_user.username` → `actor_username` |
| 3 | **AdminAuditPage** | `/admin/audit` 菜单；action 筛选 + resource_type 输入 |
| 4 | **Taxonomy R10 提示** | `taxonomy_hint.py`；dataset preview / detail 返回 `taxonomy_version_warning`、`taxonomy_mixed_hint` |
| 5 | **验收** | `test_audit_m9.py` + `acceptance/M9.md` |

### 1.2 文档 / 延期（M9.2 / M9.3）

| ID | 标题 | 状态 |
|----|------|------|
| M9.2 | PostgreSQL 迁移路径 | **docs only** — 见 §4 |
| M9.3 | sdk_v1 cloud 全链验收 | **H-1** — 需 DataWorks + OSS/MC 环境 |

### 1.3 明确不做

- 审计日志写入新 action（M3–M8 已有写路径）
- 训练侧 / PyTorch 交付
- 平台内执行 aug transform

---

## 2. API

### GET `/api/admin/audit`

**Auth**: `require_admin`

**Query**:

| 参数 | 说明 |
|------|------|
| `action` | 精确匹配，如 `dataset.create` |
| `resource_type` | 如 `dataset_snapshot` |
| `resource_id` | UUID |
| `actor_id` | 用户 ID |
| `limit` | 1–200，默认 50 |
| `offset` | 默认 0 |

**Response**:

```json
{
  "items": [{ "id", "actor_id", "actor_username", "action", "resource_type", "resource_id", "detail", "created_at" }],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

### Dataset preview / detail 扩展字段

| 字段 | 来源 |
|------|------|
| `taxonomy_version_warning` | filter taxonomy ≠ published |
| `taxonomy_mixed_hint` | ready 快照且未锁定 taxonomy 版本 |
| `published_taxonomy_version_code` | 当前 published 版本号 |

---

## 3. 文件清单

| 路径 | 变更 |
|------|------|
| `hmi/backend/hmi/audit.py` | `query_audit_logs` |
| `hmi/backend/hmi/admin/router.py` | `GET /audit` |
| `hmi/backend/hmi/dataset/taxonomy_hint.py` | **new** |
| `hmi/backend/hmi/dataset/router.py` | preview/detail 注入 taxonomy context |
| `hmi/backend/scripts/test_audit_m9.py` | **new** |
| `hmi/frontend/src/pages/AdminAuditPage.tsx` | **new** |
| `hmi/frontend/src/api/index.ts` | `listAuditLogs` |
| `hmi/frontend/src/App.tsx` | route `/admin/audit` |
| `hmi/frontend/src/layouts/AppLayout.tsx` | 菜单项 |
| `hmi/frontend/src/pages/DatasetListPage.tsx` | preview warning Alert |
| `hmi/frontend/src/pages/DatasetDetailPage.tsx` | detail warning Alert |

---

## 4. PostgreSQL 迁移路径（M9.2 · docs done）

当前 HMI 应用态 SQLite：`data/app.db`（用户、taxonomy、review、dataset、audit、taxonomy_proposal）。

**完整设计**：[`postgresql-migration-path.md`](postgresql-migration-path.md)（表清单、`DATABASE_URL`、Alembic baseline、审计分区、部署矩阵、M11+ 实施工单）。

代码迁移 **未实施**；staging/prod 切换 PG 见该文档 §8。

---

## 5. 验收命令

```bash
py -3 hmi/backend/scripts/test_audit_m9.py
cd hmi/frontend && npm run build
```

---

## 6. 与 M8 衔接

- M8 已写 audit：`dataset.create/delete/derive`、`aug_recipe.*`、`clip.review` 等
- M9 仅 **读路径** 产品化，不改变写侧语义
