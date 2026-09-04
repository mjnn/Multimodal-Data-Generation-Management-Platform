### Task 4: 编辑器 UI — 去掉槽位表，混排数据源卡

**Files:**
- Create: `hmi/frontend/src/components/datatype/PipelineSourceCard.tsx`
- Modify: `PipelineOrchestrator.tsx`、`PipelineStepCard.tsx`、`DataTypeEditorPage.tsx`

**Interfaces:**
- `PipelineSourceCard` props：`step, index, total, onChange, onMove, onRemove`
- `PipelineOrchestrator` **删除 `slots` prop**；从 `steps` 推导；顶部按钮 `data-testid="pipe-add-source"` 调用 `newSourceCard({ key: \`src-${Date.now()}\`, title: '数据源', kinds: ['.mp4'] })` **插入到列表开头**（或当前选中项之上；默认开头）
- `DataTypeEditorPage`：删除「源槽位」Card / `Form.List`；`buildRecipe` 用 `compileSteps(steps)` 的 `slots` + preprocess，不再读 `values.slots`
- `EditorForm` 去掉 `slots`
- 算子卡产出芯片：显示 `output_labels[t] || typeLabel(t)`；parse_bag 旁加可选「显示名」输入仅对当前 produces（可先只做 frames 一行 Input，避免范围膨胀：每个 chip 旁小 Input）

`PipelineSourceCard` 最小字段：title、kinds（多选 catalog suffixes）、min/max、required。

`remove` 时同时清掉 `bindings.kind==='slot' && slot_id===gone`。

- [ ] **Step 1:** 实现 Source 卡 + Orchestrator 加源按钮 + 按 `card_kind` 渲染 Source vs Step

- [ ] **Step 2:** 拆掉 Editor 槽位表单；保存走 compile 出的 slots

- [ ] **Step 3:** `cmd /c "npx.cmd tsc -b --pretty false"` 于 `hmi/frontend`

- [ ] **Step 4: Commit**（仅当用户要求）

---

