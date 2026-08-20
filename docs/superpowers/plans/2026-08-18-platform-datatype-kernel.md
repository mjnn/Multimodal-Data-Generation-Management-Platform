# Platform DataType Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the first slice of the platform kernel: operator catalog + recipe validation + two published types (`oms_cabin`, `ivi_ui_stub`) + source/sample/run persistence + preflight + product cache keys + data-type workspace (list → enter) with search isolation.

**Architecture:** HMI local SQLite holds DataType recipes and lake/sample/run records. Operators and view templates are code-registered. Preflight compiles a Sample’s source kinds against the recipe. Existing OMS overview/search/review live inside the `oms_cabin` workspace; `ivi_ui_stub` is a separate empty channel. SDK `CapabilityPlanner` stays the executor; this slice does not rewrite DataWorks.

**Tech Stack:** Python 3.11, FastAPI, SQLite (`app.db`), React + Ant Design, Playwright, unittest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-18-platform-datatype-kernel-design.md`
- Operators in code; DataType is JSON recipe; unknown `op_id` / `overview_view` rejected
- One DataType binds one taxonomy tree (`oms` vs `ivi_ui_stub`, never share)
- Sources enter the lake without a type; runs bind type
- BBox backends: `opencv` | `yolo` only (no `vl`)
- First slice: local HMI + SDK; no DataWorks/MC schema change
- `ivi_ui_stub` must preflight; label stage may be off
- Search/overview/review require a workspace `data_type_id`; no cross-type hits
- Do not commit unless the user asks

---

## File map

| Path | Responsibility |
|------|----------------|
| `hmi/backend/hmi/platform/operators.py` | Operator catalog |
| `hmi/backend/hmi/platform/views.py` | View template ids |
| `hmi/backend/hmi/platform/recipe.py` | Recipe validate + seed recipes |
| `hmi/backend/hmi/platform/preflight.py` | Required-input preflight |
| `hmi/backend/hmi/platform/cache.py` | Product cache key |
| `hmi/backend/hmi/platform/store.py` | SQLite Source/Sample/DataType/Run |
| `hmi/backend/hmi/platform/router.py` | REST API |
| `hmi/backend/hmi/platform/search_scope.py` | Require `data_type_id`; OMS vs IVI isolation |
| `hmi/backend/scripts/test_platform_datatype_kernel.py` | Unit/API tests |
| `hmi/frontend/src/pages/DataTypeHomePage.tsx` | Type list |
| `hmi/frontend/src/context/DataTypeWorkspaceContext.tsx` | Workspace id |
| `hmi/frontend/e2e/datatype-workspace.spec.ts` | A-E2E |

---

### Task 1: Operator catalog + view templates + recipe validation + seeds

**Files:**
- Create: `hmi/backend/hmi/platform/__init__.py`
- Create: `hmi/backend/hmi/platform/operators.py`
- Create: `hmi/backend/hmi/platform/views.py`
- Create: `hmi/backend/hmi/platform/recipe.py`
- Test: `hmi/backend/scripts/test_platform_datatype_kernel.py`

**Interfaces:**
- Produces: `OPERATORS: dict[str, dict]`, `list_operators() -> list[dict]`
- Produces: `VIEW_TEMPLATES = frozenset({"cabin_timeline", "frame_gallery_bbox", "audio_spec_asr", "json_tree"})`
- Produces: `validate_recipe(recipe: dict) -> dict` raises `ValueError`
- Produces: `SEED_RECIPES: dict[str, dict]` with `oms_cabin` and `ivi_ui_stub`

- [ ] **Step 1: Write failing tests** for missing taxonomy_id, unknown op, unknown view, vl detector rejected, seeds valid
- [ ] **Step 2: Implement catalog + validate_recipe + seeds**
- [ ] **Step 3: Run** `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py -v` — pass Task 1 cases

Recipe shape:

```python
{
  "id": "oms_cabin",
  "title": str,
  "purpose": str,
  "owner": str,
  "taxonomy_id": str,          # logical tree id
  "overview_view": str,
  "status": "draft" | "published",
  "require_any_kinds": list[list[str]],  # at least one group fully present
  "preprocess": [{"op_id": str, "when_kind": str | None, "required": bool}],
  "stages": {"label": {"enabled": bool}, "embed": {"enabled": bool}},
  "bbox": {"enabled": bool, "detector": "opencv"|"yolo", "yolo_classes": str},
}
```

`oms_cabin.require_any_kinds = [["rosbag"], ["video"], ["image"], ["audio"]]`  
`ivi_ui_stub.require_any_kinds = [["video"], ["image"]]`  
`ivi_ui_stub.stages.label.enabled = False`

---

### Task 2: Preflight + product cache key

**Files:**
- Create: `hmi/backend/hmi/platform/preflight.py`
- Create: `hmi/backend/hmi/platform/cache.py`

**Interfaces:**
- Produces: `preflight(recipe: dict, source_kinds: list[str]) -> dict` with `ok: bool`, `missing: list[str]`, `ops: list[str]`
- Produces: `product_cache_key(input_ids: list[str], op_id: str, params: dict) -> str`

- [ ] Tests: text-only vs oms_cabin fails; image-only vs ivi_ui_stub ok; same inputs+params same key; param change different key
- [ ] Implement

---

### Task 3: SQLite store + seed published types + ivi taxonomy

**Files:**
- Create: `hmi/backend/hmi/platform/store.py`
- Modify: `hmi/backend/hmi/app_db.py` `ensure_schema` to call `ensure_platform_schema`
- Modify: `hmi/backend/hmi/taxonomy_db.py` — helper to ensure published `ivi_ui_stub` version if missing

**Interfaces:**
- Tables: `platform_source`, `platform_sample`, `platform_sample_source`, `platform_data_type`, `platform_run`, `platform_product`
- `upsert_data_type(recipe)`, `list_data_types()`, `get_data_type(id)`
- `put_source(...)`, `create_sample(source_ids, sample_id=None)`
- `create_run(sample_id, data_type_id, ...)` only if preflight ok
- Seed `oms_cabin` + `ivi_ui_stub` as published

---

### Task 4: REST API + search isolation

**Files:**
- Create: `hmi/backend/hmi/platform/router.py`
- Create: `hmi/backend/hmi/platform/search_scope.py`
- Modify: `hmi/backend/hmi/main.py` include router; `/api/search` and `/api/clips/query` require `data_type_id`

**Interfaces:**
- `GET /api/platform/operators`
- `GET /api/platform/data-types`
- `PUT /api/platform/data-types/{id}` (admin; validate)
- `POST /api/platform/sources`
- `POST /api/platform/samples`
- `POST /api/platform/runs/preflight` body `{sample_id|source_kinds, data_type_id}`
- Search without `data_type_id` → 400
- `oms_cabin` → existing search; `ivi_ui_stub` → empty items; unknown type → 404

---

### Task 5: Frontend workspace shell

**Files:**
- Create: `hmi/frontend/src/pages/DataTypeHomePage.tsx`
- Create: `hmi/frontend/src/context/DataTypeWorkspaceContext.tsx`
- Modify: `hmi/frontend/src/App.tsx` routes
- Modify: `hmi/frontend/src/layouts/AppLayout.tsx` nav + breadcrumbs
- Modify: `hmi/frontend/src/api/index.ts` + `types.ts`
- Modify: `hmi/frontend/src/pages/OverviewPage.tsx` pass `data_type_id`
- Modify: `hmi/frontend/src/components/OverviewClipSearchPanel.tsx` if it calls search
- Modify: `hmi/frontend/e2e/bbox-overlay.spec.ts` goto `/w/oms_cabin`

Routes:
- `/` type list
- `/w/:dataTypeId` overview for that type
- Existing `/clips/:id`, `/review/*` stay; they inherit last workspace from sessionStorage, default `oms_cabin`

---

### Task 6: Playwright A-E2E + acceptance + CURRENT

**Files:**
- Create: `hmi/frontend/e2e/datatype-workspace.spec.ts`
- Create: `project-management/acceptance/PLAT-DTYPE-KERNEL.md`
- Modify: `project-management/CURRENT.md`, `tracking.csv`, `progress-board.md`, `changelog-progress.md`

E2E: login → `/` shows 舱内 OMS and 车机 UI → enter IVI → overview empty/isolated copy → enter OMS workspace still lists clips (or empty local without regression crash)

---

## Spec coverage

| Spec | Task |
|------|------|
| D2 recipe/operators | 1 |
| D3 lake then type | 3–4 |
| D4 one tree per type | 1, 3 |
| D5 three layers | 1–3 |
| D6 workspace search | 4–5 |
| D7 opencv/yolo | 1 |
| A1 unknown op rejected | 1, 4 |
| A2 two runs two types | 3–4 |
| A3 preflight missing | 2 |
| A4 search isolation | 4–5 |
| A5 cache key | 2 (key + store hit skip logged; no full operator re-run required this slice) |
