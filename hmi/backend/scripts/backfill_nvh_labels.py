"""Check and optionally backfill NVH labels on existing audio_array_spec runs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))

os.environ.setdefault("HMI_DATA_SOURCE", "local")
os.environ.setdefault(
    "HMI_RUNTIME_ROOT",
    str(REPO / "hmi" / "data" / "hmi_runtime"),
)


def main() -> int:
    from hmi.data_source import LOCAL_ROOT, artifacts_dir
    from hmi.local import store as ls
    from hmi.local.nvh_ai_label import fill_nvh_semantic_labels
    from hmi.local.nvh_deriver import (
        apply_nvh_labels_to_facts,
        derive_nvh_labels,
        persist_nvh_labels_artifact,
    )
    from hmi.platform.recipe import seed_recipes
    from hmi.platform.store import get_run
    from hmi.taxonomy_db import get_version_by_code

    print("LOCAL_ROOT", LOCAL_ROOT)
    rows = ls.query(
        """
        SELECT pe.run_id, pe.data_type_id, pr.clip_id, pr.status, pr.ds
        FROM pipeline_execution pe
        JOIN pipeline_run pr ON pr.run_id = pe.run_id
        WHERE pe.data_type_id = 'audio_array_spec'
        ORDER BY pe.created_at DESC
        """
    )
    print("audio_array_spec runs:", len(rows))
    recipe = seed_recipes()["audio_array_spec"]
    tax = get_version_by_code("audio_nvh-v2")
    print("audio_nvh-v2", None if not tax else tax["status"], None if not tax else tax["id"])

    do_backfill = "--backfill" in sys.argv
    for row in rows:
        run_id = row["run_id"]
        clip_id = row["clip_id"]
        ds = str(row.get("ds") or "")
        art = artifacts_dir(clip_id, run_id)
        plat = get_run(run_id)
        fact = ls.query_one(
            "SELECT labels_json FROM fact_clip_label WHERE clip_id=? AND run_id=?",
            (clip_id, run_id),
        )
        y_keys = list((plat or {}).get("y") or {})
        fact_keys = list(json.loads(fact["labels_json"])) if fact and fact["labels_json"] else []
        nvh_path = art / "nvh_labels.json"
        print(
            f"- clip={clip_id[:20]}… run={run_id[:8]}… "
            f"art={art.is_dir()} nvh_file={nvh_path.is_file()} "
            f"y={len(y_keys)} fact={len(fact_keys)} "
            f"sem={[k for k in fact_keys if k.startswith('nvh.sem.')][:4]}"
        )
        if not do_backfill:
            continue
        if not art.is_dir() or not (art / "audio_spec").is_dir():
            print("  skip: no audio_spec artifacts")
            continue
        labels = derive_nvh_labels(art)
        label_stage = (recipe.get("stages") or {}).get("label") or {}
        if bool(label_stage.get("enabled", True)):
            labels = fill_nvh_semantic_labels(
                art,
                labels,
                model=str(label_stage.get("model") or "nvh_sem_heuristic"),
            )
        persist_nvh_labels_artifact(art, labels)
        apply_nvh_labels_to_facts(
            clip_id=clip_id,
            run_id=run_id,
            ds=ds,
            labels=labels,
        )
        print(
            f"  backfilled keys={len(labels)} "
            f"sem={[k for k in labels if k.startswith('nvh.sem.')]}"
        )
    if not do_backfill:
        print("\n(re-run with --backfill to write labels onto existing artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
