"""Label search, clusters, taxonomy, vector similarity."""



from __future__ import annotations



import json

from typing import Any

from cachetools import TTLCache

from hmi.clip_context import resolve_clip_context

from hmi.config import get_settings, table_name

from hmi.db import query, sql_quote

from hmi.oss_signer import sign_image

from hmi.labels_sync import (
    aggregate_cluster_hits,
    dedupe_search_rows,
    label_row_sync_fields,
    scene_timestamp_ns,
)
from hmi.labels_util import (
    label_value_ids,
    labels_preview,
    match_labels,
    parse_labels_json,
)

from hmi.services.clips import composite_id, parse_composite_id

from hmi.vec import parse_embedding, similar_filtered



LABEL_KEYWORDS = [

    "驾驶", "疲劳", "儿童", "后排", "前排", "闭眼", "打哈欠", "看手机", "交谈", "无人", "夜间", "通勤",

]



_labeled_frames_cache: TTLCache = TTLCache(maxsize=8, ttl=300)





def labeled_frames_cache_clear() -> None:

    _labeled_frames_cache.clear()





def get_label_taxonomy(version_id: str | None = None) -> list[dict[str, Any]]:

    from hmi.taxonomy.compat import get_label_taxonomy as get_taxonomy_compat

    return get_taxonomy_compat(version_id)





def get_label_suggestions() -> list[str]:

    return LABEL_KEYWORDS





def _active_clip_filters() -> list[tuple[str, str, str]]:
    settings = get_settings()
    dim_rows = query(
        f"SELECT clip_id, active_run_id FROM {table_name(settings, 'dim_clip')}"
    )
    filters: list[tuple[str, str, str]] = []
    for dim in dim_rows:
        clip_id = str(dim["clip_id"])
        run_id = str(dim.get("active_run_id") or "")
        if not run_id:
            continue
        try:
            ctx = resolve_clip_context(clip_id, run_id)
            filters.append((ctx.clip_id, ctx.run_id, ctx.ds))
        except Exception:
            continue
    return filters





def _load_labeled_frames() -> list[dict[str, Any]]:

    cache_key = "all"

    if cache_key in _labeled_frames_cache:

        return _labeled_frames_cache[cache_key]



    settings = get_settings()

    clip_filters = _active_clip_filters()

    if not clip_filters:

        return []



    label_tbl = table_name(settings, "fact_image_label")

    frame_tbl = table_name(settings, "fact_frame")

    where_clip = " OR ".join(

        f"(l.clip_id={sql_quote(c)} AND l.run_id={sql_quote(r)} AND l.ds={sql_quote(ds)})"

        for c, r, ds in clip_filters

    )

    rows = query(
        f"SELECT l.clip_id, l.run_id, l.frame_id, l.timestamp_ns, l.labels_json, "
        f"l.sync_group_id, l.anchor_timestamp_ns, l.label_scope, "
        f"f.camera, f.frame_idx, f.image_path "
        f"FROM {label_tbl} l "

        f"INNER JOIN {frame_tbl} f "

        f"ON l.clip_id = f.clip_id AND l.run_id = f.run_id AND l.ds = f.ds "

        f"AND l.frame_id = CONCAT(f.camera, ':', CAST(f.frame_idx AS STRING)) "

        f"WHERE {where_clip}"

    )

    _labeled_frames_cache[cache_key] = rows

    return rows





def _frame_row_to_search_item(

    ctx_clip_id: str,

    ctx_run_id: str,

    row: dict[str, Any],

    labels_json: dict[str, Any],

    preview: str,

    settings: dict[str, str],

) -> dict[str, Any]:

    camera = str(row["camera"])

    frame_idx = int(row["frame_idx"])

    image_path = str(row["image_path"])

    meta = label_row_sync_fields(row)
    return {
        "composite_id": composite_id(ctx_clip_id, ctx_run_id, camera, frame_idx),
        "clip_id": ctx_clip_id,
        "camera": camera,
        "frame_idx": frame_idx,
        "timestamp_ns": scene_timestamp_ns(row),
        "preview_url": sign_image(settings, ctx_clip_id, ctx_run_id, image_path),
        "label_text": preview,
        "label_ids": label_value_ids(labels_json),
        "status": "success",
        **meta,
    }





