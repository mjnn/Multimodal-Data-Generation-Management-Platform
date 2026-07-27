#!/usr/bin/env python3
"""Bundle helpers + DataWorks node for PyODPS paste."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
OUT_DIR = PIPELINE_ROOT / "dataworks" / "bundled"
FUTURE_IMPORT = "from __future__ import annotations"

HELPER_IMPORTS = (
    re.compile(
        r"^from (?:mf_ai_function|mc_write_idempotent|pipeline_dispatch|oms_time_labels|sample_sync) import \([\s\S]*?\)\s*",
        re.MULTILINE,
    ),
    re.compile(
        r"^from (?:mf_ai_function|mc_write_idempotent|pipeline_dispatch|oms_time_labels|sample_sync) import .+$",
        re.MULTILINE,
    ),
)

HELPER_FILES: tuple[tuple[str, Path, str, str], ...] = (
    (
        "mf_ai_function.py",
        PIPELINE_ROOT / "dataworks" / "mf_ai_function.py",
        "# === BEGIN mf_ai_function.py (auto-bundled) ===",
        "# === END mf_ai_function.py ===",
    ),
    (
        "mc_write_idempotent.py",
        PIPELINE_ROOT / "dataworks" / "mc_write_idempotent.py",
        "# === BEGIN mc_write_idempotent.py (auto-bundled) ===",
        "# === END mc_write_idempotent.py ===",
    ),
    (
        "pipeline_dispatch.py",
        PIPELINE_ROOT / "dataworks" / "pipeline_dispatch.py",
        "# === BEGIN pipeline_dispatch.py (auto-bundled) ===",
        "# === END pipeline_dispatch.py ===",
    ),
    (
        "oms_time_labels.py",
        PIPELINE_ROOT / "dataworks" / "oms_time_labels.py",
        "# === BEGIN oms_time_labels.py (auto-bundled) ===",
        "# === END oms_time_labels.py ===",
    ),
    (
        "sample_sync.py",
        PIPELINE_ROOT / "dataworks" / "sample_sync.py",
        "# === BEGIN sample_sync.py (auto-bundled) ===",
        "# === END sample_sync.py ===",
    ),
)


def _strip_future_import(source: str) -> str:
    lines = source.splitlines()
    kept = [line for line in lines if line.strip() != FUTURE_IMPORT]
    return "\n".join(kept).strip("\n")


def _strip_helper_imports(source: str) -> str:
    text = source
    for pattern in HELPER_IMPORTS:
        text = pattern.sub("", text)
    return text.strip("\n")


def bundle(node_path: Path, *, helpers: tuple[str, ...]) -> Path:
    if not node_path.is_file():
        raise SystemExit(f"Missing node: {node_path}")

    node_body = _strip_helper_imports(_strip_future_import(node_path.read_text(encoding="utf-8")))
    blocks: list[str] = [FUTURE_IMPORT, "", f"# {node_path.name} — paste this single file into DataWorks PyODPS3"]

    for helper_file, helper_path, begin, end in HELPER_FILES:
        helper_key = helper_file.removesuffix(".py")
        if helper_key not in helpers:
            continue
        if not helper_path.is_file():
            raise SystemExit(f"Missing helper: {helper_path}")
        if begin in node_body:
            raise SystemExit(f"Already bundled: {node_path}")
        helper_body = _strip_future_import(helper_path.read_text(encoding="utf-8"))
        blocks.extend(["", begin, helper_body, end])

    blocks.extend(["", node_body, ""])
    bundled = "\n".join(blocks)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / node_path.name
    out_path.write_text(bundled, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle DataWorks node helpers")
    parser.add_argument("node", type=Path)
    parser.add_argument(
        "--helpers",
        default="mf_ai_function,pipeline_dispatch,oms_time_labels,sample_sync",
        help="Comma-separated: mf_ai_function,mc_write_idempotent,pipeline_dispatch,oms_time_labels,sample_sync",
    )
    args = parser.parse_args()
    helper_names = tuple(part.strip() for part in args.helpers.split(",") if part.strip())
    out_path = bundle(args.node.resolve(), helpers=helper_names)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
