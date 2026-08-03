"""Parse an aug_recipe spec and print transform plan (platform does not execute)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate_recipe(spec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not spec.get("recipe_schema_version"):
        errors.append("missing recipe_schema_version")
    if not spec.get("recipe_code"):
        errors.append("missing recipe_code")
    transforms = spec.get("transforms")
    if not isinstance(transforms, list) or not transforms:
        errors.append("transforms must be a non-empty list")
    else:
        for i, t in enumerate(transforms):
            if not isinstance(t, dict):
                errors.append(f"transforms[{i}] must be object")
                continue
            if not t.get("id"):
                errors.append(f"transforms[{i}] missing id")
            if not t.get("type"):
                errors.append(f"transforms[{i}] missing type")
            if not t.get("targets"):
                errors.append(f"transforms[{i}] missing targets")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse aug_recipe spec (training-side reference)")
    parser.add_argument("recipe_path", type=Path, help="Path to recipe JSON/YAML-like JSON file")
    args = parser.parse_args()

    path = args.recipe_path
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 1

    raw = path.read_text(encoding="utf-8")
    spec = json.loads(raw)
    if not isinstance(spec, dict):
        print("recipe must be a JSON object", file=sys.stderr)
        return 1

    errors = validate_recipe(spec)
    if errors:
        print("validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("=== aug_recipe ===")
    print(f"  recipe_code: {spec.get('recipe_code')}")
    print(f"  version:     {spec.get('version')}")
    print(f"  schema:      {spec.get('recipe_schema_version')}")
    applies = spec.get("applies_to") or {}
    print(f"  export_preset: {applies.get('export_preset', 'any')}")
    print(f"  modalities:    {applies.get('modalities', [])}")

    print("\n=== transforms (training-side must implement) ===")
    for t in spec.get("transforms") or []:
        tid = t.get("id", "?")
        ttype = t.get("type", "?")
        prob = t.get("p", 1.0)
        targets = t.get("targets") or []
        print(f"  - {tid}: type={ttype} p={prob} targets={len(targets)}")

    seed = spec.get("seed_policy") or {}
    if seed:
        print(f"\nseed_policy: mode={seed.get('mode')} base_seed={seed.get('base_seed')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
