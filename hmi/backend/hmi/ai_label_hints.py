"""Per-label AI confidence / evidence hints for human review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.data_source import artifact_path


def extract_label_hints(raw_labels: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build {label_id: {confidence?, evidence?}} from OMS-style label entries."""
    if not isinstance(raw_labels, dict):
        return {}
    hints: dict[str, dict[str, Any]] = {}
    for lid, entry in raw_labels.items():
        if not isinstance(entry, dict):
            continue
        hint: dict[str, Any] = {}
        conf = entry.get("confidence")
        if conf is not None:
            try:
                hint["confidence"] = float(conf)
            except (TypeError, ValueError):
                pass
        evidence = entry.get("evidence")
        if evidence is not None and str(evidence).strip():
            hint["evidence"] = str(evidence).strip()
        if hint:
            hints[str(lid)] = hint
    return hints


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def load_ai_label_hints_local(clip_id: str, run_id: str) -> dict[str, dict[str, Any]]:
    """Load hints from labels.jsonl, ai/label_hints.json, or legacy labels_merged."""
    labels_path = artifact_path(clip_id, run_id, "labels.jsonl")
    if labels_path.is_file():
        try:
            for line in labels_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    hints = extract_label_hints(row.get("labels") if isinstance(row.get("labels"), dict) else None)
                    if hints:
                        return hints
                    break
        except (json.JSONDecodeError, OSError):
            pass

    dedicated = _read_json(artifact_path(clip_id, run_id, "ai/label_hints.json"))
    if dedicated:
        out: dict[str, dict[str, Any]] = {}
        for lid, entry in dedicated.items():
            if isinstance(entry, dict):
                out[str(lid)] = dict(entry)
        if out:
            return out

    merged = _read_json(artifact_path(clip_id, run_id, "ai/labels_merged.json"))
    if not merged:
        merged = _read_json(artifact_path(clip_id, run_id, "ai/labels.json"))
    if merged:
        embedded = merged.get("label_hints")
        if isinstance(embedded, dict):
            return {
                str(lid): dict(entry)
                for lid, entry in embedded.items()
                if isinstance(entry, dict)
            }
    return {}


def write_ai_label_hints_local(
    clip_id: str,
    run_id: str,
    hints: dict[str, dict[str, Any]],
) -> None:
    if not hints:
        return
    path = artifact_path(clip_id, run_id, "ai/label_hints.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hints, ensure_ascii=False, indent=2), encoding="utf-8")
