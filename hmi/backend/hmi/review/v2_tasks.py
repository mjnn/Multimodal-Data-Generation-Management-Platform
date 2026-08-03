"""Review v2 task queue: confidence-priority open queue + comprehensive filter."""



from __future__ import annotations



import json

from dataclasses import dataclass, field

from typing import Any

from urllib.parse import quote, unquote



from hmi.ai_label_hints import load_ai_label_hints_local

from hmi.clip_facts import (
    get_clip_label_view_for_queue,
    list_clip_label_candidates,
    resolve_clip_thumbnail,
)

from hmi.labels_util import _normalize_bool, match_label_filters

from hmi.local.clip_context import resolve_ds_for_run

from hmi.local import store

from hmi.review.field_review_db import field_review_key_set, get_field_review

from hmi.review_db import get_review

from hmi.taxonomy_db import get_published_version, list_nodes



REVIEW_V2_MODES = frozenset({"confidence", "comprehensive"})

LEGACY_REVIEW_V2_MODE_ALIASES = {"ai_dispute": "confidence"}



# Labels with confidence strictly below this threshold are prioritized after empty values.

LOW_CONFIDENCE_THRESHOLD = 0.75





def normalize_review_v2_mode(mode: str) -> str:

    mode = (mode or "").strip()

    mode = LEGACY_REVIEW_V2_MODE_ALIASES.get(mode, mode)

    if mode not in REVIEW_V2_MODES:

        raise ValueError(f"invalid mode: {mode}")

    return mode





def _is_empty_value(value: Any) -> bool:

    if value is None:

        return True

    if isinstance(value, str) and not value.strip():

        return True

    return False





def _clip_dir_name(clip_id: str) -> str:

    row = store.query_one(

        "SELECT clip_dir_name FROM dim_clip WHERE clip_id=? LIMIT 1",

        (clip_id,),

    )

    if row and row.get("clip_dir_name"):

        return str(row["clip_dir_name"])

    return clip_id[:24]





def task_key(clip_id: str, run_id: str, label_id: str) -> str:

    return f"{clip_id}|{run_id}|{label_id}"





def parse_task_key(raw: str) -> tuple[str, str, str]:

    parts = unquote(raw).split("|", 2)

    if len(parts) != 3 or not all(parts):

        raise ValueError("invalid task cursor")

    return parts[0], parts[1], parts[2]





def encode_cursor(clip_id: str, run_id: str, label_id: str) -> str:

    return quote(task_key(clip_id, run_id, label_id), safe="")





def _taxonomy_node_map() -> dict[str, dict[str, Any]]:

    published = get_published_version()

    if not published:

        return {}

    nodes = list_nodes(published["id"], active_only=True)

    return {str(n["label_id"]): n for n in nodes}





def _label_meta(label_id: str, node_map: dict[str, dict[str, Any]]) -> dict[str, Any]:

    node = node_map.get(label_id) or {}

    return {

        "label_id": label_id,

        "label_name": node.get("name") or label_id,

        "dtype": node.get("dtype"),

        "value_schema": node.get("value_schema"),

    }





def _build_clip_card(clip_id: str, run_id: str, view: dict[str, Any]) -> dict[str, Any]:

    card: dict[str, Any] = {

        "clip_id": clip_id,

        "run_id": run_id,

        "clip_dir_name": _clip_dir_name(clip_id),

        "label_preview": view.get("label_preview") or "",

        "anchor_timestamp_ns": view.get("anchor_timestamp_ns"),

        "dispute_count": int(view.get("dispute_count") or 0),

        "multi_ai_gate": view.get("multi_ai_gate"),

    }

    try:

        ds = resolve_ds_for_run(clip_id, run_id)

        anchor = view.get("anchor_timestamp_ns")

        thumb = resolve_clip_thumbnail(

            clip_id,

            run_id,

            ds,

            int(anchor) if anchor is not None else None,

        )

        if thumb:

            card["thumbnail"] = {

                "camera": thumb.get("camera"),

                "frame_idx": thumb.get("frame_idx"),

                "image_path": thumb.get("image_path"),

                "timestamp_ns": thumb.get("timestamp_ns"),

            }

    except (ValueError, TypeError):

        pass

    review = get_review(clip_id, run_id)

    if review:

        card["review_status"] = review.get("review_status")

        card["clip_review_updated_at"] = review.get("updated_at")

    try:

        from hmi.router import clips_svc

        segments = clips_svc().get_audio_segments(clip_id, run_id)

        parts = [str(s.get("asr_text") or "").strip() for s in segments]

        asr_text = "\n".join(p for p in parts if p)

        if asr_text:

            card["asr_text"] = asr_text

    except Exception:

        pass

    return card





