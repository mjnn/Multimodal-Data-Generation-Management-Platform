"""HMI wrapper for dual-model label merge (shared with DataWorks job4)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
_DATAWORKS = REPO_ROOT / "pipeline" / "dataworks"
if str(_DATAWORKS) not in sys.path:
    sys.path.insert(0, str(_DATAWORKS))

from label_merge import (  # noqa: E402
    flat_label_map,
    merge_dual_model_labels,
    merge_from_label_docs,
)

__all__ = [
    "flat_label_map",
    "merge_dual_model_labels",
    "merge_from_label_docs",
]
