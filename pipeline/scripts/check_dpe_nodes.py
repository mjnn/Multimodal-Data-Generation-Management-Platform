#!/usr/bin/env python3
"""Guardrail: DataWorks DPE nodes must not use unpickle-safe custom types.

MaxFrame serializes UDFs to DPE workers; user-defined classes/dataclasses in
dataworks/*_node.py fail with errors like:
  AttributeError: Can't get attribute 'Foo.__init__' on <module '__main__' ...>

Run before paste/deploy: python scripts/check_dpe_nodes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
NODE_GLOB = "dataworks/*_node.py"

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dataclass decorator", re.compile(r"^\s*@dataclass\b", re.MULTILINE)),
    ("dataclasses import", re.compile(r"^\s*from dataclasses import\b", re.MULTILINE)),
    ("user-defined class", re.compile(r"^\s*class\s+[A-Za-z_]\w*\s*[:\(]", re.MULTILINE)),
    ("NamedTuple", re.compile(r"^\s*(class\s+\w+\(NamedTuple\)|\w+\s*=\s*namedtuple\()", re.MULTILINE)),
    ("Enum subclass", re.compile(r"^\s*class\s+\w+\(.*Enum.*\)\s*:", re.MULTILINE)),
]


def check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    for label, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = match.group(0).strip()
            issues.append(f"{path.relative_to(PIPELINE_ROOT)}:{line_no}: {label}: {snippet}")
    return issues


def main() -> int:
    node_files = sorted(PIPELINE_ROOT.glob(NODE_GLOB))
    if not node_files:
        print(f"No files matched {NODE_GLOB}", file=sys.stderr)
        return 1

    all_issues: list[str] = []
    for path in node_files:
        all_issues.extend(check_file(path))

    if all_issues:
        print("DPE node pickle safety check FAILED:", file=sys.stderr)
        for issue in all_issues:
            print(f"  {issue}", file=sys.stderr)
        print(
            "\nFix: UDF code paths must use dict/list/builtins only; "
            "no dataclass or custom class in dataworks/*_node.py",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(node_files)} DPE node file(s) passed pickle-safety check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