def _confidence_float(hint: dict[str, Any]) -> float | None:

    raw = hint.get("confidence")

    if raw is None:

        return None

    try:

        return float(raw)

    except (TypeError, ValueError):

        return None





def _confidence_priority_bucket(ai_value: Any, confidence: float | None) -> int:

    """0=empty (highest), 1=low/unknown confidence, 2=mid, 3=high."""

    if _is_empty_value(ai_value):

        return 0

    if confidence is None or confidence < 0.5:

        return 1

    if confidence < LOW_CONFIDENCE_THRESHOLD:

        return 2

    return 3





def _is_low_confidence(ai_value: Any, confidence: float | None) -> bool:

    if _is_empty_value(ai_value):

        return False

    if confidence is None:

        return True

    return confidence < LOW_CONFIDENCE_THRESHOLD


def _confidence_sort_key(

    ai_value: Any,

    confidence: float | None,

    clip_dir: str,

    lid: str,

) -> tuple[Any, ...]:

    bucket = _confidence_priority_bucket(ai_value, confidence)

    # Within non-empty rows, lower confidence first; missing confidence sorts as 0.

    conf_sort = confidence if confidence is not None else 0.0

    if _is_empty_value(ai_value):

        conf_sort = 0.0

    return (bucket, conf_sort, clip_dir, lid)





def _collect_label_ids(view: dict[str, Any]) -> list[str]:

    labels = view.get("labels_json") or {}

    return sorted(str(k) for k in labels.keys())





def _active_label_candidate_pairs() -> list[dict[str, str]]:
    active_rows = store.query(
        "SELECT clip_id, active_run_id FROM dim_clip "
        "WHERE active_run_id IS NOT NULL AND TRIM(active_run_id) != ''"
    )
    active = {(str(r["clip_id"]), str(r["active_run_id"])) for r in active_rows}
    if not active:
        return list_clip_label_candidates()
    out: list[dict[str, str]] = []
    for pair in list_clip_label_candidates():
        cid, rid = str(pair["clip_id"]), str(pair["run_id"])
        if (cid, rid) in active:
            out.append({"clip_id": cid, "run_id": rid})
    return out


