# Source Unit Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans (inline). Steps use checkbox syntax.

**Goal:** Let operators group lake files into reusable data units and lock multi-slot pipeline bind (audio_defect, oms_cabin) to one unit.

**Architecture:** New `platform_source_unit` + member tables (M:N). Sample stays internal. `collection_id` stays upload-batch only. Run bind requires `unit_id` when a recipe has ≥2 slots **and** the run fills ≥2 slots, or when ≥2 slots are required.

**Tech Stack:** FastAPI, SQLite `app.db`, React/Ant Design, Playwright. Windows: `py -3`, `npx.cmd`.

## Global Constraints

- Do not change DataWorks; do not publish `audio_nvh-v2`
- POST units only in local mode (same as `POST /sources`)
- Unit delete does not delete `platform_source` rows
- Min 2 members per unit

---

### Task 1: Store + run constraint

**Files:**
- Create: `hmi/backend/hmi/platform/source_unit.py`
- Create: `hmi/backend/scripts/test_source_units.py`
- Modify: `hmi/backend/hmi/platform/store.py`, `router.py`

**Tests:** `py -3 hmi/backend/scripts/test_source_units.py`

---

### Task 2: Lake + run-bind UI

**Files:**
- Modify: `hmi/frontend/src/api/types.ts`, `index.ts`, `LakeManagePage.tsx`, `LakeRunBindPanel.tsx`
- Modify: `hmi/frontend/e2e/platform-lake.spec.ts`

**Tests:** `npx.cmd playwright test e2e/platform-lake.spec.ts`

---

### Task 3: Baseline types + acceptance

`oms_cabin` and `audio_defect` use unit UX (`len(slots) >= 2`). Single-slot `ivi_ui_stub` / `audio_array_spec` unchanged. Write `acceptance/PLAT-SOURCE-UNIT.md`.
