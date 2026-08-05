# pipeline/dataworks/sdk_pipeline_driver_lib.py
from __future__ import annotations

import uuid
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


def content_hash_to_clip_id(hex_digest: str) -> str:
    digest = hex_digest.strip().lower().removeprefix("sha256:")
    return f"sha256:{digest}"


def make_run_id() -> str:
    return str(uuid.uuid4())


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
        "ds": "string",
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