def build_pending_tasks(

    mode: str,

    *,

    label_id: str | None = None,

    filter_value: Any = None,

    include_clip_card: bool = True,

) -> list[dict[str, Any]]:

    mode = normalize_review_v2_mode(mode)

    if mode == "comprehensive":

        if not label_id or filter_value is None or filter_value == "":

            raise ValueError("label_id and value required for comprehensive mode")



    reviewed_keys = field_review_key_set()

    node_map = _taxonomy_node_map()

    tasks: list[dict[str, Any]] = []

    hints_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    view_cache: dict[tuple[str, str], dict[str, Any]] = {}

    card_cache: dict[tuple[str, str], dict[str, Any]] = {}

    dir_cache: dict[str, str] = {}


    def _hints_for(clip_id: str, run_id: str) -> dict[str, dict[str, Any]]:

        key = (clip_id, run_id)

        if key not in hints_cache:

            hints_cache[key] = load_ai_label_hints_local(clip_id, run_id)

        return hints_cache[key]



    for pair in _active_label_candidate_pairs():

        clip_id = str(pair["clip_id"])

        run_id = str(pair["run_id"])

        try:

            ds = resolve_ds_for_run(clip_id, run_id)

        except ValueError:

            continue

        view = view_cache.get((clip_id, run_id))

        if view is None:

            view = get_clip_label_view_for_queue(clip_id, run_id, ds=ds)

            if view is None:

                continue

            view_cache[(clip_id, run_id)] = view

        if not view.get("clip_label_ready"):

            continue



        labels_json = view.get("labels_json") or {}

        if not isinstance(labels_json, dict):

            labels_json = {}

        clip_dir = dir_cache.get(clip_id)

        if clip_dir is None:

            clip_dir = _clip_dir_name(clip_id)

            dir_cache[clip_id] = clip_dir


        for lid in _collect_label_ids(view):

            if (clip_id, run_id, lid) in reviewed_keys:

                continue

            ai_value = labels_json.get(lid)

            hint = _hints_for(clip_id, run_id).get(lid) or {}

            confidence = _confidence_float(hint)



            if mode == "confidence":

                sort_key = _confidence_sort_key(ai_value, confidence, clip_dir, lid)

            else:

                if lid != label_id:

                    continue

                if not match_label_filters(labels_json, {label_id: filter_value}):

                    continue

                sort_key = (clip_dir, clip_id, lid)



            meta = _label_meta(lid, node_map)

            bucket = (

                _confidence_priority_bucket(ai_value, confidence) if mode == "confidence" else None

            )

            card_key = (clip_id, run_id)

            if include_clip_card:

                clip_card = card_cache.get(card_key)

                if clip_card is None:

                    clip_card = _build_clip_card(clip_id, run_id, view)

                    card_cache[card_key] = clip_card

            else:

                clip_card = None

            tasks.append(

                {

                    "_sort": sort_key,

                    "clip_id": clip_id,

                    "run_id": run_id,

                    "label_id": lid,

                    "label_name": meta["label_name"],

                    "dtype": meta["dtype"],

                    "value_schema": meta["value_schema"],

                    "ai_value": ai_value,

                    "ai_confidence": hint.get("confidence"),

                    "ai_evidence": hint.get("evidence"),

                    "human_doubtful": False,

                    "low_confidence": _is_low_confidence(ai_value, confidence),

                    "priority_bucket": bucket,

                    "clip_card": clip_card,

                    "cursor": encode_cursor(clip_id, run_id, lid),

                }

            )



    tasks.sort(key=lambda t: t["_sort"])

    for t in tasks:

        t.pop("_sort", None)

        t["position"] = {"index": 0, "total": len(tasks)}

    total = len(tasks)

    for idx, t in enumerate(tasks):

        t["position"] = {"index": idx + 1, "total": total}

    return tasks





def is_eligible_for_low_confidence_claim(task: dict[str, Any]) -> bool:
    """Eligible for low-confidence batch claim: empty value or confidence < threshold."""
    bucket = task.get("priority_bucket")
    if bucket is not None:
        return int(bucket) <= 2
    ai_value = task.get("ai_value")
    confidence = _confidence_float({"confidence": task.get("ai_confidence")})
    if _is_empty_value(ai_value):
        return True
    return _is_low_confidence(ai_value, confidence)


def filter_low_confidence_claim_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in tasks if is_eligible_for_low_confidence_claim(t)]


def build_low_confidence_claim_tasks(limit: int) -> list[dict[str, Any]]:
    tasks = build_pending_tasks("confidence")
    return filter_low_confidence_claim_tasks(tasks)[:limit]





def task_stats(

    mode: str,

    *,

    label_id: str | None = None,

    filter_value: Any = None,

) -> dict[str, Any]:

    tasks = build_pending_tasks(
        mode,
        label_id=label_id,
        filter_value=filter_value,
        include_clip_card=False,
    )

    normalized = normalize_review_v2_mode(mode)

    result: dict[str, Any] = {

        "mode": normalized,

        "label_id": label_id,

        "value": filter_value,

        "pending": len(tasks),

        "total": len(tasks),

    }

    if normalized == "confidence":

        claimable = filter_low_confidence_claim_tasks(tasks)

        result["low_confidence_pending"] = len(claimable)

    return result





def pick_next_task(

    mode: str,

    *,

    label_id: str | None = None,

    filter_value: Any = None,

    cursor: str | None = None,

) -> dict[str, Any] | None:

    tasks = build_pending_tasks(mode, label_id=label_id, filter_value=filter_value)

    if not tasks:

        return None

    if not cursor:

        return tasks[0]

    try:

        cur_clip, cur_run, cur_label = parse_task_key(cursor)

    except ValueError:

        return tasks[0]

    cur_key = task_key(cur_clip, cur_run, cur_label)

    for idx, task in enumerate(tasks):

        if task_key(task["clip_id"], task["run_id"], task["label_id"]) == cur_key:

            if idx + 1 < len(tasks):

                return tasks[idx + 1]

            return None

    return tasks[0]





