"""Load a minimal dataset snapshot zip and print X/y shape summary."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


def _load_jsonl(zf: zipfile.ZipFile, name: str) -> list[dict[str, Any]]:
    try:
        raw = zf.read(name).decode("utf-8")
    except KeyError:
        return []
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def summarize_x(row: dict[str, Any]) -> str:
    x = row.get("x_json") or {}
    schema = x.get("schema", "unknown")
    if schema == "clip_embedding_v1":
        vec = x.get("vector") or []
        return f"clip_embedding_v1 dim={len(vec)}"
    if schema == "frame_embeddings_v1":
        items = x.get("items") or []
        return f"frame_embeddings_v1 items={len(items)}"
    return f"{schema}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Load dataset snapshot zip (minimal or full)")
    parser.add_argument("zip_path", type=Path, help="Path to dataset.zip")
    parser.add_argument("--head", type=int, default=3, help="Print first N rows summary")
    args = parser.parse_args()

    path = args.zip_path
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        meta: dict[str, Any] = {}
        if "meta.json" in names:
            meta = json.loads(zf.read("meta.json").decode("utf-8"))

        feature_name = "特征.jsonl"
        target_name = "目标.jsonl"
        x_rows = _load_jsonl(zf, feature_name)
        y_rows = _load_jsonl(zf, target_name)

        parsed_binary = [n for n in names if n.startswith("clips/") and "/parsed/" in n]

        print("=== meta.json ===")
        print(f"  schema_version: {meta.get('schema_version')}")
        print(f"  export_preset:  {meta.get('export_preset')}")
        print(f"  clip_count:     {meta.get('clip_count')}")
        print(f"  line_count:     {meta.get('line_count')}")
        print(f"  augmentation:   {meta.get('augmentation_mode', 'none')}")

        print("\n=== manifest ===")
        print(f"  feature rows: {len(x_rows)}")
        print(f"  target rows:  {len(y_rows)}")
        print(f"  parsed binaries in zip: {len(parsed_binary)}")

        for i, row in enumerate(x_rows[: args.head]):
            y = y_rows[i]["y_json"] if i < len(y_rows) else {}
            variant = row.get("variant_id", "base")
            print(f"\n  row {i}: clip={row.get('clip_id', '')[:24]}… variant={variant}")
            print(f"    X: {summarize_x(row)}")
            print(f"    y keys: {list((y or {}).keys())[:5]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
