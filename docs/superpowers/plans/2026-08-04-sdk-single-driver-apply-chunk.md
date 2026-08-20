# SDK Single-Driver apply_chunk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One DataWorks PyODPS3 Driver discovers bags, runs `mf.apply_chunk` with SDK+mc inside DPE UDFs, then writes MC `aig_sdk__*` + `pipeline/dispatch/latest.json` — no multi-node staging workflow.

**Architecture:** Driver-only orchestration; chunk UDF calls `run_stages`; Driver finishes `mc_write`/`dispatch`. Stages are comma-separated and filter both layers. Spec: `docs/superpowers/specs/2026-08-04-sdk-single-driver-apply-chunk-design.md`.

**Tech Stack:** MaxFrame `apply_chunk`, DPE + `@with_fs_mount`, `oms-multimodal` SDK (`MODEL_BACKEND=mc`), MaxCompute `aig_sdk__*`, OSS sdk_v1 layout.

## Global Constraints

- Python 3.11 for mc extras; DPE image must include `oms-multimodal-sdk[mc]` + `rosbags`.
- UDF: no `@dataclass` / custom classes in picklable closures; return only dict/list/scalars.
- Default `model_backend=mc`, `mc_image_mode=base64`, `batch_rows=1`.
- OSS layout `sdk_v1`; MC prefix `aig_sdk__`.
- Old `sdk_*_node` / `sdk_*_dpe_node` stay frozen (reference only).
- **Commits:** only when the user explicitly asks (do not auto-commit).
- Authority: PRD > Mn notes > CURRENT; this plan implements the approved design above.

## File map

| File | Responsibility |
|------|----------------|
| `piplinesdk/oms_multimodal/capabilities/stages.py` | `parse_stages`, `run_stages`, `StagesResult` |
| `piplinesdk/oms_multimodal/capabilities/run_meta.py` | `write_run_json` |
| `piplinesdk/oms_multimodal/capabilities/__init__.py` | Re-export new APIs |
| `piplinesdk/oms_multimodal/__init__.py` | Public exports |
| `piplinesdk/tests/test_run_stages.py` | Unit tests for stages / run.json |
| `pipeline/dataworks/sdk_pipeline_driver_lib.py` | Pure helpers: discover rows, chunk dtypes, summary (importable without DW `o`/`args`) |
| `pipeline/dataworks/sdk_pipeline_driver_node.py` | DW paste target: Driver + apply_chunk UDF |
| `pipeline/scripts/test_sdk_pipeline_driver_lib.py` | Unit tests for driver lib |
| `docs/sdk-v1-cloud-e2e-runbook.md` | Rewrite for single-node path |
| `pipeline/docker/custom-dpe-image.md` | Note SDK`[mc]` requirement |
| `project-management/CURRENT.md` | Point next work to this plan / P0 probe |

Reuse (do not rewrite): `sdk_dpe_common.py`, `pipeline_dispatch.write_dispatch_to_oss`, `scripts/ingest_sdk_run_to_mc.py` SQL patterns, existing atomic capabilities.

---

### Task 1: SDK `parse_stages` + `run_stages` + `write_run_json`

**Files:**
- Create: `piplinesdk/oms_multimodal/capabilities/stages.py`
- Create: `piplinesdk/oms_multimodal/capabilities/run_meta.py`
- Create: `piplinesdk/tests/test_run_stages.py`
- Modify: `piplinesdk/oms_multimodal/capabilities/__init__.py`
- Modify: `piplinesdk/oms_multimodal/__init__.py`

**Interfaces:**
- Consumes: `extract_clips`, `transcribe_clips`, `materialize_preview`, `label_clips`, `embed_clips`, `RunContext`, `ClipConfig`, `OmsMultimodalClient`
- Produces:
  - `parse_stages(raw: str | None) -> frozenset[str]`
  - `DRIVER_STAGES = frozenset({"discover", "mc_write", "dispatch"})`
  - `UDF_STAGES = frozenset({"extract", "asr", "preview", "label", "embed", "upload"})`
  - `ALL_STAGES = DRIVER_STAGES | UDF_STAGES`
  - `run_stages(ctx, bag_path, client, *, stages, clip_config=None) -> StagesResult`
  - `write_run_json(run_dir, *, clip_id, run_id, ds, bag_oss_key="", stages_done=(), model_backend="mc", extra=None) -> Path`

