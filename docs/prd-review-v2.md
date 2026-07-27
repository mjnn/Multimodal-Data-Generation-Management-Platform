# PRD 增补 — 校核页 v2（逐标签 · 双模式）

| 字段 | 内容 |
|------|------|
| 版本 | **v0.3 增补**（基于 PRD v0.2） |
| 状态 | 缺口评审完成，**P0=0**，可进入 M6 实施 |
| 基线 | M3 校核能力 + M5 出口 |
| 用户决议 | 2026-07-23 澄清问卷 |

---

## 1. 背景与动机

M3 校核为「队列列表 → 详情页全量表单」，校核员需在单页编辑全部 OMS 标签，认知负担高、与「先聚焦场景再快判」的工作流不符。

**目标**：替换为**单页双模式**校核工作台，以 **clip + 单 label_id** 为最小校核单元，支持快速连审。

---

## 2. In / Out

### In

| # | 能力 |
|---|------|
| I1 | **AI 分歧校核**：系统自动排队；优先空值标签，其次 AI 分歧标签 |
| I2 | **全面校核**：校核员从已发布标签树选定 **label_id + 枚举/字符串值**；仅展示 AI 当前值 = 所选值的 clip，逐条快审 |
| I3 | 单页布局：上标签搜索/筛选，下 clip 卡片（类数据总览）+ 操作按钮 |
| I4 | 四按钮：**符合** / **修正**（枚举下拉、字符串输入）/ **不确定** / **上一个** |
| I5 | 任一操作提交即完成该 **(clip, run, label_id)** 校核并自动跳下一条 |
| I6 | **不确定** → 该 label 值置空 + 标记 `human_doubtful` |
| I7 | 完全替换旧校核 UI（队列 + 详情全表单） |

### Out

| # | 不做 |
|---|------|
| O1 | 帧级校核 |
| O2 | 同屏多标签编辑 |
| O3 | 保留旧校核页为并行入口 |
| O4 | 不确定标签自动触发 Job3 重跑 |

---

## 3. 双模式定义

### 3.1 模式 A · AI 分歧校核

**入口**：`/review` 默认 Tab「AI 分歧校核」。

**任务来源**：全库有 AI clip 标签且存在以下任一情况的 `(clip_id, run_id, label_id)`：

1. **P0 优先**：`labels_json[label_id]` 为空 / null（未达 AI 合并阈值或 gate 留空）
2. **P1 次之**：`label_consensus[label_id]` 标记分歧（`needs_review` 或 status ∈ split/minority/tie）

**排序**：

```text
priority_bucket (空值=0, 分歧=1)
→ dispute_count desc（clip 级）
→ clip_dir_name asc
→ label_id asc
```

**跳过**：已在 `clip_label_field_review` 中存在记录的 `(clip, run, label)` 不再入队。

### 3.2 模式 B · 全面校核

**入口**：同页 Tab「全面校核」。

**前置**：校核员在顶部标签搜索框从**已发布 taxonomy** 选定 **label_id + value**（枚举走下拉，字符串走输入）。

**任务来源**：AI `labels_json[label_id] == 所选 value` 的 clip，且该 `(clip, run, label)` **尚未 field-review**。

**排序**：`clip_dir_name asc` → `clip_id asc`。

**UX**：校核员心中已有场景假设（如「上午 + 城市」），对照 clip 卡片判断 AI 打标是否符合。

---

## 4. 单条校核交互

| 按钮 | 行为 | 写入 |
|------|------|------|
| **符合** | 接受 AI 当前值 | `action=confirm`, `value=ai_value` |
| **修正** | 弹出/内联编辑器 | `action=correct`, `value=用户输入` |
| **不确定** | 人工无法判定 | `action=uncertain`, `value=null`, `human_doubtful=true` |
| **上一个** | 回到会话内上一条已审任务（只读预览，可重新提交覆盖） | — |

提交成功后：

1. UPSERT `clip_label_field_review`
2. 合并更新 `clip_label_review.labels_json`（该 label 键）
3. 若该 clip 所有「需校 label」均已 field-review → `clip_label_review.review_status=reviewed`
4. 前端自动加载下一条任务

---

## 5. 数据模型

### 5.1 新表 `clip_label_field_review`

| 列 | 类型 | 说明 |
|----|------|------|
| id | TEXT PK | uuid |
| clip_id | TEXT | |
| run_id | TEXT | |
| label_id | TEXT | 如 `L1.1.day_period` |
| taxonomy_version_id | TEXT FK | 校核时 published 版本 |
| action | ENUM | `confirm` \| `correct` \| `uncertain` |
| value_json | TEXT | 最终值 JSON；uncertain 为 `null` |
| human_doubtful | INT | 0/1；uncertain 时为 1 |
| ai_value_json | TEXT | 提交时 AI 原值快照 |
| reviewer_id | TEXT FK | |
| reviewed_at | TEXT ISO8601 | |
| UNIQUE(clip_id, run_id, label_id) | | |

