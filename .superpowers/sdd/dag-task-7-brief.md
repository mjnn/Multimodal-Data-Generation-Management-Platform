### Task 7: xyflow 画板替换纵向编排列表

**Files:**
- Modify: `hmi/frontend/package.json` via `cmd /c "npm.cmd install @xyflow/react"` in `hmi/frontend`（禁止裸 `npm`）
- Create: `hmi/frontend/src/components/datatype/PipelineDagCanvas.tsx`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`（用画布替换 `PipelineOrchestrator` 的算子列表；源仍可从 palette 加 source 节点）
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`（testid 改为 DAG）

**Interfaces:**
- Canvas `data-testid="dag-canvas"`
- Palette: keep `palette-op-{op_id}`；add `palette-op-if`, `palette-op-review`, `palette-op-export`
- Nodes: `data-testid="dag-node-{key}"`；label node `dag-node-label` (also `dag-node-{labelKey}`)
- Label has no delete control (`dag-remove-label` count 0)
- Adding an op inserts a node **not** pinned last; user connects edges
- Default new recipe: one source node + one label node + one edge（`defaultNewGraph()`）

- [ ] **Step 1: Install**

working_directory: `hmi/frontend`  
`cmd /c "npm.cmd install @xyflow/react"`

- [ ] **Step 2: Minimal canvas**

`PipelineDagCanvas` wraps `ReactFlowProvider` + `ReactFlow`. Map `RecipeGraph.nodes` to xyflow nodes (`id=key`, `position`, `data={{ type, title, op_id }}`). Edges: xyflow `sourceHandle=source_port`, `targetHandle=target_port`. if node renders two handles `then` / `else` at the bottom.

On connect: append edge with `source_port` from handle id (`out`/`then`/`else`).

Palette click: append node with new key `op-{opId}-{Date.now()}`, position `{x: 320, y: 80 * nodes.length}`. Label cannot be added twice (palette label hidden if one exists). Label cannot be removed in `onNodesChange`.

Replace `PipelineOrchestrator` on the editor page with `PipelineDagCanvas`. Keep `OverviewComposer` below.

Delete or stop calling `pinLabelLast` from the editor path.

- [ ] **Step 3: Update Playwright**

Rewrite the first spec:

- `getByTestId('dag-canvas')` visible
- `palette-op-if` visible
- `dag-node-label` visible
- `dag-remove-label` count 0
- clicking `palette-op-mel_spectrogram` creates a node `dag-node-` matching `/mel_spectrogram/`
- save still works
- reopen: graph nodes still there (`dag-node-label` visible)

Remove assertions that mel Y < label Y in a **list**. Optionally: after add, both nodes exist.

STFT bind test: inspector opens on select; if too heavy for this task, keep a skip and cover bind in Task 8. Prefer: selecting the STFT node shows inspector `dag-inspector` with bind control `pipe-bind-stft_spectrogram-in` reused.

oms_cabin edit: `dag-canvas` + `dag-node-label`.

- [ ] **Step 4: tsc + playwright**

```
cmd /c "npx.cmd tsc -b"
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
```

working_directory: `hmi/frontend`  
Expected: tsc PASS; playwright 3/3 (or updated count) PASS

---