def list_label_options(keyword: str = "") -> list[dict[str, Any]]:

    published = get_published_version()

    if not published:

        return []

    kw = keyword.strip().lower()

    nodes = list_nodes(published["id"], active_only=True)

    out: list[dict[str, Any]] = []

    for node in nodes:

        label_id = str(node.get("label_id") or "")

        name = str(node.get("name") or label_id)

        if not label_id:

            continue

        hay = f"{label_id} {name}".lower()

        if kw and kw not in hay:

            continue

        schema = node.get("value_schema")

        options: list[Any] = []

        if isinstance(schema, dict) and isinstance(schema.get("values"), list):

            options = schema["values"]

        out.append(

            {

                "label_id": label_id,

                "name": name,

                "dtype": node.get("dtype"),

                "value_schema": schema,

                "enum_values": options,

            }

        )

    return out





def parse_query_value(raw: str | None, dtype: str | None = None) -> Any:

    if raw is None:

        return None

    text = raw.strip()

    if dtype == "boolean" or text.lower() in ("true", "false", "0", "1", "yes", "no"):

        parsed = _normalize_bool(text)

        if parsed is not None:

            return parsed

    if text.lower() == "null":

        return None

    try:

        return json.loads(text)

    except json.JSONDecodeError:

        return text





@dataclass

class ReviewV2Session:

    mode: str

    label_id: str | None = None

    filter_value: Any = None

    history: list[dict[str, Any]] = field(default_factory=list)

    index: int = -1





_sessions: dict[str, ReviewV2Session] = {}





def get_or_reset_session(

    user_id: str,

    mode: str,

    *,

    label_id: str | None = None,

    filter_value: Any = None,

) -> ReviewV2Session:

    mode = normalize_review_v2_mode(mode)

    existing = _sessions.get(user_id)

    if (

        existing is None

        or existing.mode != mode

        or existing.label_id != label_id

        or existing.filter_value != filter_value

    ):

        existing = ReviewV2Session(mode=mode, label_id=label_id, filter_value=filter_value)

        _sessions[user_id] = existing

    return existing





def session_snapshot(session: ReviewV2Session) -> dict[str, Any]:

    return {

        "mode": session.mode,

        "label_id": session.label_id,

        "value": session.filter_value,

        "history_count": len(session.history),

        "history_index": session.index,

        "can_prev": session.index > 0,

    }





def advance_session(session: ReviewV2Session, task: dict[str, Any]) -> None:

    if session.index < len(session.history) - 1:

        session.history = session.history[: session.index + 1]

    session.history.append(task)

    session.index = len(session.history) - 1





def _refresh_task_clip_review_meta(task: dict[str, Any]) -> dict[str, Any]:

    """Refresh clip-level review metadata on a task (e.g. after prev navigation)."""

    from copy import deepcopy



    from hmi.review_db import get_review



    refreshed = deepcopy(task)

    review = get_review(refreshed["clip_id"], refreshed["run_id"])

    card = refreshed.get("clip_card")

    if not isinstance(card, dict):

        return refreshed

    if review:

        card["clip_review_updated_at"] = review.get("updated_at")

        card["review_status"] = review.get("review_status")

    else:

        card.pop("clip_review_updated_at", None)

        card.pop("review_status", None)

    existing = get_field_review(refreshed["clip_id"], refreshed["run_id"], refreshed["label_id"])

    if existing:

        refreshed["human_doubtful"] = bool(existing["human_doubtful"])

    return refreshed





def prev_session_task(session: ReviewV2Session) -> dict[str, Any] | None:

    if session.index <= 0:

        return None

    session.index -= 1

    task = _refresh_task_clip_review_meta(session.history[session.index])

    session.history[session.index] = task

    return task





def clear_sessions() -> None:

    """Test helper."""

    _sessions.clear()