### 5.2 与 `clip_label_review` 关系

- **保留** clip 级表作为 dataset y 导出载体（R-M6-3）
- field review 提交时 **增量 merge** 到 `labels_json`
- `review_status`：
  - 默认 `pending_review`
  - 当 clip 的全部 AI 产出 label 键均已有 field review → `reviewed`
  - 管理员可 `reopen` 清空 field reviews 或整 clip 打回（沿用 M3 API，扩展行为）

### 5.3 审计

`audit_log.action` 新增 `clip.label_field_review`，含 clip_id / label_id / action。

---

## 6. API 草案（`/api/review/v2/*`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/review/v2/session` | 当前模式、进度（remaining/total）、上一条指针 |
| GET | `/review/v2/next` | 取下一条任务；query: `mode`, `label_id`, `value`, `cursor` |
| GET | `/review/v2/prev` | 会话内上一条（含已提交结果） |
| GET | `/review/v2/tasks/stats` | 各模式待审数量 |
| POST | `/review/v2/submit` | body: `{clip_id, run_id, label_id, action, value?, updated_at?}` |
| GET | `/review/v2/label-options` | 已发布 taxonomy 可搜 label + 枚举值（全面校核用） |

**任务 payload**（next/prev）：

```json
{
  "clip_id": "sha256:demo_morning_city",
  "run_id": "...",
  "label_id": "L1.1.day_period",
  "label_name": "时段",
  "ai_value": null,
  "value_schema": { "type": "enum", "values": ["morning","afternoon","night"] },
  "human_doubtful": false,
  "clip_card": { "...": "同 Overview 轻量字段 + anchor 图" },
  "position": { "index": 3, "total": 28 }
}
```

---

## 7. 页面 IA

**路由**：`/review`（单页，替换原 `/review` + `/review/:clipId`）

```text
┌─────────────────────────────────────────────┐
│ [AI 分歧校核] [全面校核]     待审 28 · 已审 5 │
├─────────────────────────────────────────────┤
│ 标签搜索 [L1.1.day_period ▼] [morning ▼]    │  ← 全面校核模式显示
├─────────────────────────────────────────────┤
│  Clip 卡片（缩略/时间轴/label_preview）       │
│  当前标签：时段 · AI 值：morning              │
├─────────────────────────────────────────────┤
│ [符合] [修正▾] [不确定]        [← 上一个]   │
└─────────────────────────────────────────────┘
```

- **修正**：枚举 → Select；字符串/数字 → Input
- 全面校核未选 label+value 时，下方展示 Empty + 引导

---

## 8. 缺口评审

| ID | 级别 | 维度 | 问题 | 决议 |
|----|------|------|------|------|
| G-M6-1 | P0 | 实体 | 校核粒度从 clip 变 label | **R-M6-1** 新表 `clip_label_field_review` |
| G-M6-2 | P0 | 状态机 | clip 何时 reviewed | **R-M6-2** AI 产出 label 键全部 field-review 后自动 reviewed |
| G-M6-3 | P0 | 真相来源 | dataset y 从哪读 | **R-M6-3** 仍以 `clip_label_review.labels_json` 为准，由 field review 合并写入 |
| G-M6-4 | P0 | 权限 | 角色 | 沿用 admin/reviewer；API `require_reviewer` |
| G-M6-5 | P0 | 异常 | 并发 field review | **R-M6-4** UNIQUE + 409；clip 级 `updated_at` 乐观锁保留 |
| G-M6-6 | P1 | Taxonomy | 全面校核枚举来源 | 已发布版本 `value_schema` |
| G-M6-7 | P1 | UX | 上一个是否可改判 | 允许重新 submit 覆盖 field review |
| G-M6-8 | P2 | 统计 | 存疑 label 报表 | backlog，M6 不做 |

**P0=0** ✓

---

## 9. 验收标准

### 正向

- [ ] **V1** AI 分歧模式：demo_morning_city 的 `day_period` 空值任务优先于 demo_holiday_mall 分歧任务
- [ ] **V2** 全面校核：选 `day_period=morning` 仅出现 AI 值为 morning 的 clip
- [ ] **V3** 点「符合」后自动跳下一条；DB 有 field review 记录
- [ ] **V4** 「不确定」后该 label 在 labels_json 为空且 human_doubtful=1
- [ ] **V5** clip 全部 label field-review 后 review_status→reviewed
- [ ] **V6** dataset 导出 y 含修正/空值结果
- [ ] **V7** 旧 `/review/:clipId` 路由重定向或 404，菜单仅新页

### 负向

- [ ] **N1** model_trainer 调用 submit → 403
- [ ] **N2** 全面校核未选 value 时 next → 422
- [ ] **N3** 重复 submit 同 (clip,label) 无 UNIQUE 冲突处理 → 409

---

## 10. 里程碑

纳入 **M6 · 校核页 v2**，工单见 `docs/m6-implementation-notes.md`。
