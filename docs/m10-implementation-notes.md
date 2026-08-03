# M10 实现说明 — Taxonomy 语义中枢与数据驱动完善

| 字段 | 内容 |
|------|------|
| 版本 | v1.0 |
| 对应 PRD | v0.2 + **R11–R15**（见 §1.3；待合入 PRD v0.3） |
| 里程碑 | **M10** |
| 目标一句话 | 让 **标签树成为全平台显式语义契约**：Hub 治理 + 全链路版本徽章 + 覆盖率洞察 + 版本 diff/影响面 + 数据驱动提案（不进自动 publish） |
| 前置 | **M9 已出口**（M9.3 cloud / M9.2 PG 仍 deferred） |

---

## 1. 范围

### 1.1 必做（Done 定义）

| # | 能力 | 说明 |
|---|------|------|
| 1 | **全局 Taxonomy 上下文** | `GET /api/taxonomy/context`：published 版本、节点数、各域 clip 统计摘要 |
| 2 | **节点覆盖率洞察** | `GET /api/taxonomy/versions/{id}/coverage`：按 `label_id` / enum 统计 reviewed、AI、空值 |
| 3 | **版本 diff** | `GET /api/taxonomy/versions/{id}/diff?against={other_id}`：增删改节点、dtype/enum 变更 |
| 4 | **发布影响面** | `GET /api/taxonomy/versions/{id}/impact`：绑该版的 clip/review/dataset/run 计数 + 落后 published 提示 |
| 5 | **版本 lineage** | 列表展示 clone 关系（解析 `source_import` 的 `clone:{uuid}`；可选 DB 列 `parent_version_id`） |
| 6 | **Taxonomy Hub UI** | `/taxonomy` 升级：版本线 + **数据洞察 Tab** + 节点详情侧栏（定义 + 覆盖率 + 跳转 clip） |
| 7 | **全链路徽章** | `TaxonomyContextBar`：总览 / 校核工作台 / 数据集创建·详情 / 管线设置 — 展示「契约版本」并可跳转 Hub |
| 8 | **数据集契约锁定 UI** | 创建快照显式选择：`跟随各 clip 校核版本（默认 R10）` / `仅某 taxonomy 版本`；预览展示版本分布 |
| 9 | **taxonomy 提案（轻量）** | `taxonomy_proposal` 表 + API：证据 clip、建议文案、状态 `open/merged/rejected`；**合入 = 打开 draft 编辑器，不自动 publish** |
| 10 | **审计** | `taxonomy.proposal.create`、`taxonomy.publish` 前 impact 快照写入 audit detail |
| 11 | **验收** | `test_taxonomy_m10.py` + Playwright `e2e/taxonomy-hub.spec.ts` + `acceptance/M10.md` |

### 1.2 明确不做（留给 M10+ / 研究链路）

| 项 | 原因 |
|----|------|
| 无监督聚类 / 大规模场景挖掘 Job | 重算力；M10 只提供 **ingest API + 展示**（R14） |
| 自动 publish / 自动改 published 节点 | 违背 R3 |
| 批量重打标 Job3 / 批量打回 reviewed | 违背 R10、R11 |
| taxonomy 变更自动改 `clip_label_review.labels_json` | 违背 R2/R10；仅提案 + 人工 draft |
| 帧级 taxonomy 编辑 | PRD Out |
| PostgreSQL 迁移 | M9.2 deferred |

### 1.3 已拍板决策（M10 冻结）

| ID | 决议 |
|----|------|
| **R11** | **数据洞察只读**：覆盖率、缺口、提案均为观察层；不得写回 clip y 或 published 树 |
| **R12** | **提案工作流**：`taxonomy_proposal` 仅 admin/dataset_manager 创建；合并路径 = 关联 draft 版本人工编辑后 publish（R3） |
| **R13** | **Dataset 契约 UI**：默认保持 R10（不锁定、允许多版本混导）；用户可显式 `filter_json.taxonomy_version_id` 锁定 |
| **R14** | **舱内场景挖掘分层**：平台负责证据聚合与提案入口；离线/Notebook/MaxFrame 聚类结果经 `POST /api/taxonomy/proposals` 或脚本导入 |
| **R15** | **版本 lineage**：优先解析 `source_import=clone:{id}`；M10.2 可增 `parent_version_id` 列便于图展示 |

### 1.4 M10 缺口评审（P0=0）

