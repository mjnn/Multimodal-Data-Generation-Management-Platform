"""Label search + similarity — local SQLite (clip-centric)."""

from __future__ import annotations

from typing import Any

from hmi.clip_facts import (
    get_clip_embedding_row,
    get_clip_label_view,
    resolve_clip_thumbnail,
    resolve_ds_for_run,
)
from hmi.labels_util import (
    label_value_ids,
    labels_preview,
    match_labels,
    parse_labels_json,
)
from hmi.local import assets, store
from hmi.local.clip_context import resolve_clip_context
from hmi.services.clips import composite_id, parse_composite_id
from hmi.services.search import LABEL_KEYWORDS
from hmi.vec import parse_embedding, similar_filtered

_labeled_clips_cache: list[dict[str, Any]] | None = None


def labeled_clips_cache_clear() -> None:
    global _labeled_clips_cache
    _labeled_clips_cache = None


def labeled_frames_cache_clear() -> None:
    labeled_clips_cache_clear()


def get_label_taxonomy(version_id: str | None = None) -> list[dict[str, Any]]:
    from hmi.taxonomy.compat import get_label_taxonomy as get_taxonomy_compat

    return get_taxonomy_compat(version_id)


def get_label_suggestions() -> list[str]:
    tokens: set[str] = set(LABEL_KEYWORDS)
    clip_rows = store.query(
        """
        SELECT labels_json FROM fact_clip_label
        WHERE labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        """
    )
    for row in clip_rows:
        preview = labels_preview(parse_labels_json(row.get("labels_json")))
        for part in preview.replace("，", ",").split(","):
            t = part.strip()
            if t:
                tokens.add(t)
    if not clip_rows:
        frame_rows = store.query(
            "SELECT labels_json FROM fact_image_label WHERE labels_json IS NOT NULL AND labels_json != ''"
        )
        for row in frame_rows:
            preview = labels_preview(parse_labels_json(row.get("labels_json")))
            for part in preview.replace("，", ",").split(","):
                t = part.strip()
                if t:
                    tokens.add(t)
    return sorted(tokens)[:40]


def _load_labeled_clips() -> list[dict[str, Any]]:
    global _labeled_clips_cache
    if _labeled_clips_cache is not None:
        return _labeled_clips_cache

    pairs = store.query(
        """
        SELECT DISTINCT clip_id, run_id FROM fact_clip_label
        WHERE labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        UNION
        SELECT DISTINCT clip_id, run_id FROM fact_image_label
        WHERE labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        """
    )
    out: list[dict[str, Any]] = []
    for pair in pairs:
        clip_id = str(pair["clip_id"])
        run_id = str(pair["run_id"])
        try:
            ds = resolve_ds_for_run(clip_id, run_id)
        except ValueError:
            continue
        view = get_clip_label_view(clip_id, run_id, ds=ds)
        if not view.get("clip_label_ready"):
            continue
        thumb = resolve_clip_thumbnail(
            clip_id,
            run_id,
            ds,
            view.get("anchor_timestamp_ns"),
        )
        if not thumb:
            continue
        camera = str(thumb["camera"])
        frame_idx = int(thumb["frame_idx"])
        labels_json = view.get("labels_json") or {}
        preview = str(view.get("label_preview") or "")
        out.append(
            {
                "clip_id": clip_id,
                "run_id": run_id,
                "camera": camera,
                "frame_idx": frame_idx,
                "timestamp_ns": int(view.get("anchor_timestamp_ns") or thumb["timestamp_ns"]),
                "image_path": str(thumb["image_path"]),
                "labels_json": labels_json,
                "label_preview": preview,
                "label_granularity": view.get("label_granularity") or "clip",
                "source": view.get("source"),
            }
        )
    _labeled_clips_cache = out
    return _labeled_clips_cache


def _match_clip_labels(
    labels_json: dict[str, Any],
    *,
    keyword: str = "",
    label_id: str | None = None,
) -> bool:
    if not labels_json:
        return False
    if "values" in labels_json:
        return match_labels(labels_json, keyword=keyword, label_id=label_id)
    wrapped = {"values": {k: {"value": v} for k, v in labels_json.items()}}
    return match_labels(wrapped, keyword=keyword, label_id=label_id)


def search_labels(keyword: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for row in _load_labeled_clips():
        labels_json = row.get("labels_json") or {}
        if not _match_clip_labels(labels_json, keyword=keyword):
            continue
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        camera = str(row["camera"])
        frame_idx = int(row["frame_idx"])
        labels_json = row.get("labels_json") or {}
        preview = str(row.get("label_preview") or labels_preview(labels_json))
        items.append(
            {
                "composite_id": composite_id(clip_id, run_id, camera, frame_idx),
                "clip_id": clip_id,
                "run_id": run_id,
                "camera": camera,
                "frame_idx": frame_idx,
                "timestamp_ns": int(row["timestamp_ns"]),
                "preview_url": assets.local_image_url(
                    clip_id, run_id, str(row["image_path"])
                ),
                "label_text": preview,
                "label_ids": list(labels_json.keys()) if isinstance(labels_json, dict) else label_value_ids(labels_json),
                "status": "success",
                "label_granularity": row.get("label_granularity") or "clip",
                "is_clip_label": True,
            }
        )
    total = len(items)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size, "items": items[start : start + page_size]}


