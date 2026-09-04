# SDD Progress Ledger

Branch: feat/ui-dtype-source-nodes (work in place; dirty tree)
Plan: docs/superpowers/plans/2026-09-03-dtype-dag-canvas.md
Started: 2026-09-03
Base: 145db06 (HEAD at start; no commits unless user asks)

Prior plan (2026-09-02-datatype-source-nodes) Tasks 1–8 complete — archived in this file's previous version / git log. Do not re-dispatch those.

## UI-DTYPE-DAG-CANVAS

Task 1: complete (no commit; recipe_graph.py + test_platform_recipe_graph.py 12/12; review Approved after join/review-order fix). Minor: nested XOR false-reject; unused keys arg; no positive export-after-label test. Condition whitelist deferred to Task 2.
Task 2: complete (no commit; graph_expr.py + validate_graph wiring; 18/18; review Approved). Minor: no validate_graph E2E for pre-label labels.* reject.
Task 3: complete (no commit; hydrate_graph; 20/20; review Approved). Minor: no dedicated stage-label fallback test.
Task 4: complete (no commit; project_graph + graph_is_lossy; transcribe; 22/22; review Approved). Minor: leftover audio_asr in xor test; no embed/bbox flag assertions.
Task 5: complete (no commit; validate_recipe graph project; ivi label on; labels_tree inject; pin_label_last append-only; graph 24 / editor 26 / kernel 19; review Approved). Minor: weak pin order assert; inject skips _normalize_card.
Task 6: complete (no commit; RecipeGraph types + recipeGraph.ts + save graph; tsc pass; review Approved). Minor: copy-from-type doesn't clear existingGraph; graphIsLossy unused until Task 8.
Task 7: complete (no commit; PipelineDagCanvas xyflow; defaultNewGraph; e2e 3/3; tsc 0; review Approved). Minor: clone/?from= still hydrates from steps (drops DAG topology); OverviewComposer sits above canvas.
Task 8: complete (no commit; DagNodeInspector + dag-cloud-hint/lossy; remapGraphKeys clone; tsc 0; e2e 3/3; review Approved). Minor: clone skips attachStepBindings; no e2e for dag-cloud-lossy (Task 12).
Task 9: complete (no commit; ensureLabelsTree + composer lock + runtime labels_json pre; tsc 0; e2e 3/3; review Approved). Minor: locked card still drag-reorderable.
Task 10: complete (no commit; execute_graph + fake adapters; graph_runtime 4/4; recipe_graph 24/24; review Approved). Minor: missing-else no-op unused under validate.
Task 11: complete (no commit; assert_runnable_locally + worker recipe_req branch + get_or_create_review; graph_runtime 8/8; review Approved). Minor: preview twice; ValueError from validate_graph not marked sdk_infer.
Task 12: complete (no commit; Playwright if-after-save + dag-cloud-lossy; acceptance/UI-DTYPE-DAG-CANVAS.md; 四件套; review Approved). A: recipe_graph 24/24, graph_runtime 8/8, editor 26/26, kernel 19/19, tsc 0. A-E2E: editor 3/3 (13.3s). Guard: ASR/label if still RuntimeError. Next: UI-NVH-REVIEW-SAVE.

---
