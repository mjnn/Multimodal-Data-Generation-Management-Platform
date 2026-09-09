# PLAT-SOURCE-UNIT · 源湖数据单元 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 规格：`docs/superpowers/specs/2026-09-08-source-unit-design.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-SOURCE-UNIT · 入湖后手动成组；多槽开跑锁同一单元 |
| 日期 | 2026-09-08 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` local + Playwright preview `:4175` |
| Agent 自动化摘要 | 新表 `platform_source_unit`；`audio_defect` 必须选单元；`oms_cabin` 填 ≥2 槽才必须；单槽 `ivi_ui_stub` / `audio_array_spec` 不变 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 数据单元 CRUD + 开跑约束

**操作步骤**
1. `py -3 hmi/backend/scripts/test_source_units.py`

**期望结果**
- 同一 wav 可加入两个单元
- `audio_defect` 无 `unit_id` → `SOURCE_UNIT_REQUIRED`
- `oms_cabin` 只填一个槽可不带单元；填两个槽必须同单元；跨单元 → `SOURCE_UNIT_MISMATCH`
- `audio_array_spec` 单槽无单元仍可开跑
- 种子：`oms_cabin` / `audio_defect` 走单元 UX；`ivi_ui_stub` / `audio_array_spec` 不走

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-08：`Ran 5 tests in 5.067s OK`

#### A-2 · 前端类型检查

**操作步骤**
1. 在 `hmi/frontend`：`cmd /c "npx.cmd tsc -b --pretty false"`

**期望结果**
- 无错误

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-08：`tsc -b` 退出码 0

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · 源湖组成单元 + audio_defect 开跑自动填槽

| 脚本/Spec | `hmi/frontend/e2e/platform-lake.spec.ts` |

**操作步骤**
1. 在 `hmi/frontend`：`cmd /c "npx.cmd playwright test e2e/platform-lake.spec.ts"`

**期望结果**
- 既有 nvh / ivi / 产物血缘用例仍绿
- 入湖 wav+json → 组成单元 → `lake-unit-row`
- 管线管理选 `audio_defect`：单元列表；点选后槽位自动填；单元外 wav 不出现；预检通过

**通过判断标准**
- Playwright 全绿

**执行记录**
- 2026-09-08：**6 passed (29.9s)**，含新用例 `lake compose unit then audio_defect bind auto-fills slots from that unit`

---

## 二、人工签字 / 主观（H · 可选）

本工单无 H 项。

---

## 三、不在本工单范围

- 上传瞬间按文件名自动配对
- 把 Sample 做成用户可编辑对象
- 改 DataWorks / publish `audio_nvh-v2`
- 云模式 POST 单元

---

## 四、点测结论

- [x] A / A-E2E 全绿 — 可标 done
