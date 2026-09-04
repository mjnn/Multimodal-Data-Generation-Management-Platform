### Task 6: 前端 graph 类型 + `recipeGraph.ts`

**Files:**
- Modify: `hmi/frontend/src/api/types.ts`
- Create: `hmi/frontend/src/utils/recipeGraph.ts`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`（load/save `graph`）

**Interfaces:**
- `RecipeGraphNode`, `RecipeGraphEdge`, `RecipeGraph` on `DataTypeRecipe.graph?`
- `hydrateGraph(recipe)`, `graphIsLossy(graph)`, mirror backend enough for the editor (positions + types). **Do not reimplement validate in the browser as the source of truth**; still POST and show backend `ValueError`. Client-side: refuse delete label locally.

- [ ] **Step 1: Add types**

```ts
export type GraphNodeType = 'source' | 'op' | 'if' | 'label' | 'review' | 'export'

export type GraphConditionPred = { field: string; op: string; value?: unknown }
export type GraphCondition = { all: GraphConditionPred[] }

export type RecipeGraphNode = {
  key: string
  type: GraphNodeType
  op_id?: string
  title: string
  params?: Record<string, unknown>
  position: { x: number; y: number }
  condition?: GraphCondition
}

export type RecipeGraphEdge = {
  id: string
  source: string
  source_port: string
  target: string
  target_port: string
}

export type RecipeGraph = { nodes: RecipeGraphNode[]; edges: RecipeGraphEdge[] }
```

Attach `graph?: RecipeGraph` to `DataTypeRecipe`.

`recipeGraph.ts`: implement `hydrateGraphFromSteps(steps: PipelineStep[]): RecipeGraph` (same chain rules as backend Task 3) and `graphIsLossy`.

- [ ] **Step 2: `cmd /c "npx.cmd tsc -b"`** in `hmi/frontend`  
Expected: FAIL until DataTypeRecipe usages compile (optional graph is fine). After adding types, PASS.

- [ ] **Step 3: Wire editor save**

In `DataTypeEditorPage`, keep `steps` until Task 7. After Task 7, `graph` is the state. For this task only: on save, if `recipe.graph` exists send it through; if not, `hydrateGraphFromSteps(steps)` and include in PUT body. Backend Task 5 already projects.

- [ ] **Step 4: tsc PASS**

---