def search_label_clusters(keyword: str, label_id: str | None = None) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in _load_labeled_clips():
        labels_json = row.get("labels_json") or {}
        if not _match_clip_labels(labels_json, keyword=keyword, label_id=label_id):
            continue
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        hits.append(
            {
                "cluster_id": f"{clip_id}|{run_id}",
                "clip_id": clip_id,
                "run_id": run_id,
                "timestamp_ns": int(row["timestamp_ns"]),
                "timestamp_end_ns": int(row["timestamp_ns"]),
                "camera": str(row["camera"]),
                "cameras": [str(row["camera"])],
                "preview_url": assets.local_image_url(
                    clip_id, run_id, str(row["image_path"])
                ),
                "label_texts": [str(row.get("label_preview") or "")],
                "hit_count": 1,
                "label_granularity": row.get("label_granularity") or "clip",
                "is_clip_label": True,
            }
        )
    return hits


def find_similar(composite_id_str: str, top_k: int = 8, min_score: float = 0.75) -> list[dict[str, Any]]:
    clip_id, run_id, camera, frame_idx = parse_composite_id(composite_id_str)
    ctx = resolve_clip_context(clip_id, run_id)
    cid, rid, ds = ctx.clip_id, ctx.run_id, ctx.ds

    clip_emb = get_clip_embedding_row(cid, rid, ds=ds)
    if clip_emb:
        query_vec = parse_embedding(str(clip_emb.get("vector_json")))
        if query_vec is not None:
            candidates: list[dict[str, Any]] = []
            rows = store.query(
                """
                SELECT e.clip_id, e.run_id, e.vector_json, l.labels_json, l.anchor_timestamp_ns
                FROM fact_clip_embedding e
                LEFT JOIN fact_clip_label l
                  ON e.clip_id=l.clip_id AND e.run_id=l.run_id AND e.ds=l.ds
                WHERE e.ds=?
                """,
                (ds,),
            )
            for row in rows:
                other_clip = str(row["clip_id"])
                other_run = str(row["run_id"])
                if other_clip == cid and other_run == rid:
                    continue
                vec = parse_embedding(str(row.get("vector_json")))
                if vec is None:
                    continue
                try:
                    other_ds = resolve_ds_for_run(other_clip, other_run)
                except ValueError:
                    continue
                thumb = resolve_clip_thumbnail(
                    other_clip,
                    other_run,
                    other_ds,
                    int(row["anchor_timestamp_ns"])
                    if row.get("anchor_timestamp_ns") not in (None, "")
                    else None,
                )
                if not thumb:
                    continue
                cam = str(thumb["camera"])
                idx = int(thumb["frame_idx"])
                lj = parse_labels_json(row.get("labels_json"))
                preview = labels_preview(lj) if lj else ""
                candidates.append(
                    {
                        "composite_id": composite_id(other_clip, other_run, cam, idx),
                        "clip_id": other_clip,
                        "camera": cam,
                        "timestamp_ns": int(thumb["timestamp_ns"]),
                        "preview_url": assets.local_image_url(
                            other_clip, other_run, str(thumb["image_path"])
                        ),
                        "label_text": preview,
                        "_vec": vec,
                    }
                )
            scored = similar_filtered(query_vec, candidates, min_score=min_score, top_k=top_k)
            return [
                {
                    "composite_id": item["composite_id"],
                    "clip_id": item["clip_id"],
                    "camera": item["camera"],
                    "timestamp_ns": item["timestamp_ns"],
                    "preview_url": item["preview_url"],
                    "label_text": item["label_text"],
                    "score": round(score, 4),
                }
                for item, score in scored
            ]

    object_id = f"{camera}:{frame_idx}"
    src = store.query_one(
        "SELECT vector_json FROM fact_embedding "
        "WHERE clip_id=? AND run_id=? AND ds=? AND object_type='frame' AND object_id=? LIMIT 1",
        (cid, rid, ds, object_id),
    )
    if not src:
        return []
    query_vec = parse_embedding(str(src.get("vector_json")))
    if query_vec is None:
        return []
    emb_rows = store.query(
        "SELECT object_id, timestamp_ns, vector_json FROM fact_embedding "
        "WHERE clip_id=? AND run_id=? AND ds=? AND object_type='frame'",
        (cid, rid, ds),
    )
    other_ids = [str(r["object_id"]) for r in emb_rows if str(r["object_id"]) != object_id]
    if not other_ids:
        return []
    placeholders = ",".join("?" for _ in other_ids)
    frame_rows = store.query(
        f"SELECT camera, frame_idx, image_path FROM fact_frame "
        f"WHERE clip_id=? AND run_id=? AND ds=? "
        f"AND (camera || ':' || frame_idx) IN ({placeholders})",
        (cid, rid, ds, *other_ids),
    )
    view = get_clip_label_view(cid, rid, ds=ds)
    preview = str(view.get("label_preview") or "")
    frame_by_oid = {f"{str(r['camera'])}:{int(r['frame_idx'])}": r for r in frame_rows}
    candidates = []
    for r in emb_rows:
        oid = str(r["object_id"])
        if oid == object_id:
            continue
        vec = parse_embedding(str(r.get("vector_json")))
        if vec is None:
            continue
        fr = frame_by_oid.get(oid)
        if not fr:
            continue
        cam, _, idx_s = oid.partition(":")
        idx = int(idx_s)
        candidates.append(
            {
                "composite_id": composite_id(ctx.clip_id, ctx.run_id, cam, idx),
                "clip_id": ctx.clip_id,
                "camera": cam,
                "timestamp_ns": int(r["timestamp_ns"]),
                "preview_url": assets.local_image_url(
                    ctx.clip_id, ctx.run_id, str(fr["image_path"])
                ),
                "label_text": preview,
                "_vec": vec,
            }
        )
    scored = similar_filtered(query_vec, candidates, min_score=min_score, top_k=top_k)
    return [
        {
            "composite_id": item["composite_id"],
            "clip_id": item["clip_id"],
            "camera": item["camera"],
            "timestamp_ns": item["timestamp_ns"],
            "preview_url": item["preview_url"],
            "label_text": item["label_text"],
            "score": round(score, 4),
        }
        for item, score in scored
    ]