| ID | 严重度 | 缺口 | 决议 |
|----|--------|------|------|
| G13 | P1 | 覆盖率统计来源 | **R11** — local 读 `clip_label_review` + `labels_json`；cloud 读 MC 表（local 模式优先实现） |
| G14 | P1 | 提案能否自动改树 | **R12** — 否 |
| G15 | P1 | 数据集是否默认锁 taxonomy | **R13** — 否，显式可选 |
| G16 | P1 | 重挖掘是否在平台算 | **R14** — 否，结果 ingest |
| G17 | P2 | lineage 存哪 | **R15** — clone 解析 + 可选列 |

**P0 计数：0** — 可进入阶段 U → 实施。

### 1.5 验收切片

- [ ] **T1** 任意页可见 published taxonomy 徽章，点击进 Hub
- [ ] **T2** Hub「数据洞察」见 ≥1 叶子节点覆盖率（reviewed 数 / enum 分布）
- [x] **T3** 两版本 diff 可见「新增/删除/改 enum」列表
- [x] **T4** publish 前 impact API 返回 clip/dataset 计数
- [ ] **T5** 数据集创建可选锁定 taxonomy 版本；预览见 `taxonomy_version_warning` / 分布
- [ ] **T6** 从相似 clip / 低置信（M10.6 可选）创建 proposal，Hub 可见且可标记 merged/rejected
- [ ] **T7** audit 可查 `taxonomy.proposal.create`

---

## 2. 状态机

### 2.1 `taxonomy_proposal`

```text
open → merged | rejected
```

- **merged**：人工已在 draft 中实现（记录 `merged_version_id` 可选），不自动 publish
- **rejected**：关闭，保留 audit

### 2.2 Taxonomy version（沿用 R3）

```text
draft → published → archived
```

- publish 前调用 impact API；UI 确认对话框（非阻断）

---

## 3. 数据模型

### 3.1 新增 `taxonomy_proposal`

```sql
CREATE TABLE taxonomy_proposal (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  proposal_type TEXT NOT NULL CHECK (proposal_type IN (
    'new_node', 'extend_enum', 'deprecate_node', 'scene_cluster', 'other'
  )),
  target_label_id TEXT,
  suggested_patch_json TEXT,  -- 人类可读建议，非自动 apply
  evidence_json TEXT NOT NULL,  -- { clip_ids[], reason, source: manual|similar|low_confidence|import }
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','merged','rejected')),
  taxonomy_version_id TEXT REFERENCES label_taxonomy_version(id),
  merged_version_id TEXT REFERENCES label_taxonomy_version(id),
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_taxonomy_proposal_status ON taxonomy_proposal (status, created_at DESC);
```

### 3.2 可选迁移 `label_taxonomy_version.parent_version_id`

- backfill：`source_import LIKE 'clone:%'` → 解析 UUID

---

