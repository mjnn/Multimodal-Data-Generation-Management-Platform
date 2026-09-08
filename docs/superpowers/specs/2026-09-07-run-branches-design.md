# Design: 同一 Clip 的多次 Run 并列生效

> 日期：2026-09-07  
> 状态：implemented（2026-09-07；acceptance/PLAT-RUN-BRANCHES.md）  
> 工单：**PLAT-RUN-BRANCHES**  
> 前置：用户确认粒度 = 每次管线跑完都是独立分支（同配方重跑也两行）  
> 不抢跑：不 publish `audio_nvh-v2`；不改 DataWorks / DPE / MC `dim_clip` 云端指针

同一 bag（`clip_id` = 内容 hash）上的每一次管线执行是一条**活着的分支**，不是被 `dim_clip.active_run_id` 盖掉的历史版本。

---

## 1. 目的

总览、检索、Dataset、校核队列不再只认「当前生效」那一条 run。  
一行 = `(clip_id, run_id)`。打开详情必须带 `?run_id=`。

## 2. 非目标

- 改 DataWorks / DPE / Job 顺序 / 云端 MC `dim_clip.active_run_id` 语义
- publish `audio_nvh-v2`
- 删除 `dim_clip.active_run_id` 列（仍作 Explorer **无 query 时的默认 run**、worker 写入的 latest 指针）
- 云模式 list/search（仍走 MC 单指针，直到另开工单）

## 3. 已拍板

| ID | 决策 | 选择 |
|----|------|------|
| D1 | 列表粒度 | 同一 clip 每次跑完都是独立行，同配方重跑也两行 |
| D2 | Dataset | 每个已打标 `(clip, run)` 都可入集；X/y 仍必须同一 run |
| D3 | 检索 | 同一 clip 可命中多次（每个匹配的 run 一条） |
| D4 | UI | 去掉「当前生效」；用 run 短 id + 状态区分分支 |
| D5 | Retry | 任意失败/取消的 run 可重试，不限 active 指针 |
| D6 | OMS vs 其它类型 | 工作区仍按 `data_type_id` 隔离；OMS 不因后来的 NVH run 把舱内分支藏起来 |

## 4. 行为

- `_clip_run_pairs_for_data_type`：按 `(clip_id, run_id)` 去重，不再按 `clip_id` 只留最新。
- OMS light list：枚举所有 OMS 合格 `pipeline_run`，不是只看 `dim_clip.active_run_id`。无任何 run 的占位 clip 仍一行。
- 检索 / Dataset / 校核候选：所有带标签的 `(clip, run)`，不按 active 过滤。
- `active_run_id`：worker 仍更新为最新 run，仅作默认打开目标。
- 总览 `rowKey` = `clip_id::run_id`；点击进入 `/clips/{id}?run_id=`。
- batch-stats 本地键为 `clip_id::run_id`（云端仍 `clip_id`，前端先复合键再回退）。

## 5. 验收

- A：同 clip 两 run → 总览两行；OMS 在 NVH 成为 latest 后仍列出舱内 run；Dataset/检索含两条。
- A-E2E：总览行带 `run_id` 进入 Explorer；RunSelector 无「当前生效」。
