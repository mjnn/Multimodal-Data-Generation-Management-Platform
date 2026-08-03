# 进度变更日志（倒序）

## 2026-07-31 — M8.5 标签树裁剪（派生）

- **后端**：`dataset/taxonomy_crop.py`；derive `taxonomy_crop_label_ids` → 克隆 draft taxonomy + `export_label_ids`；assemble 导出 y 列过滤
- **UI**：`DatasetTaxonomyCropForm`；派生 Modal 区分「标签树裁剪」与「按标签值筛选 clip」
- **测试**：`test_dataset_m8.py` taxonomy crop case；E2E 文案更新

## 2026-07-31 — M8.5 派生向导 · 平衡 + 按标签筛选 clip

- **UI**：`DatasetDetailPage` 派生 Modal（父集条件、按标签筛选、类别平衡、实时预览）
- **工具**：`utils/datasetFilter.ts`（`buildDeriveFilterJson`）；`DatasetListPage` 复用
- **后端**：derive 部分 `filter_json` override merge（已有 `derive.py`）
- **测试**：`test_dataset_m8.py` 补 label crop derive；`e2e/dataset-derive-wizard.spec.ts`
- **验收**：`acceptance/M8.md` A-E2E-2/3

## 2026-07-31 — M10.10 Hub diff/impact/lineage UI

- **UI**：`TaxonomyLineageBar`、`TaxonomyVersionMetaPanel`；版本 Tab 血缘条；Drawer diff/impact；发布前 impact 确认框
- **API 客户端**：`getTaxonomyDiff`、`getTaxonomyImpact`；types 补全
- **E2E**：`e2e/taxonomy-hub.spec.ts` +2（lineage、diff panel）；**4 passed**
- **CURRENT → M7.5 全链 E2E / M9.3 待 DataWorks**

## 2026-07-31 — M9.2 docs + Dataset 创建向导 E2E 补全

- **M9.2**：`docs/postgresql-migration-path.md`；`acceptance/M9.2.md`；tracking M9.2 → done
- **E2E**：`e2e/dataset-create-wizard.spec.ts`（M7.8 导出建议+采用；M7.5 Parquet checkbox；M8 平衡维度 UI）
- **CURRENT → M9.3 H-1 / M7.5 全链 E2E**

## 2026-07-31 — M10 出口 · Taxonomy 语义中枢

- **API**：context、coverage、diff、impact、lineage、proposals；dataset preview `taxonomy_version_distribution`
- **UI**：Hub Tabs（版本/数据洞察/提案）、TaxonomyContextBar、Dataset Taxonomy 契约锁定、Similar 提案入口
- **DB**：`taxonomy_proposal`；R11–R15 落地
- 验收：`test_taxonomy_m10.py` + `e2e/taxonomy-hub.spec.ts` + `npm run build`；`acceptance/M10.md`
- **CURRENT → M9.3 / 维护**

## 2026-07-31 — M10 立项 · Taxonomy 语义中枢

- **DOC-M10**：`docs/m10-implementation-notes.md`（Hub + 全链路契约 + 覆盖率 + diff/impact + 提案）
- **缺口 R11–R15** 写回 `docs/prd-rosbag-labels.md` §13
- **阶段 U**：`docs/design/m10-ui-options.md`（推荐 A−+B）；`DESIGN-M10.md` 待用户确认
- tracking：M10-U、M10.1–M10.9；**CURRENT → M10-U**
- 舱内场景挖掘：M10 只做洞察+提案 ingest（R14）；重算法离线

## 2026-07-31 — M7.8 出口 · 导出顾问

- `export_advisor.py`：按 clip/行数/标签列/embedding 给出 preset、Parquet、取样建议
- `POST /api/datasets/preview` → `export_recommendation`；创建向导「导出建议」+「采用建议」
- 验收：`test_export_advisor_m78.py` + `npm run build`；`acceptance/M7.8.md`

## 2026-07-31 — M7.5 出口 · Parquet 可选导出

- `parquet_export.py`：X/y Parquet + OSS + zip 打包
- `filter_json.include_parquet`；创建向导 Checkbox；meta `parquet_available`
- 验收：`test_dataset_m75.py` + `npm run build`；`acceptance/M7.5.md`
- 依赖：`pyarrow` 加入 `hmi/backend/requirements.txt`

## 2026-07-31 — M9 出口 · 部署与治理

- **M9.1**：`GET /api/admin/audit`（admin-only）；`query_audit_logs` + `actor_username`
- **M9.4**：`taxonomy_hint.py`；dataset preview/detail R10 警告；列表/详情 Alert
- **M9.5**：`AdminAuditPage` + `/admin/audit` 菜单 + `listAuditLogs`
- 验收：`test_audit_m9.py` + `npm run build` 全绿；`acceptance/M9.md`
- **M9.2 PostgreSQL / M9.3 cloud E2E** 延期（docs / H-1）
- **CURRENT → 维护 / 可选 M7.5**

## 2026-07-30 — M6–M8 出口 · 治理链收敛

- **M6**：删旧 ReviewQueue/Detail；`test_review_v2.py` + `e2e/review-v2.spec.ts` + `acceptance/M6.md`
- **M7**：Schema/build 报告/export preset；`test_dataset_m7.py`；前端 dataset UI
- **M8**：balance/oversample/recipe/derive；`test_dataset_m8.py`；examples/
- 回归：`test_prd_appendix_c.py` 全绿（legacy reviewed + OSS mock 修复）
- **CURRENT → M9 预告**

## 2026-07-30 — M8 立项 · Dataset 样本扩展

- 边界确认：平台 = 平衡采样 / 过采样 / recipe 契约 / 派生 lineage；训练侧 = transform 执行
- `docs/m8-implementation-notes.md` + `docs/dataset-augmentation-recipe-schema.md`
- tracking M8.1–M8.7；`acceptance/M8.md`；delivery schema → 1.1 预告
- **依赖 M7 出口**；M9 预留部署/audit

## 2026-07-30 — M7 立项 · Dataset 交付加固

- 产品边界确认：不做 PyTorch 开箱即用；强化 Schema 契约、build 报告、export preset
- `docs/m7-implementation-notes.md` + `docs/dataset-delivery-schema.md` v1.0 草案
- tracking M7.1–M7.7；`acceptance/M7.md` 模板
- **CURRENT**：M6.6 仍为推荐工单；M6 出口后启动 M7

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
