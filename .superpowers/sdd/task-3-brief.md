### Task 3: 前端类型 + recipePipeline 镜像

**Files:**
- Modify: `hmi/frontend/src/api/types.ts`
- Modify: `hmi/frontend/src/utils/recipePipeline.ts`
- Test: 无独立 jest；用 `npx.cmd tsc -b`

**Interfaces:**
- `PipelineStep` 增加：`card_kind?: 'source' | 'op'`；`title?: string`；`kinds?: string[]`；`cardinality_min?: number`；`cardinality_max?: number`；`output_labels?: Record<string, string>`
- `DataTypeSlot` 增加 `title?: string`
- `DataTypePreprocessStep` 增加 `output_labels?: Record<string, string>`
- 镜像：`isSourceCard`、`newSourceCard`、`slotsFromSteps`、`hydrateRecipeToSteps` 前置 source 卡、`compileSteps` 返回 `slots`、`typeLabel(t, labels?)` 优先 `labels[t]`

- [ ] **Step 1:** 改 `types.ts`（先改类型，tsc 可能仍过，因为字段可选）

- [ ] **Step 2:** `recipePipeline.ts` 实现与 Task 2 同名逻辑；`bindingOptions` 把 `upstream` 里的 source 卡当成槽位，label = `title`；算子产物 label = `${op.title} · ${step.output_labels?.[name] || typeLabel(name)}`

- [ ] **Step 3:** `cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"` — 退出码 0

- [ ] **Step 4: Commit**（仅当用户要求）

---