- [ ] **Step 1: Write failing tests**

Create `piplinesdk/tests/test_run_stages.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from oms_multimodal.capabilities.run_meta import write_run_json
from oms_multimodal.capabilities.stages import (
    ALL_STAGES,
    DRIVER_STAGES,
    UDF_STAGES,
    parse_stages,
    run_stages,
)
from oms_multimodal.capabilities.types import (
    EmbedResult,
    ExtractResult,
    LabelResult,
    RunContext,
    TranscribeResult,
)


class TestParseStages(unittest.TestCase):
    def test_default_all(self) -> None:
        self.assertEqual(parse_stages(None), ALL_STAGES)
        self.assertEqual(parse_stages(""), ALL_STAGES)

    def test_subset_and_aliases(self) -> None:
        s = parse_stages("extract, asr, LABEL")
        self.assertEqual(s, frozenset({"extract", "asr", "label"}))

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_stages("extract,nope")


class TestWriteRunJson(unittest.TestCase):
    def test_writes_sdk_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_run_json(
                root,
                clip_id="sha256:abc",
                run_id="run-1",
                ds="20260804",
                bag_oss_key="rosbags/x.bag",
                stages_done=("extract", "upload"),
                model_backend="mc",
            )
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["layout_version"], "sdk_v1")
            self.assertEqual(doc["clip_id"], "sha256:abc")
            self.assertEqual(doc["run_id"], "run-1")
            self.assertIn("labels", doc["sdk_files"])


class TestRunStages(unittest.TestCase):
    def test_skips_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(run_dir=Path(tmp), clip_id="c", run_id="r", media_mode="local")
            client = MagicMock()
            bag = Path(tmp) / "out.bag"
            bag.write_bytes(b"x")
            extract = ExtractResult(
                clips_index=ctx.clips_index_path,
                videos_out=ctx.videos_path,
                clip_rows=1,
                video_rows=1,
                bag="out.bag",
                topics=[],
            )
            with (
                patch("oms_multimodal.capabilities.stages.extract_clips", return_value=extract) as ex,
                patch("oms_multimodal.capabilities.stages.transcribe_clips") as tr,
                patch("oms_multimodal.capabilities.stages.materialize_preview") as pr,
                patch("oms_multimodal.capabilities.stages.label_clips") as lb,
                patch("oms_multimodal.capabilities.stages.embed_clips") as em,
                patch("oms_multimodal.capabilities.stages.write_run_json") as wj,
            ):
                result = run_stages(
                    ctx,
                    bag,
                    client,
                    stages=frozenset({"extract"}),
                )
            ex.assert_called_once()
            tr.assert_not_called()
            pr.assert_not_called()
            lb.assert_not_called()
            em.assert_not_called()
            wj.assert_not_called()
            self.assertEqual(result.stages_done, ["extract"])
            self.assertEqual(result.errors, [])

    def test_upload_writes_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(run_dir=Path(tmp), clip_id="c", run_id="r", media_mode="local")
            client = MagicMock()
            bag = Path(tmp) / "out.bag"
            bag.write_bytes(b"x")
            with patch("oms_multimodal.capabilities.stages.write_run_json") as wj:
                wj.return_value = Path(tmp) / "run.json"
                result = run_stages(
                    ctx,
                    bag,
                    client,
                    stages=frozenset({"upload"}),
                    bag_oss_key="rosbags/out.bag",
                    ds="20260804",
                    model_backend="mc",
                )
            wj.assert_called_once()
            self.assertIn("upload", result.stages_done)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect FAIL**

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\piplinesdk
py -3.11 -m pytest tests/test_run_stages.py -v
```

Expected: import / collection errors (`stages` / `run_meta` missing).

