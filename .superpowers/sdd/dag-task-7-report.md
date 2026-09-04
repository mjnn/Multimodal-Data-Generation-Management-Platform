# Task 7 Report: xyflow 画板替换纵向编排列表

**Status:** PASS  
**Commits:** none

## What changed

| File | Change |
|------|--------|
| `hmi/frontend/package.json` (+ lock) | Installed `@xyflow/react` ^12.11.6 |
| `hmi/frontend/src/utils/recipeGraph.ts` | Added `defaultNewGraph()`, `graphToSteps()` (source/op/label only) |
| `hmi/frontend/src/components/datatype/PipelineDagCanvas.tsx` | Created — ReactFlowProvider + ReactFlow canvas |
| `hmi/frontend/src/components/datatype/PipelineDagCanvas.css` | Canvas + node styles |
| `hmi/frontend/src/components/datatype/ComponentPalette.tsx` | `hideOpIds` + extras (`palette-op-if/review/export/source`) |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | Primary state is `graph`; save sends canvas graph; OverviewComposer kept |
| `hmi/frontend/e2e/platform-dtype-editor.spec.ts` | DAG testids; dropped list Y-order / bind inspector / pipe-step cards |

## Behavior

- **New:** `defaultNewGraph()` — source `src-1` + label `stage-label` + one edge.
- **Load:** `recipe.graph.nodes` if present, else `hydrateGraphFromSteps(steps)`.
- **Save:** PUT body `graph` is the canvas (not stale pass-through). `compileSteps(graphToSteps(graph))` still fills linear slots for a graph-less backend.
- **Canvas:** `data-testid="dag-canvas"`; nodes `dag-node-${key}`; label also `dag-node-label`; no `dag-remove-label`. if node has `then` / `else` handles. Palette add key `op-{opId}-{Date.now()}` at `{x:320, y:80*n}` — not pin-last.
- **Palette:** catalog `palette-op-{op_id}` plus if/review/export/source; hide extra label if one exists.

## Install

```text
cwd: hmi/frontend
cmd: cmd /c "npm.cmd install @xyflow/react"
exit: 0
output:
added 20 packages, and audited 268 packages in 25s
50 packages are looking for funding
  run `npm fund` for details
8 vulnerabilities (1 moderate, 7 high)
To address all issues, run:
  npm audit fix
Run `npm audit` for details.
```

## tsc

```text
cwd: hmi/frontend
cmd: cmd /c "npx.cmd tsc -b"
exit: 0
output: (empty — success)
```

## Playwright

```text
cwd: hmi/frontend
cmd: cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
exit: 0
output:
Running 3 tests using 1 worker
  ok 1 [chromium] › e2e\platform-dtype-editor.spec.ts:4:1 › admin can create draft data type with pipeline component cards (2.6s)
  ok 2 [chromium] › e2e\platform-dtype-editor.spec.ts:40:1 › STFT cannot bind to a video-only slot (6.9s)
  ok 3 [chromium] › e2e\platform-dtype-editor.spec.ts:49:1 › admin can open edit page for oms_cabin (1.7s)
  3 passed (22.5s)
```

## Concerns

- STFT “无兼容输入” bind inspector is **not** covered here (Task 8). The STFT spec only asserts canvas + node create.
- oms_cabin no longer asserts `pipe-step-parse_bag` / bind dropdowns (old card inspector).
- Adding an op does not auto-connect; unconnected ops still save because backend `validate_graph` only requires required sources to reach the label (and exactly one label). Adding **if** without then/else edges would fail PUT — expected.
- `PipelineOrchestrator` is unused by the editor but left in the tree (OverviewComposer still imports its CSS).