## 4. API 子集

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/taxonomy/context` | 已登录 | 全局上下文（published、统计摘要） |
| GET | `/api/taxonomy/versions/{id}/coverage` | 已登录 | 节点/enum 覆盖率 |
| GET | `/api/taxonomy/versions/{id}/diff` | 已登录 | query `against` 必填 |
| GET | `/api/taxonomy/versions/{id}/impact` | admin | 影响面 |
| GET | `/api/taxonomy/versions/{id}/lineage` | 已登录 | 祖先/子孙 clone 链 |
| GET | `/api/taxonomy/nodes/{label_id}/usage` | 已登录 | clip 数、dataset filter 引用数 |
| GET | `/api/taxonomy/proposals` | admin, dataset_manager | 列表 |
| POST | `/api/taxonomy/proposals` | admin, dataset_manager | 创建提案 |
| PATCH | `/api/taxonomy/proposals/{id}` | admin | merged/rejected |

**不实现（M10）**：自动 merge patch 到 nodes；Webhook；MC 实时聚类。

---

## 5. 前端页面

### 5.1 路由与交互

| 路由 | 变更 |
|------|------|
| `/taxonomy` | Tab：**版本** / **数据洞察** / **提案队列**；版本详情 Drawer：diff / impact / 编辑 |
| `/taxonomy/versions/:id` | 深链：洞察 + diff 对比 |
| 全局 | `TaxonomyContextBar` 组件嵌入 AppLayout 内容区顶或 PageHeader extra |

**数据集创建**（`DatasetListPage`）：

- 新增「Taxonomy 契约」Select：`默认（各 clip 校核版本）` / `锁定版本…`
- 预览 panel 增：版本分布 mini 表（单版本 / 混合）

**校核工作台**：

- Header：`校核契约 {version_code}`；若 ≠ published → Alert + 链 Hub diff

**管线设置**：

- 已有 taxonomy 选择；增「与 published 关系」badge

### 5.2 阶段 U（必须先于 M10.4+ UI 视觉工单）

| 项 | 路径 |
|----|------|
| 方案对比 | `docs/design/m10-ui-options.md` |
| 选定设计 | `docs/design/DESIGN-M10.md`（**已定稿 R-UI-M10-1：A−+B**） |
| 决议 | R-UI-M10-1 … |

**U 已完成（R-UI-M10-1 A−+B）** — M10.4+ UI 工单可开工。

---

## 6. 工单表

| ID | 名称 | 依赖 | 产出 |
|----|------|------|------|
| **DOC-M10** | 本文档 | M9 | `docs/m10-implementation-notes.md` |
| **M10-U** | UI/UX 多方案 + DESIGN 定稿 | DOC-M10 | `m10-ui-options.md` + `DESIGN-M10.md` + 用户 R-UI |
| **M10.1** | context + coverage API | DOC-M10 | `taxonomy/insights.py` + router + test |
| **M10.2** | diff + impact + lineage API | M10.1 | `taxonomy/diff.py` `taxonomy/impact.py` |
| **M10.3** | proposal DB + API + audit | M10.1 | `taxonomy_proposal_db.py` |
| **M10.4** | Taxonomy Hub Tabs（洞察/diff/提案） | M10-U, M10.1–M10.3 | `TaxonomyPage` refactor |
| **M10.5** | 全局 TaxonomyContextBar + 校核/管线嵌入 | M10-U, M10.1 | 多页组件 |
| **M10.6** | Dataset 契约锁定 + 版本分布预览 | M10-U, M10.1 | `DatasetListPage` |
| **M10.7** | 节点 usage + clip 列表跳转 | M10.2 | Hub 节点侧栏 |
| **M10.8** | 从相似 clip 创建 proposal（入口） | M10.3, M10.7 | Clip/similar UI 按钮 |
| **M10.9** | 验收与 E2E | M10.4–M10.8 | `test_taxonomy_m10.py` `e2e/taxonomy-hub.spec.ts` `acceptance/M10.md` |
| **M10.10** | Hub diff/impact/lineage UI | M10.4 | LineageBar + VersionMetaPanel + publish impact |
| **M10** | 里程碑出口 | M10.9 | CURRENT → 下一 DOC |

**推荐实施顺序**：

```text
DOC-M10 → M10-U（用户选定 DESIGN）
  → M10.1 → M10.2 → M10.3（后端可并行）
  → M10.4 ∥ M10.5 ∥ M10.6
  → M10.7 → M10.8 → M10.9
```

---

## 7. 测试最低集

| 类型 | 内容 |
|------|------|
| A | `test_taxonomy_m10.py`：context、coverage、diff、impact、proposal CRUD |
| A | `npm run build` |
| A-E2E | Hub 洞察 Tab 有数据；徽章跳转；dataset 锁定版本预览 |
| H | 可选：publish 前 impact 对话框主观（0–1 条） |

---

## 8. 与既有模块衔接

| 模块 | M10 增强 |
|------|----------|
| M2 Taxonomy | Hub、lineage、diff |
| M3/M6 Review | 契约 header、低置信 → proposal |
| M4/M7/M8 Dataset | 契约锁定、版本分布、R10 强化 |
| M9 audit / taxonomy_hint | proposal audit、impact 快照 |
| Search / Similar | 相似 clip → proposal 证据 |

---

## 9. 完成口径

**M10 出口** = T1–T7 验收通过 + A/A-E2E 全绿 + `acceptance/M10.md` 签字。

---

## 10. 舱内场景挖掘（M10 边界说明）

M10 落地 **第一层（平台洞察）**：

- 覆盖率 / 缺口 / enum 从未出现
- 人工或脚本写入的 **scene_cluster 提案**
- 从 **向量相似**、**低置信校核** 一键「建议补充 Taxonomy」

**第二层（离线算法）** 在 M10 仅约定 ingest 格式：

```json
{
  "title": "疑似新场景：副驾低头+夜间",
  "proposal_type": "scene_cluster",
  "evidence": { "clip_ids": ["sha256:..."], "source": "import", "cluster_id": "..." },
  "suggested_patch_json": { "note": "建议新增 L2.x 或扩展 enum" }
}
```

---

开工前：**DOC-M10 ✓ → M10-U 用户选定 → M10.1**。