- [ ] **Step 3: Implement `run_meta.py`**

```python
# piplinesdk/oms_multimodal/capabilities/run_meta.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_run_json(
    run_dir: Path | str,
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str = "",
    stages_done: tuple[str, ...] | list[str] = (),
    model_backend: str = "mc",
    extra: dict[str, Any] | None = None,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "layout_version": "sdk_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "bag_oss_key": bag_oss_key,
        "sdk_files": {
            "labels": "labels.jsonl",
            "embeddings": "fusion_embeddings.jsonl",
            "videos": "clip_videos.jsonl",
        },
        "preview_manifest": "preview/manifest.json",
        "stages_done": list(stages_done),
        "model_backend": model_backend,
        "completed_at": _utc_now(),
    }
    if extra:
        doc.update(extra)
    path = run_dir / "run.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
```

- [ ] **Step 4: Implement `stages.py`**

```python
# piplinesdk/oms_multimodal/capabilities/stages.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ClipConfig
from .embed import embed_clips
from .extract import extract_clips
from .label import label_clips
from .preview import materialize_preview
from .run_meta import write_run_json
from .transcribe import transcribe_clips
from .types import RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient

DRIVER_STAGES = frozenset({"discover", "mc_write", "dispatch"})
UDF_STAGES = frozenset({"extract", "asr", "preview", "label", "embed", "upload"})
ALL_STAGES = DRIVER_STAGES | UDF_STAGES

_ALIASES = {"transcribe": "asr"}


def parse_stages(raw: str | None) -> frozenset[str]:
    if raw is None or not str(raw).strip():
        return ALL_STAGES
    out: set[str] = set()
    for token in str(raw).split(","):
        name = token.strip().lower()
        if not name:
            continue
        name = _ALIASES.get(name, name)
        if name not in ALL_STAGES:
            raise ValueError(f"unknown stage {name!r}; choose from {sorted(ALL_STAGES)}")
        out.add(name)
    return frozenset(out) if out else ALL_STAGES


@dataclass
class StagesResult:
    stages_done: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    preview_ok: bool = False
    extract_clip_rows: int = 0
    label_rows: int = 0
    embedding_rows: int = 0


def run_stages(
    ctx: RunContext,
    bag_path: Path | str,
    client: "OmsMultimodalClient",
    *,
    stages: frozenset[str],
    clip_config: ClipConfig | None = None,
    bag_oss_key: str = "",
    ds: str = "",
    model_backend: str = "mc",
    cleanup_work: bool = False,
) -> StagesResult:
    """Run UDF-side stages in order. Driver-only stages are ignored here."""
    bag_path = Path(bag_path)
    wanted = stages & UDF_STAGES
    result = StagesResult()
    cfg = clip_config or ClipConfig()

    if "extract" in wanted:
        extracted = extract_clips(ctx, bag_path, client=client, clip_config=cfg)
        result.extract_clip_rows = extracted.clip_rows
        result.stages_done.append("extract")

    if "asr" in wanted:
        tr = transcribe_clips(ctx, client)
        result.errors.extend(tr.errors)
        result.stages_done.append("asr")

    if "preview" in wanted:
        preview_dir = materialize_preview(ctx)
        result.preview_ok = any(preview_dir.glob("clip_preview_*.mp4")) or (preview_dir / "audio.wav").is_file()
        result.stages_done.append("preview")

    if "label" in wanted:
        lr = label_clips(ctx, client, run_asr=False, merge_asr_file=True)
        result.errors.extend(lr.errors)
        result.label_rows = lr.row_count
        result.stages_done.append("label")

    if "embed" in wanted:
        er = embed_clips(ctx, client)
        result.errors.extend(er.errors)
        result.embedding_rows = er.row_count
        result.stages_done.append("embed")

    if "upload" in wanted:
        # Mount path IS the OSS tree when run_dir is under mount; write run.json as commit marker.
        write_run_json(
            ctx.run_dir,
            clip_id=ctx.clip_id,
            run_id=ctx.run_id,
            ds=ds or "",
            bag_oss_key=bag_oss_key,
            stages_done=tuple(result.stages_done + ["upload"]),
            model_backend=model_backend,
        )
        result.stages_done.append("upload")

    if cleanup_work and ctx.work_dir is not None:
        import shutil

        work = Path(ctx.work_dir)
        if work.is_dir() and work != ctx.run_dir:
            shutil.rmtree(work, ignore_errors=True)

    return result
```

