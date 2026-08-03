"""Optional Parquet export for dataset snapshots (M7.5)."""

from __future__ import annotations

import io
import json
from typing import Any

FEATURE_PARQUET_NAME = "特征.parquet"
TARGET_PARQUET_NAME = "目标.parquet"


def is_parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        import pyarrow.parquet  # noqa: F401

        return True
    except ImportError:
        return False


def x_parquet_oss_key(snapshot_id: str) -> str:
    return f"datasets/{snapshot_id.strip()}/X.parquet"


def y_parquet_oss_key(snapshot_id: str) -> str:
    return f"datasets/{snapshot_id.strip()}/y.parquet"


def _flatten_x_row(row: dict[str, Any]) -> dict[str, Any]:
    x = row.get("x_json") or {}
    schema = str(x.get("schema") or "")
    rec: dict[str, Any] = {
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "variant_id": row.get("variant_id") or "base",
        "source_row_key": row.get("source_row_key"),
        "x_schema": schema,
        "dim": None,
        "model_version": None,
        "aggregation_method": None,
        "vector": None,
        "x_json": None,
    }
    if schema == "clip_embedding_v1":
        vec = x.get("vector")
        rec["dim"] = x.get("dim")
        rec["model_version"] = x.get("model_version")
        rec["aggregation_method"] = x.get("aggregation_method")
        rec["vector"] = list(vec) if vec is not None else None
    else:
        rec["x_json"] = json.dumps(x, ensure_ascii=False)
        if schema == "frame_embeddings_v1":
            items = x.get("items") or []
            rec["dim"] = len(items)
    return rec


def _collect_label_keys(rows: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for row in rows:
        y = row.get("y_json") or {}
        if isinstance(y, dict):
            keys.update(str(k) for k in y.keys())
    return sorted(keys)


def _flatten_y_row(row: dict[str, Any], label_keys: list[str]) -> dict[str, Any]:
    y = row.get("y_json") or {}
    if not isinstance(y, dict):
        y = {}
    rec: dict[str, Any] = {
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "variant_id": row.get("variant_id") or "base",
        "source_row_key": row.get("source_row_key"),
        "taxonomy_version_id": row.get("taxonomy_version_id"),
        "taxonomy_version_code": row.get("taxonomy_version_code"),
        "y_json": json.dumps(y, ensure_ascii=False),
    }
    for key in label_keys:
        col = f"label__{key.replace('.', '__')}"
        val = y.get(key)
        if val is None:
            rec[col] = None
        elif isinstance(val, (str, int, float, bool)):
            rec[col] = val
        else:
            rec[col] = json.dumps(val, ensure_ascii=False)
    return rec


def rows_to_x_parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    records = [_flatten_x_row(row) for row in rows]
    table = pa.Table.from_pylist(records)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def rows_to_y_parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    label_keys = _collect_label_keys(rows)
    records = [_flatten_y_row(row, label_keys) for row in rows]
    table = pa.Table.from_pylist(records)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def export_parquet_artifacts(rows: list[dict[str, Any]]) -> dict[str, bytes] | None:
    """Return X/y parquet bytes, or None if pyarrow unavailable."""
    if not rows or not is_parquet_available():
        return None
    return {
        "x": rows_to_x_parquet_bytes(rows),
        "y": rows_to_y_parquet_bytes(rows),
    }
