"""Load clip-omni v2 AI artifacts (multi-model labels + embedding)."""



from __future__ import annotations



import json

from pathlib import Path

from typing import Any



from hmi.clip_facts import upsert_clip_embedding, upsert_clip_label

from hmi.data_source import artifact_path

from hmi.labels_util import labels_to_clip_dict

from hmi.oss_paths import (

    clip_ai_consensus_meta_key,

    clip_ai_embedding_key,

    clip_ai_labels_key,

    clip_ai_labels_merged_key,

)

from hmi.oss_signer import get_object_json, put_object_text

from hmi.vec import parse_embedding





def _read_json_file(path: Path) -> dict[str, Any] | None:

    if not path.is_file():

        return None

    try:

        loaded = json.loads(path.read_text(encoding="utf-8"))

    except (json.JSONDecodeError, OSError):

        return None

    return loaded if isinstance(loaded, dict) else None





def _merged_labels_path(clip_id: str, run_id: str) -> Path:

    merged = artifact_path(clip_id, run_id, "ai/labels_merged.json")

    if merged.is_file():

        return merged

    return artifact_path(clip_id, run_id, "ai/labels.json")





def load_ai_labels_local(clip_id: str, run_id: str) -> dict[str, Any] | None:

    return _read_json_file(_merged_labels_path(clip_id, run_id))





def load_ai_consensus_local(clip_id: str, run_id: str) -> dict[str, Any] | None:

    doc = _read_json_file(artifact_path(clip_id, run_id, "ai/consensus_meta.json"))

    if doc:

        return doc

    labels = load_ai_labels_local(clip_id, run_id)

    if labels and labels.get("multi_ai_meta"):

        return {"multi_ai_meta": labels["multi_ai_meta"]}

    return None





def load_ai_embedding_local(clip_id: str, run_id: str) -> dict[str, Any] | None:

    return _read_json_file(artifact_path(clip_id, run_id, "ai/embedding.json"))





def load_ai_labels_oss(clip_id: str, run_id: str) -> dict[str, Any] | None:

    doc = get_object_json(clip_ai_labels_merged_key(clip_id, run_id))

    if doc:

        return doc

    return get_object_json(clip_ai_labels_key(clip_id, run_id))





def load_ai_embedding_oss(clip_id: str, run_id: str) -> dict[str, Any] | None:

    return get_object_json(clip_ai_embedding_key(clip_id, run_id))





def ingest_ai_labels_doc(

    doc: dict[str, Any],

    *,

    clip_id: str,

    run_id: str,

    ds: str,

) -> None:

    labels = doc.get("labels_json")

    if labels is None and doc.get("labels"):

        labels = doc["labels"]

    if not isinstance(labels, dict):

        return

    multi_ai = doc.get("multi_ai_meta")

    if multi_ai is None:

        consensus = _read_json_file(

            artifact_path(clip_id, run_id, "ai/consensus_meta.json")

        )

        if consensus:

            multi_ai = consensus.get("multi_ai_meta")

    upsert_clip_label(

        clip_id,

        run_id,

        ds=ds,

        labels_json=labels_to_clip_dict(labels) if labels else labels,

        taxonomy_version_id=str(doc.get("taxonomy_version_id") or "") or None,

        model_version=str(doc.get("model_version") or "") or None,

        label_source=str(doc.get("label_source") or "ai"),

        multi_ai_meta_json=multi_ai,

    )





def ingest_ai_embedding_doc(

    doc: dict[str, Any],

    *,

    clip_id: str,

    run_id: str,

    ds: str,

) -> None:

    vec = doc.get("vector")

    if vec is None:

        vec = parse_embedding(str(doc.get("vector_json") or ""))

    else:

        parsed = parse_embedding(vec)

        vec = parsed.tolist() if parsed is not None else None

    if not vec:

        return

    upsert_clip_embedding(

        clip_id,

        run_id,

        ds=ds,

        vector=list(vec),

        model_version=str(doc.get("model_version") or "") or None,

        aggregation_method=str(doc.get("aggregation_method") or "clip_omni"),

    )





def ingest_v2_ai_from_local_artifacts(clip_id: str, run_id: str, ds: str) -> dict[str, bool]:

    from hmi.sdk_ingest import ingest_sdk_run_local, sdk_bundle_present

    if sdk_bundle_present(clip_id, run_id):
        return ingest_sdk_run_local(clip_id, run_id, ds)

    labels_doc = load_ai_labels_local(clip_id, run_id)

    embed_doc = load_ai_embedding_local(clip_id, run_id)

    if labels_doc:

        ingest_ai_labels_doc(labels_doc, clip_id=clip_id, run_id=run_id, ds=ds)

    if embed_doc:

        ingest_ai_embedding_doc(embed_doc, clip_id=clip_id, run_id=run_id, ds=ds)

    return {"labels": bool(labels_doc), "embedding": bool(embed_doc)}





def write_ai_labels_oss(

    clip_id: str,

    run_id: str,

    *,

    labels_json: dict[str, Any],

    taxonomy_version_id: str | None = None,

    model_version: str | None = None,

    multi_ai_meta: dict[str, Any] | None = None,

) -> str:

    key = clip_ai_labels_merged_key(clip_id, run_id)

    body = json.dumps(

        {

            "clip_id": clip_id,

            "run_id": run_id,

            "label_source": "ai_merged",

            "taxonomy_version_id": taxonomy_version_id,

            "model_version": model_version,

            "labels_json": labels_json,

            "multi_ai_meta": multi_ai_meta,

        },

        ensure_ascii=False,

        indent=2,

    )

    put_object_text(key, body, content_type="application/json")

    put_object_text(clip_ai_labels_key(clip_id, run_id), body, content_type="application/json")

    return key





def write_ai_embedding_oss(

    clip_id: str,

    run_id: str,

    *,

    vector: list[float],

    model_version: str | None = None,

    aggregation_method: str = "clip_omni",

) -> str:

    key = clip_ai_embedding_key(clip_id, run_id)

    body = json.dumps(

        {

            "clip_id": clip_id,

            "run_id": run_id,

            "dim": len(vector),

            "model_version": model_version,

            "aggregation_method": aggregation_method,

            "vector": vector,

        },

        ensure_ascii=False,

        indent=2,

    )

    put_object_text(key, body, content_type="application/json")

    return key