- [ ] **Step 5: Export from package `__init__` files**

In `capabilities/__init__.py` import and add to `__all__`: `parse_stages`, `run_stages`, `StagesResult`, `write_run_json`, `ALL_STAGES`, `UDF_STAGES`, `DRIVER_STAGES`.

Same public names in `oms_multimodal/__init__.py` `__all__`.

- [ ] **Step 6: Run tests — expect PASS**

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\piplinesdk
py -3.11 -m pytest tests/test_run_stages.py -v
```

Expected: all PASS.

---

### Task 2: Driver pure helpers (`sdk_pipeline_driver_lib.py`)

**Files:**
- Create: `pipeline/dataworks/sdk_pipeline_driver_lib.py`
- Create: `pipeline/scripts/test_sdk_pipeline_driver_lib.py`

**Interfaces:**
- Consumes: `parse_stages` from SDK (or duplicate thin stage split if import path awkward in DW paste — prefer import from SDK when wheel present; lib must stay testable offline)
- Produces:
  - `split_stages(stages) -> tuple[frozenset[str], frozenset[str]]`  # driver_stages, udf_stages
  - `build_job_rows(bags: list[dict], *, ds: str) -> list[dict[str, str]]`
  - `chunk_output_dtypes() -> dict[str, str]`  # for MaxFrame dtypes
  - `row_success_status(errors: list) -> bool`
  - `batch_summary(result_rows: list[dict]) -> dict`

- [ ] **Step 1: Write failing tests**

`pipeline/scripts/test_sdk_pipeline_driver_lib.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "dataworks"))
sys.path.insert(0, str(REPO / "piplinesdk"))

from sdk_pipeline_driver_lib import (  # noqa: E402
    batch_summary,
    build_job_rows,
    chunk_output_dtypes,
    split_stages,
)


