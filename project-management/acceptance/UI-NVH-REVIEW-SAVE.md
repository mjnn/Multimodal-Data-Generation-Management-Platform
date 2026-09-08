# UI-NVH-REVIEW-SAVE · 语义 L6 人工写回 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-NVH-REVIEW-SAVE · 语义 L6 人工写回 |
| 日期 | 2026-09-04 |
| 环境前置 | A-E2E 需本机后端 `:8000` + Playwright preview `:4175`；先 `py -3 hmi/backend/scripts/seed_nvh_review_e2e_clip.py` |
| Agent 自动化摘要 | 校核保存只写回 `nvh.sem.*` 到 `fact_clip_label` + `nvh_labels.json`；客观叶子不动；勿 publish `audio_nvh-v2`；Explorer 仅 L6 显示快速校核 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · L6 writeback 不覆盖客观叶子

**操作步骤**
1. `py -3 hmi/backend/scripts/test_nvh_review_save.py`

**期望结果**
- `quality_grade` 写回为 A，`leq_db_mean` 仍为 94.5
- OMS `values` 载荷 noop
- rollup 只计 `nvh.sem.*`；`audio_nvh-v2` 仍为 draft

**通过判断标准**
- unittest 3/3

**执行记录**
- 通过（2026-09-04）：`Ran 3 tests … OK`

#### A-2 · 既有 field review rollup 回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_review_m61.py`

**期望结果**
- OMS 两字段校核仍可 rollup 到 `reviewed`

**执行记录**
- 通过（2026-09-04）：`All M6.1 checks passed.`

#### A-3 · 前端 TypeScript

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b --pretty false`

**期望结果**
- exit 0（顺手收口 `DagNodeInspector` union 上误读 `description`）

**执行记录**
- 通过（2026-09-04）：`tsc -b && vite build --mode e2e` 成功

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · NVH 标签树仍在；无 raw rail

| 脚本/Spec | `hmi/frontend/e2e/nvh-label-tree.spec.ts` |

**操作步骤**
1. 本机 API `HMI_DATA_SOURCE=local` 在 `:8000`
2. `py -3 hmi/backend/scripts/seed_nvh_review_e2e_clip.py`
3. `cd hmi/frontend && npm.cmd run build -- --mode e2e && npm.cmd run preview -- --mode e2e --host 127.0.0.1 --port 4175`
4. `npx.cmd playwright test e2e/nvh-label-tree.spec.ts`（`PLAYWRIGHT_SKIP_WEBSERVER=1` `PLAYWRIGHT_BASE_URL=http://127.0.0.1:4175`）

**期望结果**
- 先进入 `/w/audio_array_spec` 再打开 clip
- `data-testid=audio-nvh-label-tree` 可见
- `audio-nvh-label-rail` 不存在

**通过判断标准**
- Playwright 该用例通过

**执行记录**
- 通过（2026-09-04）：chromium 2.8s

#### A-E2E-2 · L6 快速校核写回后树与 API 可见，客观叶子仍在

| 脚本/Spec | `hmi/frontend/e2e/nvh-label-tree.spec.ts` |

**操作步骤**
1. 同上环境
2. 展开标签树；客观 `nvh.clip.spl.leq_db_mean` 无「快速校核」
3. 打开 `nvh.sem.quality_grade` 快速校核，改档并「完成本标签校核」

**期望结果**
- 树值变为新档
- `GET /api/clips/.../audio-nvh` 的 `labels.nvh.sem.quality_grade` 为新档
- `nvh.clip.spl.leq_db_mean` 仍存在

**通过判断标准**
- Playwright 该用例通过

**执行记录**
- 通过（2026-09-04）：chromium 6.1s；suite **2/2 (9.3s)**

---

## 二、人工签字 / 主观（H · 可选）

无。可脚本化 UI 已用 A-E2E。

---

## 三、不在本工单范围

- **publish** `audio_nvh-v2`
- HMI 在线 H-2
- DataWorks / DPE
- `text_to_json` capability

---

## 四、点测结论

- [x] A / A-E2E — 可标 done
