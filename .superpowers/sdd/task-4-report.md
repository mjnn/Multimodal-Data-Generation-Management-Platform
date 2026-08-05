# Task 4 Report

## Status

Complete. Commit `c1643d8` wires `sdk_pipeline_driver_node.py` from the echo UDF to `run_stages` and includes the scoped preview multi-directory fix.

## Changes

- Added `_pipeline_chunk` with per-row `OmsMultimodalClient` lifecycle and `run_stages` execution.
- Injected closed-over SDK/model/MC environment values into `os.environ` before client creation.
- Added `ODPS_ACCESS_ID`, `ODPS_ACCESS_KEY`, `ODPS_PROJECT`, and `ODPS_ENDPOINT` injection. Explicit workflow arguments override Driver account/project/endpoint fallbacks.
- Set `ok = len(result.errors) == 0`; exceptions and any capability error block later `mc_write`.
- Preserved `wrap_dpe_udf`, `apply_chunk`, explicit output dtypes, and `BATCH_SUMMARY_JSON`.
- Moved the preview return after all clip-directory loops.

## Verification

- `py -3.11 -m py_compile pipeline/dataworks/sdk_pipeline_driver_node.py piplinesdk/oms_multimodal/capabilities/preview.py` — PASS.
- `py -3 pipeline/scripts/check_dpe_nodes.py` — PASS, 31 files.
- `PYTHONPATH=piplinesdk py -3.11 -m pytest piplinesdk/tests/test_run_stages.py -q` — PASS, 6 tests.
- Multi-directory preview regression probe — PASS after reproducing the pre-fix failure.
- `git diff --check` for both committed files — PASS.

## Concerns

- DataWorks/DPE P0 (`extract,asr`, one bag, MC backend) was not run locally and remains the cloud acceptance step.
- `bag_oss_keys` discovery still creates pending clip IDs; use the explicit `bag_oss_key` + `clip_id` + `run_id` triplet for real execution until content-hash discovery is implemented.

## Critical Review Fixes

- Added the MC backend package and model factory to version control, including the missing `ClientConfig` MC runtime fields.
- Wired `OmsMultimodalClient` ASR, Omni, and embedding construction through the MC factories with one lazily shared `McRuntime`.
- Added idempotent `close()` runtime destruction and a defensive callable check in the Driver UDF cleanup.
- Re-exported model factory functions from the SDK public API.
- Added the missing `make_run_context()` client contract used by the committed Task-4 Driver path.
- Added MC construction, shared-runtime, close lifecycle, and run-context regression tests.

## Critical Review Verification

- Required pytest command — PASS, 22 tests.
- `py -3.11 -m py_compile pipeline/dataworks/sdk_pipeline_driver_node.py` — PASS.
- `py -3 pipeline/scripts/check_dpe_nodes.py` — PASS, 31 files.
- Scoped `git diff --check` — PASS.

## Remaining Concern

- Real DataWorks/DPE MC execution still requires the P0 cloud acceptance run; local tests mock client construction and do not invoke a model.
