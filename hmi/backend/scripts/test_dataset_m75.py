"""M7.5 smoke test: optional Parquet export."""

from __future__ import annotations

import io
import json
import os
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from hmi.dataset.assemble import assemble_snapshot_rows
from hmi.dataset.export import export_xy_to_oss
from hmi.dataset.parquet_export import (
    FEATURE_PARQUET_NAME,
    TARGET_PARQUET_NAME,
    export_parquet_artifacts,
    is_parquet_available,
    rows_to_x_parquet_bytes,
    rows_to_y_parquet_bytes,
)

_uploads: dict[str, bytes | str] = {}


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _mock_put_object_bytes(key: str, payload: bytes, *, content_type: str = "application/octet-stream") -> None:
    _uploads[key.lstrip("/")] = payload


def main() -> None:
    if not is_parquet_available():
        print("SKIP: pyarrow not installed")
        return

    rows = [
        {
            "clip_id": "sha256:abc",
            "run_id": str(uuid.uuid4()),
            "x_json": {
                "schema": "clip_embedding_v1",
                "vector": [1.0, 0.0, 0.5],
                "dim": 3,
                "model_version": "test-v1",
            },
            "y_json": {"L1.1.day_period": "night", "L1.2.weather": "rain"},
            "taxonomy_version_id": "tax-1",
            "taxonomy_version_code": "v1",
        }
    ]

    x_bytes = rows_to_x_parquet_bytes(rows)
    y_bytes = rows_to_y_parquet_bytes(rows)
    assert len(x_bytes) > 0 and len(y_bytes) > 0
    print("OK parquet bytes generated")

    artifacts = export_parquet_artifacts(rows)
    assert artifacts and "x" in artifacts and "y" in artifacts
    print("OK export_parquet_artifacts")

    from hmi.dataset.assemble import AssemblyResult

    assembly = AssemblyResult(rows=rows, clip_count=1, line_count=1)
    _uploads.clear()
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text), patch(
        "hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes
    ):
        info = export_xy_to_oss(
            str(uuid.uuid4()),
            assembly,
            export_preset="minimal",
            filter_snapshot={"include_parquet": True},
        )
    assert info["parquet_available"] is True
    pkg = _uploads.get(info["package_key"])
    assert isinstance(pkg, bytes)
    with zipfile.ZipFile(io.BytesIO(pkg)) as zf:
        names = set(zf.namelist())
        assert FEATURE_PARQUET_NAME in names
        assert TARGET_PARQUET_NAME in names
        meta = json.loads(zf.read("meta.json").decode("utf-8"))
        assert meta.get("parquet_available") is True
        assert meta.get("include_parquet") is True
    print("OK export_xy_to_oss with include_parquet")

    print("\nM7.5 backend tests passed.")


if __name__ == "__main__":
    main()
