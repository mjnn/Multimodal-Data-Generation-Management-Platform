# Final whole-branch review fix · UI-DTYPE-SOURCE-NODES

**工单:** UI-DTYPE-SOURCE-NODES（review findings）  
**日期:** 2026-09-03  
**Status:** DONE  
**Git:** no commit (user forbade)

## Fixes

1. **Critical — `require_any_kinds` singleton groups**  
   Preflight ANDs kinds inside a group. Seeds use `singleton_kind_groups` so one `.wav` / `.mp4` works. `compile_steps` / `compileSteps` had been emitting each required slot’s full kinds list as one group, so editor save made a single file fail.  
   Now emit one group per kind (`singleton_kind_groups` / frontend equivalent).

2. **Important — unique `addSource` titles**  
   Second add was always titled `数据源` → save 400 `duplicate slot title`.  
   `nextSourceTitle` now yields `数据源`, `数据源 2`, …

3. **Important — strip `output_labels` to current `produces`**  
   Compile (backend + frontend) drops labels whose ports are no longer produced. Unchecking 连续帧 also strips `output_labels.frames` in the parse_bag card.

## Tests (TDD)

Critical test written first; RED was:

```
[[' .aac', '.dat', …, '.wav']] != [['.aac'], ['.dat'], …, ['.wav']]
```

Then implement → GREEN.

| Check | Command | Result |
|-------|---------|--------|
| Editor | `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` | **25/25 OK** (6.7s) |
| Kernel | `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py` | **19/19 OK** (4.8s) |
| Frontend | `cd hmi/frontend && cmd /c "npx.cmd tsc -b --pretty false"` | **pass** |

New editor cases: hydrate+compile `audio_array_spec` + preflight `[".wav"]`; same for `ivi_ui_stub` + `[".mp4"]`; compile strips stale `output_labels.frames`.

## Files changed

- `hmi/backend/hmi/platform/recipe_pipeline.py`
- `hmi/backend/scripts/test_platform_datatype_editor.py`
- `hmi/frontend/src/utils/recipePipeline.ts`
- `hmi/frontend/src/components/datatype/PipelineOrchestrator.tsx`
- `hmi/frontend/src/components/datatype/PipelineStepCard.tsx`

## Not done (per brief)

- No git commit
- No DataWorks changes
- Did not publish `audio_nvh-v2`
