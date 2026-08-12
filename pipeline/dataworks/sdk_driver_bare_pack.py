# Helpers used by Driver hybrid pack UDF docs / unit tests (logic also inlined in node UDF).

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def path_under_mount_to_oss_key(path: Path | None, mount_path: str | Path) -> str:
    """Map a file under the DPE OSS mount to a bucket-relative object key."""
    if path is None:
        return ""
    try:
        if not path.is_file():
            return ""
    except OSError:
        return ""
    mount = Path(mount_path)
    try:
        resolved = path.resolve()
        mount_resolved = mount.resolve()
        rel = resolved.relative_to(mount_resolved)
    except (OSError, ValueError):
        # Best-effort: strip mount prefix from string form.
        raw = str(path).replace("\\", "/")
        prefix = str(mount).replace("\\", "/").rstrip("/") + "/"
        if raw.startswith(prefix):
            return raw[len(prefix) :].lstrip("/")
        return ""
    return str(rel).replace("\\", "/")


def resolve_under_bases(path_str: str, bases: list[Path]) -> Path | None:
    raw = str(path_str or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p
    for base in bases:
        cand = base / raw
        if cand.is_file():
            return cand
        cand2 = base / raw.lstrip("/\\")
        if cand2.is_file():
            return cand2
    # basename search
    name = Path(raw).name
    for base in bases:
        if not base.exists():
            continue
        for hit in base.rglob(name):
            if hit.is_file():
                return hit
    return None


def find_clip_dir(work: Path, clip_id: str) -> Path | None:
    for hit in work.rglob(clip_id):
        if hit.is_dir() and (hit / "audio.wav").is_file():
            return hit
    return None


def load_asr_map(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "asr.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        row = json.loads(text)
        if not isinstance(row, dict):
            continue
        for key_name in ("sdk_clip_id", "clip_id"):
            key = str(row.get(key_name) or "").strip()
            if key:
                out[key] = row
    return out


def pick_frame_paths(
    *,
    clip_row: dict[str, Any],
    bases: list[Path],
    clip_dir: Path | None,
    limit: int = 4,
    prefer_embedding: bool = False,
) -> list[Path]:
    keys = ("embedding_frames", "frames") if prefer_embedding else ("frames", "embedding_frames")
    paths: list[Path] = []
    for key in keys:
        for fr in clip_row.get(key) or []:
            if not isinstance(fr, dict):
                continue
            resolved = resolve_under_bases(str(fr.get("image_path") or ""), bases)
            if resolved is not None:
                paths.append(resolved)
            if len(paths) >= limit:
                return paths
        if paths:
            return paths[:limit]
    if clip_dir is not None:
        for jpg in sorted(clip_dir.rglob("*.jpg"))[:limit]:
            paths.append(jpg)
    return paths[:limit]
