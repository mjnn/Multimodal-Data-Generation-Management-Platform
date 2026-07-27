# M6 实现说明 — 校核页 v2（逐标签 · 双模式）

| 字段 | 内容 |
|------|------|
| 里程碑 | M6 |
| PRD | `docs/prd-review-v2.md` |
| 状态 | 待实施 |
| 依赖 | M3 review_db、M2 published taxonomy、Overview clip 卡片 |

---

## 1. 必做

- `clip_label_field_review` 表 + migration
- `/api/review/v2/*` 任务队列 + submit + merge labels_json
- 单页 `ReviewWorkbenchPage` 替换 `ReviewQueuePage` + `ReviewDetailPage`
- Playwright：`e2e/review-v2.spec.ts`（双模式 + 四按钮）
- 旧路由移除 / 重定向

## 2. 明确不做

- 帧级校核、多标签同屏编辑
- 存疑标签统计报表（P2 backlog）
- 旧校核 UI 并存

## 3. 已拍板决策

| ID | 决策 |
|----|------|
| R-M6-1 | 粒度：clip + label_id，表 `clip_label_field_review` |
| R-M6-2 | clip reviewed = 该 clip AI 产出全部 label 键均已 field-review |
| R-M6-3 | dataset y 仍读 `clip_label_review.labels_json`（field review 合并） |
| R-M6-4 | field review UNIQUE；clip 级 optimistic lock 保留 |
| 全面校核筛选 | AI 值 = 所选 value |
| 不确定 | value 置空 + human_doubtful |
| UI | 完全替换旧校核页 |

## 4. 工单表

| ID | 标题 | 范围 | 依赖 |
|----|------|------|------|
| M6.1 | field review DB + merge | `app_db` schema, `field_review_db.py`, merge into labels_json | DOC-M6 |
| M6.2 | v2 task queue API | `review/v2/` router, AI dispute ordering, comprehensive filter | M6.1 |
| M6.3 | submit + clip status rollup | POST submit, reviewed rollup, audit | M6.2 |
| M6.4 | ReviewWorkbenchPage | 单页双 Tab + clip 卡片 + 四按钮 | M6.2 |
| M6.5 | 路由替换 + 移除旧页 | App.tsx, AppLayout 菜单, 删 ReviewQueue/Detail | M6.4 |
| M6.6 | pytest + Playwright + acceptance | test_review_v2.py, e2e/review-v2.spec.ts, acceptance/M6.md | M6.3;M6.5 |

## 5. 后端文件（预期）

```text
hmi/backend/hmi/review/
  field_review_db.py      # CRUD clip_label_field_review
  v2_tasks.py             # next/prev/stats 队列逻辑
  v2_router.py              # /api/review/v2/*
  merge.py                  # field → clip_label_review.labels_json
```

## 6. 前端文件（预期）

```text
frontend/src/pages/ReviewWorkbenchPage.tsx
frontend/src/components/ReviewClipCard.tsx
frontend/src/components/ReviewActionBar.tsx
frontend/src/hooks/useReviewV2Session.ts
frontend/e2e/review-v2.spec.ts
```

## 7. 测试最低集

**A 类**

- `test_review_v2.py`：dispute 排序、comprehensive 筛选、submit 合并、rollup reviewed
- `npm run build`

**A-E2E**

- reviewer 登录 → AI 分歧模式 → 符合 → 跳下一条
- 全面校核选 label+value → 修正 → labels 更新

## 8. 演示数据

沿用 `seed_demo_clip_data.py`：

- AI 分歧：`demo_morning_city`（空 day_period）、`demo_holiday_mall`（is_holiday 分歧）
- 全面校核：`day_period=morning` → demo_morning_city（若 AI 有值）/ 需按 mock 实际值调整
