# Task 6 Report · 开跑 assignments API

**工单:** UI-DTYPE-SOURCE-NODES  
**分支:** feat/platform-datatype-kernel  
**日期:** 2026-09-02  
**Status:** DONE

## Summary

Assignments API for `POST /api/platform/runs` was already present in the uncommitted working tree (Tasks 1–5 context). Verified against brief: tests + `validate_source_assignments` + `create_run_from_sources(..., assignments=)` + router wiring. No TDD rewrite of passing tests; no implementation gaps vs brief. All three test suites green. No commit.

## Brief vs working tree

| Brief item | Status | Location |
|------------|--------|----------|
| `validate_source_assignments(recipe, assignments, *, source_kind_by_id)` | Present | `hmi/backend/hmi/platform/run_bind.py` |
| required slots / kind ∈ slot.kinds / min–max / no duplicate source_id | Present | same |
| `create_run_from_sources(..., assignments=None)` multi-slot → `assignments required` | Present | `hmi/backend/hmi/platform/store.py` |
| single-slot bare `source_ids` auto-wraps into sole slot | Present | same |
| Router optional `assignments` on `POST /runs` | Present | `hmi/backend/hmi/platform/router.py` (`RunIn`, `SlotAssignmentIn`) |
| Brief Step 1 tests | Present (+ wrong-kind / duplicate extras) | `hmi/backend/scripts/test_platform_lake_run_bind.py` |
| Slot id `audio_primary` | Matches seed | `SEED_RECIPES["audio_array_spec"]["slots"][0]["id"]` |

**TDD:** Tests already existed and passed → no RED→GREEN rewrite. No missing brief assertions.

## Behavior verified

1. `oms_cabin` without assignments → `ValueError` containing `"assignments"`
2. `audio_array_spec` bare `source_ids` still creates a run
3. Explicit `assignments=[{"slot_id": "audio_primary", ...}]` maps wav → `run["source_ids"]`
4. Wrong kind (video into `audio_primary`) and duplicate `source_id` across slots rejected

## Test evidence (this run)

| Suite | Command | Result |
|-------|---------|--------|
| lake-run bind | `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py` | **9/9** · `Ran 9 tests in 6.100s OK` |
| editor regression | `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` | **23/23** · `Ran 23 tests in 4.272s OK` |
| kernel regression | `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py` | **19/19** · `Ran 19 tests in 3.705s OK` |

## Self-review

- No DataWorks changes
- Did not publish `audio_nvh-v2`
- Did not revert Tasks 1–5 working-tree features
- No git commit (user forbade)

## Commits

None.

## Concerns

None. Implementation was pre-landed in the working tree; this task was verification + report only.

---

## Review fix · preflight source_ids alignment (2026-09-02)

**Finding:** `POST /api/platform/runs/preflight` with bare `source_ids` (no `assignments`) did not auto-wrap into the sole slot / raise for multi-slot the way `create_run_from_sources` does.

**Fix:** Extracted `resolve_run_source_bindings` in `run_bind.py`; both `create_run_from_sources` and `api_preflight` use it.

**Command:**
```text
py -3 hmi/backend/scripts/test_platform_lake_run_bind.py
```

**Output:**
```text
Ran 10 tests in ~6.5s
OK
EXIT=0
```

**Files changed:**
- `hmi/backend/hmi/platform/run_bind.py` — add `resolve_run_source_bindings`
- `hmi/backend/hmi/platform/store.py` — `create_run_from_sources` calls shared helper
- `hmi/backend/hmi/platform/router.py` — `api_preflight` uses shared helper for `assignments` / `source_ids`
- `hmi/backend/scripts/test_platform_lake_run_bind.py` — `test_preflight_bare_source_ids_require_assignments_for_multi_slot`
- `.superpowers/sdd/task-6-report.md` — this append

No DataWorks changes. Did not publish `audio_nvh-v2`. No git commit.
