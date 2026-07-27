# 进度变更日志（倒序）

## 2026-07-23 — M6.3 完成 · submit + audit

- POST `/api/review/v2/submit`：confirm/correct/uncertain → merge + rollup
- audit `clip.label_field_review`；rollup 时 OSS export
- reopen 时清空 field reviews
- `test_review_m63.py` 全绿
- **CURRENT → M6.4**

## 2026-07-23 — M6.2 完成 · v2 task queue API

- `v2_tasks.py`：AI 分歧排序（空值优先）+ 全面校核 AI 值匹配
- `v2_router.py`：`/api/review/v2/next|prev|session|tasks/stats|label-options|tasks`
- 会话内 `prev` 历史栈（按 user_id）
- `test_review_m62.py` 全绿
- **CURRENT → M6.3**

## 2026-07-23 — M6.1 完成 · field review DB + merge

- `clip_label_field_review` 表 + `field_review_db.py`
- `merge.py`：`apply_field_review` 合并 labels_json + rollup reviewed
- `test_review_m61.py` 全绿；`acceptance/M6.1.md`
- **CURRENT → M6.2**

## 2026-07-23 — M6 立项 · 校核页 v2

- 用户澄清：逐标签粒度、双模式（AI 分歧 / 全面校核）、单页替换旧 UI
- `docs/prd-review-v2.md` 增补 + 缺口评审 P0=0
- `docs/m6-implementation-notes.md` + tracking M6.1–M6.6
- **CURRENT → M6.1**

## 2026-07-21 — M5 里程碑出口

- `test_prd_appendix_c.py`：附录 C C1–C8、N1–N6 全绿
- WIKI §8/§9 路由与 API 表更新
- `acceptance/M5.md` 全绿
- **PRD P0 能力闭环**

## 2026-07-21 — M4 里程碑出口

- `test_dataset_m4.py` 全绿；m41–m45 spot 回归
- `acceptance/M4.md` 全绿
- **M4 done** → 可开 M5

## 2026-07-21 — M4.6 完成

- `DatasetListPage` / `DatasetDetailPage`、侧栏「数据集」
- `e2e/datasets-admin.spec.ts`；`npm.cmd run build` 全绿
- **CURRENT → M4.7**

## 2026-07-21 — M4.5 完成

- `dataset/router.py`、`require_dataset_read/manager`、audit
- `test_dataset_m45.py` 全绿
- **CURRENT → M4.6**

## 2026-07-21 — M4.4 完成

- `dataset/mc_export.py`、`migrate_dataset_snapshot_row.sql`；build cloud 挂钩
- `test_dataset_m44.py` 全绿
- **CURRENT → M4.5**

## 2026-07-21 — M4.3 完成

- `dataset/build.py`、`export.py`、`hmi/scripts/build_dataset_snapshot.py`
- `test_dataset_m43.py` 全绿
- **CURRENT → M4.4**

## 2026-07-21 — M4.2 完成

- `dataset/assemble.py`（R7/R8 过滤 + X/y）；`test_dataset_m42.py` 全绿
- **CURRENT → M4.3**

## 2026-07-21 — M4.1 完成

- `dataset_db.py`；`test_dataset_m41.py` 全绿
- **CURRENT → M4.2**

## 2026-07-21 — DOC-M4 完成

- `docs/m4-implementation-notes.md` v1.0；工单 M4.1–M4.7 入 tracking
- **CURRENT 推荐 → M4.1**（Dataset DB + dataset_db.py）

## 2026-07-21 — M3 里程碑出口

- `test_review_m3.py` 全绿（S3/C3/C4/N5/N6）
- `acceptance/M3.md` 全绿；子脚本 m31–m34 回归通过
- **M3 done** → 可开 DOC-M4 / M4

## 2026-07-21 — M3.5 完成

- `/review` 队列 + 详情页；侧栏「校核」；409 冲突提示
- `frontend/e2e/review-admin.spec.ts`；`npm run build` 全绿
- **CURRENT → M3.6**

## 2026-07-21 — M3.4 完成

- save → `clip.review`；reopen → `clip.reopen`；409 不写 audit
- `test_review_m34.py` 全绿
- **CURRENT → M3.5**

## 2026-07-21 — M3.3 完成

- `/api/review/*`（queue / detail / save / reopen / enqueue）
- `require_reviewer` 门禁；`test_review_m33.py` 全绿
- **CURRENT → M3.4**

## 2026-07-21 — M3.2 完成

- `review/aggregate.py`（R4 聚合）、`review/enqueue.py`、`hmi/scripts/enqueue_review_clips.py`
- `test_review_m32.py` 全绿
- **CURRENT → M3.3**

