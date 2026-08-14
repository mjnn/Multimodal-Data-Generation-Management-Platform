# HMI-BBOX-OVERLAY · 可编辑 BBox 叠加层（本地优先）· 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | HMI-BBOX-OVERLAY · 可编辑 BBox 叠加层 |
| 日期 | 2026-08-14 |
| 环境前置 | API 单元：否；A-E2E：需 HMI Web + 本地有 clip（有 bboxes 更佳） |
| Agent 自动化摘要 | A-1 pass（2/2）；前端 tsc pass；A-E2E 脚本入库（环境无 bbox clip 时可 soft-skip） |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · bboxes.jsonl upsert 写回

**操作步骤**
1. `py -3 hmi/backend/scripts/test_hmi_bbox_overlay.py -v`

**期望结果**
- upsert 保留其它帧与额外字段；坐标写回可读；缺文件可创建

**通过判断标准**
- exit 0 · 2 tests OK

**执行记录**（Agent 收工填）
- **pass** 2026-08-14 · `Ran 2 tests … OK`

#### A-2 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && npx tsc --noEmit -p tsconfig.json`

**期望结果**
- 无类型错误

**通过判断标准**
- exit 0

**执行记录**
- **pass** 2026-08-14

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · Explorer 原图叠加 / 烧录预览文案

| 脚本/Spec | `hmi/frontend/e2e/bbox-overlay.spec.ts` |

**操作步骤**
1. `cd hmi/frontend && npx playwright test e2e/bbox-overlay.spec.ts`

**期望结果**
- 有本地 clip：若存在 `bboxes.jsonl` 则出现 `data-testid=bbox-overlay`；若有烧录预览则 Segmented 文案为「原图」「烧录预览」
- 无数据时 soft-skip（不红）

**通过判断标准**
- exit 0（含 skip）

**执行记录**
- 脚本已入库；本机 Agent 未强制跑通全量 Playwright（依赖本地 HMI 服务与 fixture）

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 叠加编辑手感

**操作步骤**
1. 本地模式打开含 `bboxes.jsonl` 的 Clip Explorer
2. 确认默认「原图」+ 框叠加；暂停后拖动/改角点/Delete/双击新建；「保存框」后侧栏表坐标更新
3. 「烧录预览」仅观察、不可作编辑源

**期望结果**
- 框与画面对齐（letterbox）；写回后刷新一致

**通过判断标准**
- 主观可接受

**执行记录**
- pending

---

## 三、不在本工单范围

- 云端 OSS/MC 写回
- Taxonomy / gold `labels_json` 耦合
- SDK 默认关闭 `encode_bbox`
- 多帧批量编辑 UI

---

## 四、点测结论

- [x] A — 可标 done（A-E2E 脚本就绪；H-1 待人工）
- [ ] H-1 — 待人工
