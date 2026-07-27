# =============================================================================
# Job4_label_merge_and_compare — 双模型标签比对合并
#
# 输入：ai/labels_primary.json + ai/labels_secondary.json
# 输出：ai/labels_merged.json · ai/consensus_meta.json · ai/labels.json（兼容别名）
#
# 规则：
#   - clip 一致率 >= threshold → 合并；字段不一致以 job2（primary）为准
#   - clip 一致率 < threshold → 争议字段留空待人工；校核页高亮
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from label_merge import merge_from_label_docs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_merge_artifacts(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    primary_doc: dict[str, Any],
    secondary_doc: dict[str, Any],
    threshold: float = 0.7,
    taxonomy_version_id: str | None = None,
) -> dict[str, str]:
    merged_flat, multi_ai_meta = merge_from_label_docs(
        primary_doc,
        secondary_doc,
        threshold=threshold,
    )
    gate = multi_ai_meta.get("gate") or {}

    ai_dir = run_root / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)

    merged_doc = {
        "clip_id": clip_id,
        "run_id": run_id,
        "label_source": "ai_merged",
        "labels_json": merged_flat,
        "multi_ai_meta": multi_ai_meta,
        "gate_passed": bool(gate.get("passed")),
        "clip_agreement": gate.get("clip_score"),
        "agreement_threshold": threshold,
        "taxonomy_version_id": taxonomy_version_id,
        "created_at": utc_now(),
    }
    consensus_doc = {
        "clip_id": clip_id,
        "run_id": run_id,
        "multi_ai_meta": multi_ai_meta,
        "disputed_label_ids": multi_ai_meta.get("disputed_label_ids") or [],
        "gate_passed": bool(gate.get("passed")),
        "created_at": utc_now(),
    }

    paths = {
        "labels_merged": ai_dir / "labels_merged.json",
        "consensus_meta": ai_dir / "consensus_meta.json",
        "labels_alias": ai_dir / "labels.json",
    }
    merged_text = json.dumps(merged_doc, ensure_ascii=False, indent=2)
    paths["labels_merged"].write_text(merged_text, encoding="utf-8")
    paths["consensus_meta"].write_text(
        json.dumps(consensus_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["labels_alias"].write_text(merged_text, encoding="utf-8")

    return {k: str(v) for k, v in paths.items()}


def merge_from_run_artifacts(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    threshold: float = 0.7,
    taxonomy_version_id: str | None = None,
) -> dict[str, str]:
    primary_path = run_root / "ai" / "labels_primary.json"
    secondary_path = run_root / "ai" / "labels_secondary.json"
    if not primary_path.is_file() or not secondary_path.is_file():
        raise FileNotFoundError(
            f"missing primary/secondary labels under {run_root / 'ai'}"
        )
    return write_merge_artifacts(
        run_root,
        clip_id=clip_id,
        run_id=run_id,
        primary_doc=_read_json(primary_path),
        secondary_doc=_read_json(secondary_path),
        threshold=threshold,
        taxonomy_version_id=taxonomy_version_id,
    )


def main() -> None:
    print("job4_label_merge_and_compare: merge_from_run_artifacts() after both labelings")


if __name__ == "__main__":
    main()
