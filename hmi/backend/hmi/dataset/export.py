"""Export dataset snapshot feature/target artifacts to OSS."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from hmi.config import get_settings
from hmi.dataset.assemble import AssemblyResult
from hmi.dataset.distribution import embedding_summary
from hmi.dataset.parsed_data import (
    PARSED_JSONL_NAME,
    attach_parsed_rows,
    collect_parsed_zip_entries,
    render_parsed_jsonl,
)
from hmi.dataset.parquet_export import (
    FEATURE_PARQUET_NAME,
    TARGET_PARQUET_NAME,
    export_parquet_artifacts,
    is_parquet_available,
    x_parquet_oss_key,
    y_parquet_oss_key,
)
from hmi.oss_signer import get_object_bytes, get_object_text, object_exists, put_object_bytes, put_object_text

DATASET_OSS_PREFIX = "datasets"

FEATURE_JSONL_NAME = "特征.jsonl"
TARGET_JSONL_NAME = "目标.jsonl"
META_JSON_NAME = "meta.json"
README_NAME = "README.txt"
PACKAGE_VERSION = 2
SCHEMA_VERSION = "1.0"
SCHEMA_VERSION_AUG = "1.1"
EXPORT_PRESETS = frozenset({"minimal", "full"})


def resolve_schema_version(*, augmentation_mode: str = "none", rows: list[dict[str, Any]] | None = None) -> str:
    if augmentation_mode and augmentation_mode != "none":
        return SCHEMA_VERSION_AUG
    if rows:
        for row in rows:
            vid = str(row.get("variant_id") or "base")
            if vid != "base":
                return SCHEMA_VERSION_AUG
    return SCHEMA_VERSION


def x_oss_key(snapshot_id: str) -> str:
    return f"{DATASET_OSS_PREFIX}/{snapshot_id.strip()}/X.jsonl"


def y_oss_key(snapshot_id: str) -> str:
    return f"{DATASET_OSS_PREFIX}/{snapshot_id.strip()}/y.jsonl"


def parsed_oss_key(snapshot_id: str) -> str:
    return f"{DATASET_OSS_PREFIX}/{snapshot_id.strip()}/parsed.jsonl"


def meta_oss_key(snapshot_id: str) -> str:
    return f"{DATASET_OSS_PREFIX}/{snapshot_id.strip()}/meta.json"


def package_oss_key(snapshot_id: str) -> str:
    return f"{DATASET_OSS_PREFIX}/{snapshot_id.strip()}/dataset.zip"


def manifest_oss_key(snapshot_id: str) -> str:
    """Legacy alias for dataset.zip OSS key (M4 tests)."""
    return package_oss_key(snapshot_id)


def render_x_jsonl(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        payload: dict[str, Any] = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "x_json": row["x_json"],
        }
        if row.get("variant_id"):
            payload["variant_id"] = row["variant_id"]
        if row.get("source_row_key"):
            payload["source_row_key"] = row["source_row_key"]
        if row.get("aug_hint"):
            payload["aug_hint"] = row["aug_hint"]
        lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def render_y_jsonl(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        payload: dict[str, Any] = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "y_json": row["y_json"],
            "taxonomy_version_id": row.get("taxonomy_version_id"),
            "taxonomy_version_code": row.get("taxonomy_version_code"),
        }
        if row.get("variant_id"):
            payload["variant_id"] = row["variant_id"]
        if row.get("source_row_key"):
            payload["source_row_key"] = row["source_row_key"]
        if row.get("aug_hint"):
            payload["aug_hint"] = row["aug_hint"]
        lines.append(json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def build_meta_json(
    *,
    snapshot_id: str,
    assembly: AssemblyResult,
    export_preset: str,
    filter_snapshot: dict[str, Any] | None = None,
    snapshot_name: str | None = None,
    augmentation_mode: str = "none",
    parent_snapshot_id: str | None = None,
    derivation: dict[str, Any] | None = None,
    aug_recipe: dict[str, Any] | None = None,
    taxonomy_summary: dict[str, Any] | None = None,
    include_parquet: bool = False,
    parquet_exported: bool = False,
) -> dict[str, Any]:
    schema_version = resolve_schema_version(augmentation_mode=augmentation_mode, rows=assembly.rows)
    emb_summary = embedding_summary(assembly.rows)
    meta: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "name": snapshot_name,
        "schema_version": schema_version,
        "package_version": PACKAGE_VERSION,
        "export_preset": export_preset,
        "filter_snapshot": filter_snapshot or {},
        "clip_count": assembly.clip_count,
        "line_count": assembly.line_count,
        "taxonomy_summary": taxonomy_summary or {},
        "embedding_summary": emb_summary,
        "build_report": assembly.build_report or {
            "skipped": assembly.skipped,
            "skipped_by_reason": {},
            "warnings": assembly.warnings,
        },
        "distribution_report": assembly.distribution_report or {"before": {}, "after": {}},
        "augmentation_mode": augmentation_mode,
        "parent_snapshot_id": parent_snapshot_id,
        "x_key": x_oss_key(snapshot_id),
        "y_key": y_oss_key(snapshot_id),
        "parsed_key": parsed_oss_key(snapshot_id),
        "package_key": package_oss_key(snapshot_id),
        "include_parquet": include_parquet,
        "parquet_available": parquet_exported,
        "files": {
            "features": FEATURE_JSONL_NAME,
            "targets": TARGET_JSONL_NAME,
            "parsed": PARSED_JSONL_NAME,
            "meta": META_JSON_NAME,
        },
    }
    if parquet_exported:
        meta["x_parquet_key"] = x_parquet_oss_key(snapshot_id)
        meta["y_parquet_key"] = y_parquet_oss_key(snapshot_id)
        meta["files"]["features_parquet"] = FEATURE_PARQUET_NAME
        meta["files"]["targets_parquet"] = TARGET_PARQUET_NAME
    if derivation:
        meta["derivation"] = derivation
    if aug_recipe:
        meta["aug_recipe"] = aug_recipe
    return meta


def build_dataset_package_bytes(
    *,
    snapshot_id: str,
    x_body: str,
    y_body: str,
    meta_body: str,
    export_preset: str = "minimal",
    parsed_body: str = "",
    parsed_files: list[tuple[str, bytes]] | None = None,
    snapshot_name: str | None = None,
    x_parquet: bytes | None = None,
    y_parquet: bytes | None = None,
) -> bytes:
    preset = export_preset if export_preset in EXPORT_PRESETS else "minimal"
    readme = (
        "数据集快照完整包\n"
        f"snapshot_id: {snapshot_id}\n"
        f"name: {snapshot_name or ''}\n"
        f"export_preset: {preset}\n\n"
        "文件说明:\n"
        f"- {FEATURE_JSONL_NAME}  clip 级特征向量 (x_json，每行一条 manifest 行)\n"
        f"- {TARGET_JSONL_NAME}  校核后标签 (y_json，每行一条 manifest 行)\n"
    )
    if x_parquet and y_parquet:
        readme += (
            f"- {FEATURE_PARQUET_NAME}  特征 Parquet（clip 级向量列 + 元数据）\n"
            f"- {TARGET_PARQUET_NAME}  标签 Parquet（扁平 label 列 + y_json）\n"
        )
    if preset == "full":
        readme += (
            f"- {PARSED_JSONL_NAME}  Job1 解析后的结构化原始数据\n"
            "- clips/{clip_id}/runs/{run_id}/parsed/...  解析产物文件\n"
        )
    readme += f"- {META_JSON_NAME}      快照元数据\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(FEATURE_JSONL_NAME, x_body)
        zf.writestr(TARGET_JSONL_NAME, y_body)
        if x_parquet and y_parquet:
            zf.writestr(FEATURE_PARQUET_NAME, x_parquet)
            zf.writestr(TARGET_PARQUET_NAME, y_parquet)
        if preset == "full" and parsed_body:
            zf.writestr(PARSED_JSONL_NAME, parsed_body)
        zf.writestr(META_JSON_NAME, meta_body)
        zf.writestr(README_NAME, readme)
        if preset == "full":
            for zip_path, payload in parsed_files or []:
                zf.writestr(zip_path, payload)
    return buf.getvalue()


def upload_dataset_package(
    snapshot_id: str,
    *,
    x_body: str,
    y_body: str,
    meta_body: str,
    export_preset: str = "minimal",
    parsed_body: str = "",
    parsed_files: list[tuple[str, bytes]] | None = None,
    snapshot_name: str | None = None,
    x_parquet: bytes | None = None,
    y_parquet: bytes | None = None,
) -> str:
    package_key = package_oss_key(snapshot_id)
    payload = build_dataset_package_bytes(
        snapshot_id=snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        export_preset=export_preset,
        parsed_body=parsed_body,
        parsed_files=parsed_files,
        snapshot_name=snapshot_name,
        x_parquet=x_parquet,
        y_parquet=y_parquet,
    )
    put_object_bytes(package_key, payload, content_type="application/zip")
    return package_key


def ensure_dataset_package_on_oss(
    snapshot_id: str,
    *,
    snapshot_name: str | None = None,
    x_key: str | None = None,
    y_key: str | None = None,
    meta_key: str | None = None,
    existing_package_key: str | None = None,
) -> str:
    """Return OSS key for dataset.zip; rebuild from X/y/meta/parsed if missing or outdated."""
    package_key = (existing_package_key or "").strip() or package_oss_key(snapshot_id)
    resolved_meta = meta_key or meta_oss_key(snapshot_id)
    meta_body = get_object_text(resolved_meta)
    meta_obj: dict[str, Any] = {}
    if meta_body:
        try:
            loaded = json.loads(meta_body)
            meta_obj = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            meta_obj = {}
    package_version_ok = int(meta_obj.get("package_version") or 0) >= PACKAGE_VERSION
    if object_exists(package_key) and package_version_ok:
        return package_key

    resolved_x = x_key or x_oss_key(snapshot_id)
    resolved_y = y_key or y_oss_key(snapshot_id)
    if not meta_body:
        resolved_meta = meta_oss_key(snapshot_id)
        meta_body = get_object_text(resolved_meta)
        if meta_body:
            try:
                loaded = json.loads(meta_body)
                meta_obj = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                meta_obj = {}
    export_preset = str(meta_obj.get("export_preset") or "minimal")
    resolved_parsed = parsed_oss_key(snapshot_id)
    x_body = get_object_text(resolved_x)
    y_body = get_object_text(resolved_y)
    parsed_body = get_object_text(resolved_parsed) or ""
    if not x_body or not y_body or not meta_body:
        raise ValueError("dataset feature/target/meta artifacts missing on OSS")

    if int(meta_obj.get("package_version") or 0) < PACKAGE_VERSION:
        raise ValueError("dataset package outdated; rebuild snapshot to include parsed data")

    parsed_files: list[tuple[str, bytes]] = []
    if export_preset == "full" and parsed_body:
        try:
            rows = [json.loads(line) for line in parsed_body.splitlines() if line.strip()]
            clip_rows = [{"clip_id": r.get("clip_id"), "run_id": r.get("run_id")} for r in rows if isinstance(r, dict)]
            parsed_files = collect_parsed_zip_entries(attach_parsed_rows(clip_rows))
        except Exception:
            parsed_files = []

    x_parquet = y_parquet = None
    if meta_obj.get("parquet_available"):
        x_pk = str(meta_obj.get("x_parquet_key") or x_parquet_oss_key(snapshot_id))
        y_pk = str(meta_obj.get("y_parquet_key") or y_parquet_oss_key(snapshot_id))
        x_parquet = get_object_bytes(x_pk)
        y_parquet = get_object_bytes(y_pk)

    return upload_dataset_package(
        snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        export_preset=export_preset,
        parsed_body=parsed_body if export_preset == "full" else "",
        parsed_files=parsed_files if export_preset == "full" else None,
        snapshot_name=snapshot_name,
        x_parquet=x_parquet,
        y_parquet=y_parquet,
    )


def export_xy_to_oss(
    snapshot_id: str,
    assembly: AssemblyResult,
    *,
    snapshot_name: str | None = None,
    export_preset: str = "minimal",
    filter_snapshot: dict[str, Any] | None = None,
    augmentation_mode: str = "none",
    parent_snapshot_id: str | None = None,
    derivation: dict[str, Any] | None = None,
    aug_recipe: dict[str, Any] | None = None,
    taxonomy_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    get_settings()
    preset = export_preset if export_preset in EXPORT_PRESETS else "minimal"
    filt = filter_snapshot or {}
    include_parquet = bool(filt.get("include_parquet"))
    x_key = x_oss_key(snapshot_id)
    y_key = y_oss_key(snapshot_id)
    meta_key = meta_oss_key(snapshot_id)
    parsed_key = parsed_oss_key(snapshot_id)
    parsed_body = ""
    parsed_files: list[tuple[str, bytes]] = []
    if preset == "full":
        rows_with_parsed = attach_parsed_rows(assembly.rows)
        parsed_files = collect_parsed_zip_entries(rows_with_parsed)
        parsed_body = render_parsed_jsonl(rows_with_parsed)
    x_body = render_x_jsonl(assembly.rows)
    y_body = render_y_jsonl(assembly.rows)

    parquet_bytes: dict[str, bytes] | None = None
    parquet_exported = False
    parquet_warning: str | None = None
    if include_parquet:
        if is_parquet_available():
            parquet_bytes = export_parquet_artifacts(assembly.rows)
            parquet_exported = parquet_bytes is not None
        else:
            parquet_warning = "include_parquet requested but pyarrow is not installed"

    meta_obj = build_meta_json(
        snapshot_id=snapshot_id,
        assembly=assembly,
        export_preset=preset,
        filter_snapshot=filter_snapshot,
        snapshot_name=snapshot_name,
        augmentation_mode=augmentation_mode,
        parent_snapshot_id=parent_snapshot_id,
        derivation=derivation,
        aug_recipe=aug_recipe,
        taxonomy_summary=taxonomy_summary,
        include_parquet=include_parquet,
        parquet_exported=parquet_exported,
    )
    if parquet_warning:
        warnings = list(meta_obj.get("build_report", {}).get("warnings") or [])
        warnings.append(parquet_warning)
        meta_obj.setdefault("build_report", {})["warnings"] = warnings

    meta_body = json.dumps(meta_obj, ensure_ascii=False, indent=2)
    put_object_text(x_key, x_body, content_type="application/x-ndjson")
    put_object_text(y_key, y_body, content_type="application/x-ndjson")
    if preset == "full":
        put_object_text(parsed_key, parsed_body, content_type="application/x-ndjson")
    x_parquet = y_parquet = None
    if parquet_bytes:
        x_parquet = parquet_bytes["x"]
        y_parquet = parquet_bytes["y"]
        put_object_bytes(x_parquet_oss_key(snapshot_id), x_parquet, content_type="application/octet-stream")
        put_object_bytes(y_parquet_oss_key(snapshot_id), y_parquet, content_type="application/octet-stream")
    put_object_text(meta_key, meta_body, content_type="application/json")
    package_key = upload_dataset_package(
        snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        export_preset=preset,
        parsed_body=parsed_body,
        parsed_files=parsed_files,
        snapshot_name=snapshot_name,
        x_parquet=x_parquet,
        y_parquet=y_parquet,
    )
    return {
        "oss_x_uri": x_key,
        "oss_y_uri": y_key,
        "oss_parsed_uri": parsed_key if preset == "full" else None,
        "oss_package_uri": package_key,
        "oss_x_parquet_uri": x_parquet_oss_key(snapshot_id) if parquet_exported else None,
        "oss_y_parquet_uri": y_parquet_oss_key(snapshot_id) if parquet_exported else None,
        "x_key": x_key,
        "y_key": y_key,
        "parsed_key": parsed_key if preset == "full" else None,
        "meta_key": meta_key,
        "package_key": package_key,
        "clip_count": assembly.clip_count,
        "line_count": assembly.line_count,
        "parsed_file_count": len(parsed_files),
        "schema_version": meta_obj["schema_version"],
        "export_preset": preset,
        "parquet_available": parquet_exported,
        "build_report": meta_obj["build_report"],
    }
