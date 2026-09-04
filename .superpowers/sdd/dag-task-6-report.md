# Task 6 Report: 前端 graph 类型 + recipeGraph.ts

**Status:** PASS  
**Commits:** none

## What changed

| File | Change |
|------|--------|
| `hmi/frontend/src/api/types.ts` | Added `GraphNodeType`, `GraphConditionPred`, `GraphCondition`, `RecipeGraphNode`, `RecipeGraphEdge`, `RecipeGraph`; `DataTypeRecipe.graph?` |
| `hmi/frontend/src/utils/recipeGraph.ts` | **Created** — `hydrateGraphFromSteps`, `graphIsLossy`, `recipeGraphFromEditor` |
| `hmi/frontend/src/pages/DataTypeEditorPage.tsx` | Save always sends `graph` via `recipeGraphFromEditor(existingGraph, steps)`; load keeps `existingGraph` when present |

## Behavior

- **hydrateGraphFromSteps**: chain nodes like backend (`source` / `label` / `op` by `card_kind`/`op_id`), `position.y += 96`, append `stage-label` if no label node.
- **graphIsLossy**: true if any node type is `if` / `review` / `export`.
- **Save**: if loaded recipe already has `graph.nodes`, pass through; else hydrate from current steps. PipelineOrchestrator unchanged (Task 7).

## tsc

```text
cwd: hmi/frontend
cmd: cmd /c "npx.cmd tsc -b"
exit: 0
output: (empty — success)
```

## Concerns

- Pass-through of `existingGraph` means step edits on a type that already has graph will **not** refresh graph until Task 7 canvas owns state (by design for this slice).
- Clone path clears graph and re-hydrates from remapped steps on save (avoids stale node keys).