def search_labels(keyword: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:

    settings = get_settings()

    items: list[dict[str, Any]] = []
    matched = [
        row
        for row in _load_labeled_frames()
        if match_labels(parse_labels_json(row.get("labels_json")), keyword=keyword)
    ]
    for row in dedupe_search_rows(matched):
        labels_json = parse_labels_json(row.get("labels_json"))
        preview = labels_preview(labels_json)
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        items.append(
            _frame_row_to_search_item(clip_id, run_id, row, labels_json, preview, settings)
        )

    total = len(items)

    start = (page - 1) * page_size

    return {"total": total, "page": page, "page_size": page_size, "items": items[start : start + page_size]}





def search_label_clusters(keyword: str, label_id: str | None = None) -> list[dict[str, Any]]:

    settings = get_settings()

    hits: list[dict[str, Any]] = []
    matched = [
        row
        for row in _load_labeled_frames()
        if match_labels(
            parse_labels_json(row.get("labels_json")),
            keyword=keyword,
            label_id=label_id,
        )
    ]
    for row in matched:
        labels_json = parse_labels_json(row.get("labels_json"))
        preview = labels_preview(labels_json)
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        meta = label_row_sync_fields(row)
        hits.append(
            {
                "clip_id": clip_id,
                "timestamp_ns": scene_timestamp_ns(row),
                "camera": str(row["camera"]),
                "preview_url": sign_image(
                    settings, clip_id, run_id, str(row["image_path"])
                ),
                "label_text": preview,
                **meta,
            }
        )

    if not hits:
        return []
    return aggregate_cluster_hits(hits)





def find_similar(composite_id_str: str, top_k: int = 8, min_score: float = 0.75) -> list[dict[str, Any]]:

    clip_id, run_id, camera, frame_idx = parse_composite_id(composite_id_str)

    ctx = resolve_clip_context(clip_id, run_id)

    settings = get_settings()

    w = (

        f"clip_id={sql_quote(ctx.clip_id)} AND run_id={sql_quote(ctx.run_id)} "

        f"AND ds={sql_quote(ctx.ds)}"

    )

    object_id = f"{camera}:{frame_idx}"

    src_rows = query(

        f"SELECT vector_json FROM {table_name(settings, 'fact_embedding')} "

        f"WHERE {w} AND object_type='frame' AND object_id={sql_quote(object_id)} LIMIT 1"

    )

    if not src_rows:

        return []

    query_vec = parse_embedding(str(src_rows[0].get("vector_json")))

    if query_vec is None:

        return []



    emb_rows = query(

        f"SELECT object_id, timestamp_ns, vector_json FROM "

        f"{table_name(settings, 'fact_embedding')} WHERE {w} AND object_type='frame'"

    )

    other_ids = [str(r["object_id"]) for r in emb_rows if str(r["object_id"]) != object_id]

    if not other_ids:

        return []



    in_list = ", ".join(sql_quote(oid) for oid in other_ids)

    frame_tbl = table_name(settings, "fact_frame")

    label_tbl = table_name(settings, "fact_image_label")

    frame_rows = query(

        f"SELECT camera, frame_idx, image_path FROM {frame_tbl} WHERE {w} "

        f"AND CONCAT(camera, ':', CAST(frame_idx AS STRING)) IN ({in_list})"

    )

    label_rows = query(

        f"SELECT frame_id, labels_json FROM {label_tbl} WHERE {w} "

        f"AND frame_id IN ({in_list})"

    )

    frame_by_oid = {

        f"{str(r['camera'])}:{int(r['frame_idx'])}": r for r in frame_rows

    }

    label_by_oid = {

        str(r["frame_id"]): parse_labels_json(r.get("labels_json")) for r in label_rows

    }



    candidates: list[dict[str, Any]] = []

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

        lj = label_by_oid.get(oid, {})

        preview = labels_preview(lj) if lj else ""

        candidates.append(

            {

                "composite_id": composite_id(ctx.clip_id, ctx.run_id, cam, idx),

                "clip_id": ctx.clip_id,

                "camera": cam,

                "timestamp_ns": int(r["timestamp_ns"]),

                "preview_url": sign_image(

                    settings, ctx.clip_id, ctx.run_id, str(fr["image_path"])

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


