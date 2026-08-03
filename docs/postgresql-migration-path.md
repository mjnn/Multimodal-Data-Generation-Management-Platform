# PostgreSQL 迁移路径（M9.2）

> 状态：设计文档（未实施代码迁移）  
> 权威：PRD 部署治理 · `docs/m9-implementation-notes.md` §4  
> 当前默认：`data/app.db`（SQLite）

---

## 1. 目标与范围

HMI 应用态数据库承载账号、Taxonomy、校核、Dataset、审计与 M10 提案队列。单机开发继续使用 SQLite；**staging / 生产** 切换 PostgreSQL 以获得：

- 多实例并发写（Gunicorn / K8s 水平扩展）
- 连接池与备份/恢复标准工具链
- 审计表 append-only 与按时间归档

**不在 M9.2 范围**：`data/timeline.db`、`data/parse_records.db`（Job1 本地时间轴与解析记录，仍可按现有 SQLite 或独立 MC/OSS 策略处理）。

---

## 2. 当前 SQLite 表清单

| 模块 | 表 | 定义入口 |
|------|-----|----------|
| 用户 | `app_user`, `app_user_role`, `app_user_oss_shortcut` | `hmi/app_db.py` |
| Taxonomy | `label_taxonomy_version`, `label_taxonomy_node` | `hmi/taxonomy_db.py` |
| 校核 | `clip_label_review`, `clip_label_field_review` | `hmi/review_db.py`, `review/field_review_db.py` |
| 分配 | `review_assignment_batch`, `review_assignment_item`, `review_workbench_session` | `hmi/review/assignment_db.py` |
| Dataset | `dataset_snapshot`, `aug_recipe` | `hmi/dataset_db.py`, `dataset/aug_recipe_db.py` |
| 审计 | `audit_log` | `hmi/review_db.py` |
| M10 | `taxonomy_proposal` | `hmi/taxonomy_proposal_db.py` |

所有表共用 **同一 SQLite 文件** `APP_DB_PATH = PROJECT_ROOT / "data" / "app.db"`，通过 `hmi.app_db.db_conn()` 上下文管理器访问。

---

## 3. 连接层抽象（第一步）

### 3.1 环境变量

```bash
# 默认（省略）：sqlite:///data/app.db（相对 PROJECT_ROOT）
DATABASE_URL=postgresql://user:pass@host:5432/rosbag_hmi?sslmode=require
```

### 3.2 建议模块结构

```
hmi/backend/hmi/db/
  __init__.py      # get_connection(), is_postgres()
  sqlite.py        # 现有 sqlite3 逻辑迁入
  postgres.py      # psycopg3 或 SQLAlchemy Core
```

`ensure_schema()` 改为：

1. 读取 `DATABASE_URL` 解析 dialect
2. SQLite：保留现有 `executescript` + 列迁移 `_MIGRATION_COLUMNS` 模式
3. PostgreSQL：执行 Alembic `upgrade head`（见 §4）

### 3.3 类型映射

| SQLite | PostgreSQL |
|--------|------------|
| `TEXT` PK (UUID) | `UUID` 或 `TEXT`（与现 API 字符串 id 兼容） |
| `INTEGER` 布尔 | `BOOLEAN` |
| `TEXT` ISO 时间 | `TIMESTAMPTZ`（写入 UTC） |
| `TEXT` JSON | `JSONB`（`filter_json`, `labels_json`, `evidence_json` 等） |
| `CHECK (role IN (...))` | `ENUM` 或 `CHECK` |

**原则**：首版迁移保持列名与 JSON 语义不变，避免业务层大改。

---

## 4. Alembic 迁移策略

### 4.1 初始化

```bash
cd hmi/backend
alembic init alembic
# env.py 从 os.environ["DATABASE_URL"] 读取
alembic revision --autogenerate -m "baseline app schema"
```

Baseline revision 应从各 `ensure_*_schema()` 的 `CREATE TABLE` 合并生成，并包含现有 SQLite 列迁移结果（如 `dataset_snapshot.export_preset`）。

### 4.2 与 `ensure_schema()` 对齐

| 环境 | 启动行为 |
|------|----------|
| dev SQLite | `ensure_schema()` 幂等 DDL（现状） |
| CI PostgreSQL | `alembic upgrade head` + 可选 seed |
| prod | **仅 Alembic**，禁用运行时 `CREATE TABLE IF NOT EXISTS` |

### 4.3 数据迁移（SQLite → PG）

1. 维护窗口内停写 HMI
2. `sqlite3 data/app.db .dump` 或专用脚本按表 `COPY`
3. JSON 列校验：`jsonb_typeof` 抽样
4. 外键顺序：`app_user` → 子表 → `audit_log`
5. 切换 `DATABASE_URL`，冒烟：`test_audit_m9.py` + `test_taxonomy_m10.py`

---

## 5. 审计与大数据表

`audit_log` 为 append-only（M9 只读 API）。PostgreSQL 建议：

- 索引：`(created_at DESC)`, `(action, created_at)`
- 保留策略：按月 `PARTITION BY RANGE (created_at)` 或 cron 归档至冷存储
- 禁止应用层 `UPDATE`/`DELETE` audit 行（与 SQLite 一致）

`dataset_snapshot` / `clip_label_field_review` 随业务增长；首版不分区，监控行数后再评估。

---

## 6. 部署矩阵

| 环境 | 数据库 | 备注 |
|------|--------|------|
| 本地 dev | SQLite | 零配置，默认 |
| CI | SQLite 或 PG service container | E2E 可继续 SQLite |
| staging | PostgreSQL (RDS) | Alembic + 连接池 `pool_size=5` |
| prod | PostgreSQL HA | 只读副本供报表；备份 PITR |

---

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 双写不一致 | 迁移窗口单写；不做 SQLite/PG 双活 |
| JSON 方言差异 | 统一 `json.dumps` 写入；PG 侧 JSONB 运算符仅只读查询 |
| 连接泄漏 | `db_conn()` 上下文管理器 + pool pre_ping |
| 回滚 | 保留 SQLite 快照；`DATABASE_URL` 指回 SQLite 文件 |

---

## 8. 实施工单建议（M11+）

| 序号 | 工单 | 产出 |
|------|------|------|
| 1 | 连接抽象 + `DATABASE_URL` | `hmi/db/` + 单测双 dialect |
| 2 | Alembic baseline | `alembic/versions/001_baseline.py` |
| 3 | CI PG job | GitHub Actions service postgres |
| 4 | 迁移 runbook | ECS 运维文档 + 验收脚本 |
| 5 | H-2 并发压测 | locust / pytest-xdist 多 worker |

---

## 9. 验收（M9.2 docs-only）

- [x] 本文档覆盖表清单、连接抽象、Alembic、审计策略、部署矩阵
- [x] `docs/m9-implementation-notes.md` §4 指向本文档
- [ ] 代码迁移：后续里程碑

---

## 参考

- `hmi/backend/hmi/app_db.py` — `ensure_schema()` 入口
- `project-management/acceptance/M9.2.md` — M9.2 验收记录
