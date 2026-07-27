"""Export dataset snapshot feature/target artifacts to OSS."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from hmi.config import get_settings
from hmi.dataset.assemble import AssemblyResult
from hmi.dataset.parsed_data import (
    PARSED_JSONL_NAME,
    attach_parsed_rows,
    collect_parsed_zip_entries,
    render_parsed_jsonl,
)
from hmi.oss_signer import get_object_text, object_exists, put_object_bytes, put_object_text

DATASET_OSS_PREFIX = "datasets"

FEATURE_JSONL_NAME = "特征.jsonl"
TARGET_JSONL_NAME = "目标.jsonl"
META_JSON_NAME = "meta.json"
README_NAME = "README.txt"
PACKAGE_VERSION = 2


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


def render_x_jsonl(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = [
        json.dumps(
            {
                "clip_id": row["clip_id"],
                "run_id": row["run_id"],
                "x_json": row["x_json"],
            },
            ensure_ascii=False,
        )
        for row in rows
    ]
    return "\n".join(lines) + "\n"


def render_y_jsonl(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = [
        json.dumps(
            {
                "clip_id": row["clip_id"],
                "run_id": row["run_id"],
                "y_json": row["y_json"],
                "taxonomy_version_id": row.get("taxonomy_version_id"),
                "taxonomy_version_code": row.get("taxonomy_version_code"),
            },
            ensure_ascii=False,
        )
        for row in rows
    ]
    return "\n".join(lines) + "\n"


def build_dataset_package_bytes(
    *,
    snapshot_id: str,
    x_body: str,
    y_body: str,
    meta_body: str,
    parsed_body: str = "",
    parsed_files: list[tuple[str, bytes]] | None = None,
    snapshot_name: str | None = None,
) -> bytes:
    readme = (
        "数据集快照完整包\n"
        f"snapshot_id: {snapshot_id}\n"
        f"name: {snapshot_name or ''}\n\n"
        "文件说明:\n"
        f"- {FEATURE_JSONL_NAME}  clip 级特征向量 (x_json，每行一条 clip)\n"
        f"- {TARGET_JSONL_NAME}  校核后标签 (y_json，每行一条 clip)\n"
        f"- {PARSED_JSONL_NAME}  Job1 解析后的结构化原始数据 (frames/events/audio 等，每行一条 clip)\n"
        f"- clips/{{clip_id}}/runs/{{run_id}}/parsed/...  解析产物文件（manifest、events、帧图、音频等，若本地/OSS 可用）\n"
        f"- {META_JSON_NAME}      快照元数据（clip 数、OSS key 等）\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(FEATURE_JSONL_NAME, x_body)
        zf.writestr(TARGET_JSONL_NAME, y_body)
        if parsed_body:
            zf.writestr(PARSED_JSONL_NAME, parsed_body)
        zf.writestr(META_JSON_NAME, meta_body)
        zf.writestr(README_NAME, readme)
        for zip_path, payload in parsed_files or []:
            zf.writestr(zip_path, payload)
    return buf.getvalue()


def upload_dataset_package(
    snapshot_id: str,
    *,
    x_body: str,
    y_body: str,
    meta_body: str,
    parsed_body: str = "",
    parsed_files: list[tuple[str, bytes]] | None = None,
    snapshot_name: str | None = None,
) -> str:
    package_key = package_oss_key(snapshot_id)
    payload = build_dataset_package_bytes(
        snapshot_id=snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        parsed_body=parsed_body,
        parsed_files=parsed_files,
        snapshot_name=snapshot_name,
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
    resolved_parsed = parsed_oss_key(snapshot_id)
    x_body = get_object_text(resolved_x)
    y_body = get_object_text(resolved_y)
    parsed_body = get_object_text(resolved_parsed) or ""
    if not x_body or not y_body or not meta_body:
        raise ValueError("dataset feature/target/meta artifacts missing on OSS")

    if int(meta_obj.get("package_version") or 0) < PACKAGE_VERSION:
        raise ValueError("dataset package outdated; rebuild snapshot to include parsed data")

    return upload_dataset_package(
        snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        parsed_body=parsed_body,
        snapshot_name=snapshot_name,
    )


def export_xy_to_oss(
    snapshot_id: str,
    assembly: AssemblyResult,
    *,
    snapshot_name: str | None = None,
) -> dict[str, Any]:
    get_settings()
    x_key = x_oss_key(snapshot_id)
    y_key = y_oss_key(snapshot_id)
    meta_key = meta_oss_key(snapshot_id)
    parsed_key = parsed_oss_key(snapshot_id)
    rows_with_parsed = attach_parsed_rows(assembly.rows)
    parsed_files = collect_parsed_zip_entries(rows_with_parsed)
    x_body = render_x_jsonl(assembly.rows)
    y_body = render_y_jsonl(assembly.rows)
    parsed_body = render_parsed_jsonl(rows_with_parsed)
    meta_body = json.dumps(
        {
            "snapshot_id": snapshot_id,
            "name": snapshot_name,
            "clip_count": assembly.clip_count,
            "skipped": assembly.skipped,
            "warnings": assembly.warnings,
            "package_version": PACKAGE_VERSION,
            "x_key": x_key,
            "y_key": y_key,
            "parsed_key": parsed_key,
            "package_key": package_oss_key(snapshot_id),
            "parsed_file_count": len(parsed_files),
            "files": {
                "features": FEATURE_JSONL_NAME,
                "targets": TARGET_JSONL_NAME,
                "parsed": PARSED_JSONL_NAME,
                "meta": META_JSON_NAME,
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    put_object_text(x_key, x_body, content_type="application/x-ndjson")
    put_object_text(y_key, y_body, content_type="application/x-ndjson")
    put_object_text(parsed_key, parsed_body, content_type="application/x-ndjson")
    put_object_text(meta_key, meta_body, content_type="application/json")
    package_key = upload_dataset_package(
        snapshot_id,
        x_body=x_body,
        y_body=y_body,
        meta_body=meta_body,
        parsed_body=parsed_body,
        parsed_files=parsed_files,
        snapshot_name=snapshot_name,
    )
    return {
        "oss_x_uri": x_key,
        "oss_y_uri": y_key,
        "oss_parsed_uri": parsed_key,
        "oss_package_uri": package_key,
        "x_key": x_key,
        "y_key": y_key,
        "parsed_key": parsed_key,
        "meta_key": meta_key,
        "package_key": package_key,
        "clip_count": assembly.clip_count,
        "line_count": len(assembly.rows),
        "parsed_file_count": len(parsed_files),
    }