class TestDriverLib(unittest.TestCase):
    def test_split_stages(self) -> None:
        d, u = split_stages("discover,extract,asr,mc_write")
        self.assertEqual(d, frozenset({"discover", "mc_write"}))
        self.assertEqual(u, frozenset({"extract", "asr"}))

    def test_build_job_rows(self) -> None:
        rows = build_job_rows(
            [{"clip_id": "sha256:a", "run_id": "r1", "bag_oss_key": "rosbags/a.bag"}],
            ds="20260804",
        )
        self.assertEqual(rows[0]["run_relpath"], "clips/sha256:a/runs/r1")
        self.assertEqual(rows[0]["ds"], "20260804")

    def test_dtypes_keys(self) -> None:
        d = chunk_output_dtypes()
        for k in ("clip_id", "ok", "error", "stages_done", "labels_relpath"):
            self.assertIn(k, d)

    def test_summary(self) -> None:
        s = batch_summary(
            [
                {"ok": True, "clip_id": "a"},
                {"ok": False, "clip_id": "b", "error": "x"},
            ]
        )
        self.assertEqual(s["ok_count"], 1)
        self.assertEqual(s["fail_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: sdk_pipeline_driver_lib`)

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline
py -3.11 pipeline\scripts\test_sdk_pipeline_driver_lib.py
```

- [ ] **Step 3: Implement lib**

```python
# pipeline/dataworks/sdk_pipeline_driver_lib.py
from __future__ import annotations

from typing import Any

try:
    from oms_multimodal.capabilities.stages import DRIVER_STAGES, UDF_STAGES, parse_stages
except ImportError:  # pragma: no cover - DW paste without path
    DRIVER_STAGES = frozenset({"discover", "mc_write", "dispatch"})
    UDF_STAGES = frozenset({"extract", "asr", "preview", "label", "embed", "upload"})

    def parse_stages(raw: str | None) -> frozenset[str]:
        if not raw or not str(raw).strip():
            return DRIVER_STAGES | UDF_STAGES
        parts = {t.strip().lower() for t in str(raw).split(",") if t.strip()}
        return frozenset(parts)


def split_stages(raw: str | None) -> tuple[frozenset[str], frozenset[str]]:
    stages = parse_stages(raw)
    return stages & DRIVER_STAGES, stages & UDF_STAGES


def build_job_rows(bags: list[dict[str, Any]], *, ds: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for bag in bags:
        clip_id = str(bag["clip_id"]).strip()
        run_id = str(bag["run_id"]).strip()
        bag_oss_key = str(bag["bag_oss_key"]).strip()
        run_relpath = f"clips/{clip_id}/runs/{run_id}"
        rows.append(
            {
                "clip_id": clip_id,
                "run_id": run_id,
                "bag_oss_key": bag_oss_key,
                "run_relpath": run_relpath,
                "ds": ds,
            }
        )
    return rows


def chunk_output_dtypes() -> dict[str, str]:
    return {
        "clip_id": "string",
        "run_id": "string",
        "bag_oss_key": "string",
        "ok": "boolean",
        "error": "string",
        "stages_done": "string",
        "run_relpath": "string",
        "labels_relpath": "string",
        "embeddings_relpath": "string",
        "videos_relpath": "string",
        "preview_ok": "boolean",
    }


def row_success_status(errors: list[dict[str, str]], *, require_files: bool = False) -> bool:
    if errors:
        return False
    return True


def batch_summary(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [r for r in result_rows if r.get("ok") in (True, "true", 1)]
    fail_rows = [r for r in result_rows if r not in ok_rows]
    return {
        "total": len(result_rows),
        "ok_count": len(ok_rows),
        "fail_count": len(fail_rows),
        "ok_clip_ids": [str(r.get("clip_id")) for r in ok_rows],
        "failures": [
            {"clip_id": str(r.get("clip_id")), "error": str(r.get("error") or "")[:500]}
            for r in fail_rows
        ],
    }
```

Fix `batch_summary` fail detection:

```python
def batch_summary(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _ok(r: dict[str, Any]) -> bool:
        v = r.get("ok")
        return v is True or v == 1 or str(v).lower() == "true"

    ok_rows = [r for r in result_rows if _ok(r)]
    fail_rows = [r for r in result_rows if not _ok(r)]
    return {
        "total": len(result_rows),
        "ok_count": len(ok_rows),
        "fail_count": len(fail_rows),
        "ok_clip_ids": [str(r.get("clip_id")) for r in ok_rows],
        "failures": [
            {"clip_id": str(r.get("clip_id")), "error": str(r.get("error") or "")[:500]}
            for r in fail_rows
        ],
    }
```

- [ ] **Step 4: Run tests — PASS**

```powershell
py -3.11 D:\cursor_project\rosbag_to_labels_pipline\pipeline\scripts\test_sdk_pipeline_driver_lib.py
```

---

### Task 3: Driver node skeleton — discover + echo `apply_chunk`

**Files:**
- Create: `pipeline/dataworks/sdk_pipeline_driver_node.py`
- Modify: `pipeline/dataworks/sdk_pipeline_driver_lib.py` (add `discover_bags_from_keys` if needed)

**Interfaces:**
- Consumes: `sdk_dpe_common.*`, `sdk_pipeline_driver_lib.*`, DataWorks `o` / `args`
- Produces: runnable node that with `stages=discover` only prints job rows; with UDF stages runs echo UDF returning `ok=True`

- [ ] **Step 1: Implement discover helper (hash later; first version uses filename stem placeholder only if hash too heavy — prefer real sha256 of bag on mount for production)**

Add to lib:

```python
def content_hash_to_clip_id(hex_digest: str) -> str:
    h = hex_digest.strip().lower().removeprefix("sha256:")
    return f"sha256:{h}"


def make_run_id() -> str:
    import uuid
    return str(uuid.uuid4())
```

In the Driver node discover loop (on mount or oss2 list): for each `.bag` key, compute sha256 (Driver may hash via short DPE apply or local mount). **MVP for skeleton:** accept explicit `bag_oss_key`+`clip_id`+`run_id` args OR list keys and set `clip_id=sha256:pending_{safe_name}` only for echo test — **do not ship pending ids to prod**. Production discover must hash file bytes (reuse Job0 pattern from `job0_discover_node` if present).

- [ ] **Step 2: Write `sdk_pipeline_driver_node.py` structure**

Pseudo-structure to implement fully (no TBD):

1. `configure_dpe_engine` + `apply_dpe_runtime_settings(dpe_image)`
2. Parse args via `sdk_dpe_common.get_dw_arg`
3. `driver_stages, udf_stages = split_stages(...)`
4. Build `job_rows` from debug args or discover
5. If `udf_stages` empty: print rows and skip apply_chunk
6. Else: `new_session(o)`; build `md.DataFrame`; define UDF that for each row in chunk DataFrame calls SDK (Task 4) — for Task 3 only echo:

```python
def _echo_chunk(df):
    import pandas as pd
    out = []
    for _, row in df.iterrows():
        out.append({
            "clip_id": str(row["clip_id"]),
            "run_id": str(row["run_id"]),
            "bag_oss_key": str(row["bag_oss_key"]),
            "ok": True,
            "error": "",
            "stages_done": "echo",
            "run_relpath": str(row["run_relpath"]),
            "labels_relpath": f"{row['run_relpath']}/labels.jsonl",
            "embeddings_relpath": f"{row['run_relpath']}/fusion_embeddings.jsonl",
            "videos_relpath": f"{row['run_relpath']}/clip_videos.jsonl",
            "preview_ok": False,
        })
    return pd.DataFrame(out)
```

7. `df.mf.apply_chunk(_echo_chunk, batch_rows=..., output_type="dataframe", dtypes=..., skip_infer=True).execute().fetch()`
8. Print `BATCH_SUMMARY_JSON=...`
9. `session.destroy()` in `finally`

Decorate UDF with `@with_fs_mount` / `@with_python_requirements` following `sdk_extract_dpe_node.py` patterns in `sdk_dpe_common.wrap_dpe_udf`.

- [ ] **Step 3: Local dry syntax check**

```powershell
py -3.11 -m py_compile D:\cursor_project\rosbag_to_labels_pipline\pipeline\dataworks\sdk_pipeline_driver_node.py
py -3 pipeline\scripts\check_dpe_nodes.py
```

Expected: no dataclass violations on the new node (or exclude if scanner only `*_node.py` matching — ensure new file is scanned).

---

### Task 4: Wire UDF to `run_stages` (extract→…→upload)

**Files:**
- Modify: `pipeline/dataworks/sdk_pipeline_driver_node.py`

**Interfaces:**
- Consumes: `run_stages`, `OmsMultimodalClient`, `ClipConfig`, env from `collect_sdk_env_for_dpe`
- Produces: real status rows; OSS artifacts under `mount_path / run_relpath`

- [ ] **Step 1: Replace echo body with:**

```python
def _pipeline_chunk(df):  # closed over mount_path, udf_stages, model env, clip cfg
    import os
    import pandas as pd
    from pathlib import Path
    from oms_multimodal import ClipConfig, OmsMultimodalClient, run_stages

    # apply closed-over env dict onto os.environ
    rows_out = []
    for _, row in df.iterrows():
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        bag_oss_key = str(row["bag_oss_key"])
        run_relpath = str(row["run_relpath"])
        ds = str(row["ds"])
        try:
            bag_path = Path(mount_path) / bag_oss_key
            run_out = Path(mount_path) / run_relpath
            run_out.mkdir(parents=True, exist_ok=True)
            client = OmsMultimodalClient(work_dir=run_out / "_sdk_work", load_dotenv=False)
            ctx = client.make_run_context(
                run_out,
                media_mode="local",
                clip_id=clip_id,
                run_id=run_id,
            )
            try:
                result = run_stages(
                    ctx,
                    bag_path,
                    client,
                    stages=udf_stages_frozen,
                    clip_config=ClipConfig(min_sec=clip_min_sec, max_sec=clip_max_sec, sample_fps=sample_fps),
                    bag_oss_key=bag_oss_key,
                    ds=ds,
                    model_backend=model_backend,
                    cleanup_work=cleanup_work,
                )
            finally:
                client.close()
            ok = not result.errors and (
                "label" not in udf_stages_frozen or result.label_rows > 0 or "label" not in result.stages_done
            )
            # Prefer: ok if no exceptions and (no errors list entries). Soft-fail ASR/label errors stay in errors.
            ok = len(result.errors) == 0
            err = ""
            if result.errors:
                err = str(result.errors[0])[:500]
            rows_out.append({
                "clip_id": clip_id,
                "run_id": run_id,
                "bag_oss_key": bag_oss_key,
                "ok": ok,
                "error": err,
                "stages_done": ",".join(result.stages_done),
                "run_relpath": run_relpath,
                "labels_relpath": f"{run_relpath}/labels.jsonl",
                "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                "preview_ok": bool(result.preview_ok),
            })
        except Exception as exc:  # noqa: BLE001
            rows_out.append({
                "clip_id": clip_id,
                "run_id": run_id,
                "bag_oss_key": bag_oss_key,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "stages_done": "",
                "run_relpath": run_relpath,
                "labels_relpath": f"{run_relpath}/labels.jsonl",
                "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                "preview_ok": False,
            })
    return pd.DataFrame(rows_out)
```

Clarify ok policy in code comments: **any** capability error dict ⇒ `ok=False` so Driver skips mc_write (matches design §3.4).

- [ ] **Step 2: Ensure ODPS env for mc inside UDF**

Before creating client, set from closed-over dict:

`MODEL_BACKEND`, `ODPS_*` (from Driver `o.account` + project/endpoint args), `MC_*`, `ASR_MODEL`, etc.  
Driver must pass `ODPS_PROJECT` / `ODPS_ENDPOINT` / access id/secret or rely on Worker identity — **document which**. Preferred: inject long-term AK from workflow secrets into env for mc `resolve_odps_entry` inside Worker (same as local `.env` pattern).

- [ ] **Step 3: P0 manual checklist (DW)**

Document in runbook (Task 6):  
`stages=extract,asr`, `batch_rows=1`, `max_bags=1`, `mc_image_mode=base64`.  
Pass = `asr.jsonl` on OSS + LogView shows ASR text.

---

### Task 5: Driver `mc_write` + `dispatch`

**Files:**
- Modify: `pipeline/dataworks/sdk_pipeline_driver_node.py`
- Optionally create: `pipeline/dataworks/sdk_mc_ingest.py` (pure functions extracted from `ingest_sdk_run_to_mc.py` for reuse)

**Interfaces:**
- Consumes: result rows with `ok=true`; OSS jsonl via mount; `o.execute_sql`; `write_dispatch_to_oss`
- Produces: MC rows + `pipeline/dispatch/latest.json`

- [ ] **Step 1: Extract ingest helpers**

Move SQL builders from `pipeline/scripts/ingest_sdk_run_to_mc.py` into `pipeline/dataworks/sdk_mc_ingest.py`:

- `ingest_sdk_run(odps, *, clip_id, run_id, ds, run_dir: Path, table_prefix="aig_sdk__", bag_oss_key="") -> None`

Keep CLI script as thin wrapper calling the same function.

- [ ] **Step 2: Unit-test SQL builder with mocked paths**

Create temp dir with minimal `labels.jsonl` / `fusion_embeddings.jsonl` / `run.json`; call builder to get statement list; assert `fact_clip_label` and `fact_clip_embedding` appear (no live ODPS required if function returns SQL list).

- [ ] **Step 3: Driver after fetch**

```python
if "mc_write" in driver_stages:
    for row in ok_rows:
        run_dir = Path(mount_path) / row["run_relpath"]
        ingest_sdk_run(o, clip_id=row["clip_id"], run_id=row["run_id"], ds=row["ds"], run_dir=run_dir, bag_oss_key=row["bag_oss_key"])

if "dispatch" in driver_stages:
    payload = {
        "layout_version": "sdk_v1",
        "items": [
            {"clip_id": r["clip_id"], "run_id": r["run_id"], "bag_oss_key": r["bag_oss_key"]}
            for r in ok_rows
        ],
        # plus single-item fields if HMI expects top-level clip_id when len==1
    }
    write_dispatch_to_oss(...)
```

Align payload shape with existing `pipeline_dispatch.write_dispatch_to_oss` / HMI reader (`DISPATCH_MANIFEST_KEY`).

- [ ] **Step 4: Skip when no ok rows** — print warning, still emit summary.

---

### Task 6: Docs + CURRENT + freeze notice

**Files:**
- Modify: `docs/sdk-v1-cloud-e2e-runbook.md`
- Modify: `pipeline/docker/custom-dpe-image.md`
- Modify: `project-management/CURRENT.md`
- Modify: `pipeline/dataworks/WORKFLOW.md` (short pointer to single-driver; mark multi-node deprecated for new work)

- [ ] **Step 1: Rewrite runbook §1 flowchart** to single node `sdk_pipeline_driver` with `stages` / `batch_rows`.
- [ ] **Step 2: Document P0/P1/P2** from design §7.
- [ ] **Step 3: DPE image** — require `pip install 'oms-multimodal-sdk[mc]'` (version pin 0.3.2+).
- [ ] **Step 4: CURRENT.md** — recommend next: **P0 DW probe** of this driver; M9.3 A-C after P1.

---

### Task 7: Discover production hashing (if deferred in Task 3)

**Files:**
- Modify: `sdk_pipeline_driver_lib.py` / driver node

- [ ] **Step 1:** Port bag content hash from `job0_discover_node` (Driver list keys + DPE hash UDF **or** hash on mount in chunk before extract).
- [ ] **Step 2:** `force_rerun` skip via ODPS query on `aig_sdk__dim_clip` + pipeline_run status.
- [ ] **Step 3:** `max_bags` trim after discover sort by key.

Prefer hashing **inside the same pipeline chunk** before extract (one pass) to avoid a second apply_chunk — then clip_id must be known for `run_relpath`. That implies either:

- **Option A (recommended for plan):** Driver lists keys → temporary `run_id` → UDF hashes bag, returns `clip_id` + writes under final path (more complex move), or  
- **Option B:** Driver `apply_chunk` hash-only first (batch_rows large), then second `apply_chunk` for pipeline (two chunks, still one node — allowed by design “逻辑上”一次业务 chunk; two applies OK if documented).

**Lock Option B** for clarity: (1) hash chunk → job_rows with real clip_id (2) pipeline chunk. No multi-node staging file.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Single PyODPS3 Driver | 3–5 |
| `apply_chunk` + `batch_rows` | 3–4 |
| Discover OSS bags | 3, 7 |
| UDF SDK stages | 1, 4 |
| `MODEL_BACKEND=mc` in UDF | 4 |
| OSS sdk_v1 + run.json | 1, 4 |
| Driver mc_write + dispatch | 5 |
| `stages` switches | 1–2, 4–5 |
| Row-level failure isolation | 4 |
| Freeze old nodes / runbook | 6 |
| P0 probe path | 4, 6 |
| No dataclass in UDF | 3–4 + check_dpe_nodes |

## Placeholder / consistency self-review

- No TBD left; Option B locked for discover hashing.
- `ok` policy: any capability `errors` ⇒ skip MC/dispatch.
- `run_stages` / `write_run_json` names consistent across tasks.
- Commits only on user request (Global Constraints).

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-08-04-sdk-single-driver-apply-chunk.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session, executing-plans with checkpoints  

Which approach?