## 2026-07-21 — M3.1 完成

- `review_db.py`、`audit.py`；`test_review_m31.py` 全绿
- **CURRENT → M3.2**

## 2026-07-21 — DOC-M3 完成

- `docs/m3-implementation-notes.md` v1.0；工单 M3.1–M3.6 入 tracking
- **CURRENT 推荐 → M3.1**（Review DB + audit_log）

## 2026-07-21 — M2.7 / M2 里程碑出口

- `test_taxonomy_m2.py` 出口集成全绿；`acceptance/M2.md` + `M2.7.md`
- 回归 m22/m24/m26 + frontend build
- **M2 milestone done**；**CURRENT → DOC-M3**

## 2026-07-21 — M2.6 完成

- `taxonomy/export.py` publish → OSS YAML + latest.json + dispatch merge + app_meta
- `pipeline_dispatch.attach_taxonomy_to_dispatch_payload`；job0_dispatch 集成
- `sql/maxcompute/migrate_fact_image_label_taxonomy.sql`；`test_taxonomy_m26.py` 全绿
- **CURRENT → M2.7**

## 2026-07-21 — M2.5 完成

- `TaxonomyPage.tsx` + `/taxonomy` 路由；admin 侧栏「标签树」
- Playwright `e2e/taxonomy-admin.spec.ts`；frontend build 通过
- **CURRENT → M2.6**

## 2026-07-21 — M2.4 完成

- `taxonomy/compat.py`；`GET /api/label-taxonomy` 默认 published + YAML fallback
- 可选 `?version_id=` 预览；`test_taxonomy_m24.py` 全绿
- **CURRENT → M2.5**

## 2026-07-21 — M2.3 完成

- `hmi/backend/hmi/taxonomy/router.py`；`/api/taxonomy/*`（versions/tree/nodes/publish/archive/clone）
- `archive_version` / `clone_version`；`test_taxonomy_m23.py` 全绿
- **CURRENT → M2.4**

## 2026-07-21 — M2.2 完成

- `taxonomy_import.py`、`hmi/scripts/import_taxonomy_yaml.py`；`publish_version()` 入 taxonomy_db
- `test_taxonomy_m22.py` 通过；CLI 导入 v2 draft 68 nodes，二次 skip
- **CURRENT → M2.3**

## 2026-07-21 — M2.1 完成

- `taxonomy_db.py` + schema；`test_taxonomy_m21.py` 通过
- **CURRENT → M2.2**

## 2026-07-21 — DOC-M2 完成

- `docs/m2-implementation-notes.md` v1.0；工单 M2.1–M2.7 入 tracking
- **CURRENT 推荐 → M2.1**（Taxonomy DB schema）

## 2026-07-21 — M1.5 / M1 里程碑出口

- `test_auth_m1_exit.py` 覆盖 C1/C8/N1/N2；M1.1–M1.4 回归全通过
- `acceptance/M1.md`；WIKI §8.1 更新
- **M1 done**；**CURRENT 推荐 → DOC-M2**

## 2026-07-21 — M1.4 完成

- RequireRole、AdminUsersPage、角色菜单；OSS API 后端 ACL
- test_auth_m14.py + frontend build 通过
- **CURRENT 推荐工单 → M1.5**

## 2026-07-21 — M1.3 完成

- 前端 LoginPage、AuthContext、RequireAuth、axios http 客户端
- 现有 API 调用改走 authenticated http；build 通过
- **CURRENT 推荐工单 → M1.4**

## 2026-07-21 — M1.2 完成

- Admin API：`GET/POST/PATCH /api/admin/users` + `require_admin`
- `hmi/scripts/bootstrap_admin.py`；`hmi/backend/scripts/test_auth_m12.py` 全通过
- **CURRENT 推荐工单 → M1.3**

## 2026-07-21 — M1.1 完成

- 实现 `app_db.py`、`auth/`（JWT + middleware + login/me/logout/refresh）
- `main.py` 挂载 AuthMiddleware 与 auth router
- 自动化：`hmi/backend/scripts/test_auth_m11.py` 全通过
- **CURRENT 推荐工单 → M1.2**

## 2026-07-21 — 阶段 E/F Bootstrap

- 创建 `project-management/` 全套（CURRENT、tracking、board、milestones、acceptance 模板）
- 创建 `docs/m1-implementation-notes.md` v1.0，拆 M1.1–M1.5
- 创建 `.cursor/rules/project-progress-handoff.mdc`、`AGENTS.md`

## 2026-07-21 — 阶段 A–B / D

- 用户确认 4 项新能力澄清
- 产出 `docs/prd-rosbag-labels.md` v0.2，P0=0
