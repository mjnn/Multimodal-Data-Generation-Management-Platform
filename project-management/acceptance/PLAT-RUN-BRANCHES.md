# PLAT-RUN-BRANCHES · 同一 Clip 的多次 Run 并列生效 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 规格：`docs/superpowers/specs/2026-09-07-run-branches-design.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-RUN-BRANCHES · 每次管线跑完都是独立分支 |
| 日期 | 2026-09-07 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` local + 前端 `:5174` |
| Agent 自动化摘要 | test_run_branches **6/6**；test_audio_nvh_view **5/5**；test_dataset_m42 OK；tsc OK；Playwright overview-run-branches **1/1 (10.9s)** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 同 clip 两 run 总览两行

**操作步骤**
1. `py -3 hmi/backend/scripts/test_run_branches.py`

**期望结果**
- 同一 `oms_cabin` clip 两次开跑 → light list 两行 `(clip_id, run_id)`
- 后来 NVH 成为 `active_run_id` 后，OMS 仍列出舱内两分支；NVH 工作区只见阵列 run

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-07：`Ran 6 tests` OK

#### A-2 · 检索 / Dataset / 校核 / 重试

**操作步骤**
1. 同上文件：`test_overview_search_returns_both_runs`、`test_dataset_pool_includes_both_labeled_runs`、`test_review_candidates_are_not_collapsed_to_active`、`test_retry_allows_non_active_failed_run`
2. `py -3 hmi/backend/scripts/test_dataset_m42.py`
3. `py -3 hmi/backend/scripts/test_audio_nvh_view.py`

**期望结果**
- 标签检索命中两个 run
- Dataset 池含两条
- 校核候选不被收成 active 一条
- 非 active 的 failed run 可 retry
- 既有 Dataset / NVH 列表隔离不回归

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-07：run-branches 6/6；dataset m42 All M4.2 checks passed；audio_nvh_view 5/5 OK

### A-E2E · Playwright

#### A-E2E-1 · 总览行带 run_id 进入 Explorer

**操作步骤**
1. 后端 `:8000` local、前端 `:5174`
2. `PLAYWRIGHT_SKIP_WEBSERVER=1` `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174` `npx.cmd playwright test e2e/overview-run-branches.spec.ts`

**期望结果**
- `/w/oms_cabin` 点击总览行进入 `/clips/...?run_id=`
- RunSelector 若出现，不含「当前生效」

**通过判断标准**
- 1 passed

**执行记录**
- 2026-09-07：`1 passed (10.9s)` against `:5174`

---

## 二、未做

- 云端 MC `dim_clip.active_run_id` 仍是单指针；未改 DataWorks
- 未 publish `audio_nvh-v2`
- 未 git commit
