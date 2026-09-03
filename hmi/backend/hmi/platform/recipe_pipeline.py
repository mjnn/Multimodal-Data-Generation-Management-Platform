"""Compile pipeline cards ↔ existing recipe preprocess / stages / bbox.

Editor source of truth is an ordered list of component cards. Persistence stays
the legacy recipe JSON so local_sdk_worker / overlay_run_request stay unchanged.
"""

from __future__ import annotations

from typing import Any

from hmi.platform.operators import (
    CATALOG,
    PARSE_BAG_MODALITIES,
    SOURCE_KINDS,
    get_operator,
    parse_bag_emit_modalities,
    type_compatible,
)
from hmi.platform.file_kinds import (
    normalize_parse_bag_modality,
    normalize_source_kind,
    singleton_kind_groups,
)


def default_produces(op: dict[str, Any] | None) -> list[str]:
    if not op:
        return []
    if str(op.get("op_id") or "") == "parse_bag":
        return list(PARSE_BAG_MODALITIES)
    names: list[str] = []
    for port in op.get("output_ports") or []:
        types = port.get("types") or []
        if types:
            names.append(str(types[0]))
    if names:
        return names
    product = str(op.get("product") or "").strip()
    return [product] if product else []


def effective_produces(card: dict[str, Any], op: dict[str, Any] | None = None) -> list[str]:
    op_id = str(card.get("op_id") or (op or {}).get("op_id") or "").strip()
    if op_id == "parse_bag":
        selected = parse_bag_emit_modalities(card.get("params") if isinstance(card.get("params"), dict) else None)
        if selected is not None:
            return selected
        stored = [str(x).strip() for x in (card.get("produces") or []) if str(x).strip()]
        mapped: list[str] = []
        for item in stored:
            m = normalize_parse_bag_modality(item)
            if m and m not in mapped:
                mapped.append(m)
        if stored == ["frames_audio_topics"] or not stored:
            return list(PARSE_BAG_MODALITIES)
        if mapped:
            return mapped
        return list(PARSE_BAG_MODALITIES)
    stored = [str(x).strip() for x in (card.get("produces") or []) if str(x).strip()]
    if stored:
        return stored
    return default_produces(op or get_operator(op_id))


def input_ports(op: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not op:
        return [{"id": "in", "types": []}]
    ports = op.get("input_ports") or []
    if ports:
        return list(ports)
    kinds = op.get("input_kinds") or []
    return [{"id": "in", "types": list(kinds)}]


def output_ports(op: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not op:
        return [{"id": "out", "types": []}]
    ports = op.get("output_ports") or []
    if ports:
        return list(ports)
    product = str(op.get("product") or "").strip()
    return [{"id": "out", "types": [product] if product else []}]


def is_source_card(card: dict[str, Any] | None) -> bool:
    if not isinstance(card, dict):
        return False
    return card.get("card_kind") == "source" or card.get("op_id") == "source"


def new_source_card(
    *,
    key: str,
    title: str,
    kinds: list[str],
    cardinality_min: int = 1,
    cardinality_max: int = 1,
    required: bool = True,
) -> dict[str, Any]:
    kinds_list = list(kinds)
    return {
        "key": key,
        "card_kind": "source",
        "op_id": "source",
        "title": title,
        "kinds": kinds_list,
        "cardinality_min": cardinality_min,
        "cardinality_max": cardinality_max,
        "required": required,
        "produces": list(kinds_list),
        "bindings": {},
    }


def slots_from_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Source cards → recipe slots (id = card key)."""
    out: list[dict[str, Any]] = []
    for card in steps:
        if not is_source_card(card):
            continue
        key = str(card.get("key") or "").strip()
        if not key:
            continue
        title = str(card.get("title") or key).strip() or key
        out.append(
            {
                "id": key,
                "title": title,
                "kinds": list(card.get("kinds") or []),
                "cardinality_min": int(card.get("cardinality_min") or 1),
                "cardinality_max": int(card.get("cardinality_max") or 1),
                "required": bool(card.get("required", True)),
                "role": "input",
            }
        )
    return out


def _bind_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [b for b in raw if isinstance(b, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _bind_from_option(opt: dict[str, Any]) -> dict[str, Any]:
    if str(opt.get("kind") or "") == "slot":
        return {"kind": "slot", "slot_id": str(opt.get("slot_id") or "")}
    return {
        "kind": "upstream",
        "step_key": str(opt.get("step_key") or ""),
        "port_id": str(opt.get("port_id") or "out"),
    }


def _auto_bindings(
    op: dict[str, Any] | None,
    slots: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    bindings: dict[str, Any] = {}
    when_kind: str | None = None
    for port in input_ports(op):
        pid = str(port.get("id") or "in")
        options = binding_options(
            needed_types=list(port.get("types") or []),
            slots=slots,
            upstream=upstream,
        )
        if not options:
            continue
        if port.get("multiple"):
            bindings[pid] = [_bind_from_option(o) for o in options]
        else:
            bindings[pid] = _bind_from_option(options[0])
        first = options[0]
        if str(first.get("kind") or "") == "slot" and when_kind is None:
            slot = next((s for s in slots if s.get("id") == first.get("slot_id")), None)
            when_kind = _when_kind_from_slot(slot)
    return bindings, when_kind


def assert_upward_bindings(steps: list[dict[str, Any]]) -> None:
    """Bindings may only point at cards that appear earlier in the list."""
    key_to_index: dict[str, int] = {}
    for i, card in enumerate(steps):
        key = str(card.get("key") or "").strip()
        if key:
            key_to_index[key] = i
    for i, card in enumerate(steps):
        bindings = card.get("bindings") or {}
        if not isinstance(bindings, dict):
            continue
        for raw in bindings.values():
            for bind in _bind_list(raw):
                refs: list[str] = []
                slot_id = str(bind.get("slot_id") or "").strip()
                step_key = str(bind.get("step_key") or "").strip()
                if slot_id:
                    refs.append(slot_id)
                if step_key:
                    refs.append(step_key)
                for ref in refs:
                    idx = key_to_index.get(ref)
                    if idx is None:
                        continue
                    if idx >= i:
                        raise ValueError(f"binding {ref!r} must reference a card above the current step")


def _require_any_kinds_from_slots(slots: list[dict[str, Any]]) -> list[list[str]]:
    required = [s for s in slots if s.get("required") and s.get("kinds")]
    pool = required if required else [s for s in slots if s.get("kinds")]
    groups: list[list[str]] = []
    for slot in pool:
        groups.extend(singleton_kind_groups(*(list(slot.get("kinds") or []))))
    return groups


def _strip_output_labels(labels: Any, produces: list[str]) -> dict[str, str] | None:
    if not isinstance(labels, dict) or not labels:
        return None
    allowed = set(produces)
    clean: dict[str, str] = {}
    for pk, pv in labels.items():
        port = str(pk).strip()
        if port not in allowed:
            continue
        name = str(pv).strip()
        if name:
            clean[port] = name
    return clean or None


def _slot_ids(slots: list[dict[str, Any]]) -> set[str]:
    return {str(s.get("id") or "").strip() for s in slots if str(s.get("id") or "").strip()}


def _when_kind_from_slot(slot: dict[str, Any] | None) -> str | None:
    if not slot:
        return None
    kinds = [str(k).strip().lower() for k in (slot.get("kinds") or []) if str(k).strip()]
    kinds = [normalize_source_kind(k) or k for k in kinds]
    kinds = [k for k in kinds if k in SOURCE_KINDS]
    if len(kinds) == 1:
        return kinds[0]
    return None


def hydrate_recipe_to_steps(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """Recipe JSON → ordered editor cards (source cards first, then ops)."""
    slots = list(recipe.get("slots") or [])
    source_cards: list[dict[str, Any]] = []
    for slot in slots:
        sid = str(slot.get("id") or "").strip()
        if not sid:
            continue
        kinds = list(slot.get("kinds") or [])
        source_cards.append(
            new_source_card(
                key=sid,
                title=str(slot.get("title") or sid),
                kinds=kinds,
                cardinality_min=int(slot.get("cardinality_min") or 1),
                cardinality_max=int(slot.get("cardinality_max") or 1),
                required=bool(slot.get("required", True)),
            )
        )
    steps: list[dict[str, Any]] = []
    prior: list[dict[str, Any]] = []
    produce_index: dict[str, tuple[str, str]] = {}

    for idx, raw in enumerate(recipe.get("preprocess") or []):
        if not isinstance(raw, dict):
            continue
        op_id = str(raw.get("op_id") or "").strip()
        op = get_operator(op_id)
        key = f"prep-{idx}-{op_id}"
        produces = [str(x).strip() for x in (raw.get("produces") or []) if str(x).strip()]
        params = dict(raw.get("params") or {})
        if op_id == "parse_bag":
            produces = effective_produces({"op_id": op_id, "produces": produces, "params": params}, op)
            params["emit_modalities"] = produces
        elif not produces:
            produces = default_produces(op)
        card: dict[str, Any] = {
            "key": key,
            "op_id": op_id,
            "role": "preprocess",
            "required": bool(raw.get("required", False)),
            "when_kind": raw.get("when_kind"),
            "produces": produces,
            "params": params,
            "bindings": _hydrate_bindings(raw.get("inputs") or [], slots, produce_index, op),
            "bbox_enabled": False,
        }
        labels = raw.get("output_labels")
        if isinstance(labels, dict) and labels:
            card["output_labels"] = dict(labels)
        if op_id == "detect_bbox":
            bbox = recipe.get("bbox") or {}
            card["bbox_enabled"] = bool(bbox.get("enabled", False))
            if bbox.get("detector"):
                card["params"]["detector"] = str(bbox.get("detector"))
            if "yolo_classes" in bbox:
                card["params"]["yolo_classes"] = str(bbox.get("yolo_classes") or "")
        steps.append(card)
        prior.append(card)
        for name in produces:
            produce_index[name] = (key, name)

    prior_all = source_cards + steps
    bbox = recipe.get("bbox") or {}
    has_bbox_op = any(s.get("op_id") == "detect_bbox" for s in steps)
    if bool(bbox.get("enabled")) and not has_bbox_op:
        op = get_operator("detect_bbox")
        key = "prep-bbox-detect_bbox"
        steps.append(
            {
                "key": key,
                "op_id": "detect_bbox",
                "role": "preprocess",
                "required": True,
                "when_kind": None,
                "produces": default_produces(op),
                "params": {
                    "detector": str(bbox.get("detector") or "opencv"),
                    "yolo_classes": str(bbox.get("yolo_classes") or ""),
                },
                "bindings": {},
                "bbox_enabled": True,
            }
        )
        prior_all = source_cards + steps

    stages = recipe.get("stages") or {}
    label = stages.get("label") or {}
    if bool(label.get("enabled", False)):
        op = get_operator("label")
        model = str(label.get("model") or "").strip()
        params: dict[str, Any] = {}
        if model:
            params["model"] = model
        steps.append(
            {
                "key": "stage-label",
                "op_id": "label",
                "role": "stage",
                "required": False,
                "when_kind": None,
                "produces": default_produces(op),
                "params": params,
                "bindings": _stage_bindings(op, label.get("inputs"), slots, produce_index, prior_all),
                "bbox_enabled": False,
            }
        )
        prior_all = source_cards + steps
    embed = stages.get("embed") or {}
    if bool(embed.get("enabled", False)):
        op = get_operator("embed")
        steps.append(
            {
                "key": "stage-embed",
                "op_id": "embed",
                "role": "stage",
                "required": False,
                "when_kind": None,
                "produces": default_produces(op),
                "params": {},
                "bindings": _stage_bindings(op, embed.get("inputs"), slots, produce_index, prior_all),
                "bbox_enabled": False,
            }
        )
    return source_cards + steps


def _stage_bindings(
    op: dict[str, Any] | None,
    inputs: Any,
    slots: list[dict[str, Any]],
    produce_index: dict[str, tuple[str, str]],
    prior: list[dict[str, Any]],
) -> dict[str, Any]:
    if inputs is None:
        bindings, _ = _auto_bindings(op, slots, prior)
        return bindings
    return _hydrate_bindings(list(inputs), slots, produce_index, op)


def _hydrate_bindings(
    inputs: list[Any],
    slots: list[dict[str, Any]],
    produce_index: dict[str, tuple[str, str]],
    op: dict[str, Any] | None,
) -> dict[str, Any]:
    ports = input_ports(op)
    slot_ids = _slot_ids(slots)
    bindings: dict[str, Any] = {}
    multi = bool(ports) and bool(ports[0].get("multiple")) and len(ports) == 1

    def _one(inp: str) -> dict[str, Any]:
        if inp in slot_ids:
            return {"kind": "slot", "slot_id": inp}
        if inp in produce_index:
            step_key, port_id = produce_index[inp]
            return {"kind": "upstream", "step_key": step_key, "port_id": port_id}
        return {"kind": "slot", "slot_id": inp}

    if multi:
        pid = str(ports[0].get("id") or "in")
        acc: list[dict[str, Any]] = []
        for raw in inputs:
            inp = str(raw).strip()
            if inp:
                acc.append(_one(inp))
        if acc:
            bindings[pid] = acc
        return bindings

    for i, raw in enumerate(inputs):
        inp = str(raw).strip()
        if not inp:
            continue
        port = ports[i] if i < len(ports) else ports[-1]
        pid = str(port.get("id") or "in")
        bindings[pid] = _one(inp)
    return bindings


def compile_steps(
    steps: list[dict[str, Any]],
    slots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cards → preprocess / products / stages / bbox / slots."""
    assert_upward_bindings(steps)
    source_slots = slots_from_steps(steps)
    if source_slots:
        slots = source_slots
    else:
        slots = list(slots or [])
    slot_by_id = {str(s.get("id") or "").strip(): s for s in slots if str(s.get("id") or "").strip()}
    by_key = {str(s.get("key") or ""): s for s in steps}

    preprocess: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen_products: set[str] = set()
    label_card: dict[str, Any] | None = None
    embed_card: dict[str, Any] | None = None
    bbox_card: dict[str, Any] | None = None

    for card in steps:
        if is_source_card(card):
            continue
        op_id = str(card.get("op_id") or "").strip()
        role = str(card.get("role") or (CATALOG.get(op_id) or {}).get("role") or "preprocess")
        if op_id == "label" or role == "stage" and op_id == "label":
            label_card = card
            continue
        if op_id == "embed" or role == "stage" and op_id == "embed":
            embed_card = card
            continue
        if role == "stage":
            continue
        op = get_operator(op_id)
        produces = effective_produces(card, op)
        if op_id == "parse_bag":
            params_pre = dict(card.get("params") or {})
            params_pre["emit_modalities"] = produces
            card = {**card, "params": params_pre, "produces": produces}
            ck = str(card.get("key") or "")
            if ck:
                by_key[ck] = card
        inputs = _compile_inputs(card, by_key, slot_by_id, op)
        when_kind = card.get("when_kind")
        if when_kind is None:
            when_kind = _derive_when_kind(card, slot_by_id)
        entry: dict[str, Any] = {
            "op_id": op_id,
            "when_kind": when_kind,
            "required": bool(card.get("required", False)),
        }
        if inputs:
            entry["inputs"] = inputs
        if produces:
            entry["produces"] = produces
        params = dict(card.get("params") or {})
        if op_id == "detect_bbox":
            bbox_card = card
            params.pop("enabled", None)
        clean_params = {k: v for k, v in params.items() if v not in (None, "")}
        if clean_params:
            entry["params"] = clean_params
        labels = _strip_output_labels(card.get("output_labels"), produces)
        if labels:
            entry["output_labels"] = labels
        preprocess.append(entry)
        for name in produces:
            if name in seen_products:
                continue
            seen_products.add(name)
            products.append({"id": name, "from_op": op_id, "reusable": True})

    stages: dict[str, Any] = {
        "label": {"enabled": label_card is not None},
        "embed": {"enabled": embed_card is not None},
    }
    if label_card is not None:
        model = str((label_card.get("params") or {}).get("model") or "").strip()
        if model:
            stages["label"]["model"] = model
        label_inputs = _compile_inputs(label_card, by_key, slot_by_id, get_operator("label"))
        stages["label"]["inputs"] = label_inputs
    if embed_card is not None:
        embed_inputs = _compile_inputs(embed_card, by_key, slot_by_id, get_operator("embed"))
        stages["embed"]["inputs"] = embed_inputs

    if bbox_card is not None:
        params = bbox_card.get("params") or {}
        bbox = {
            "enabled": bool(bbox_card.get("bbox_enabled", True)),
            "detector": str(params.get("detector") or "opencv"),
            "yolo_classes": str(params.get("yolo_classes") or ""),
        }
    else:
        bbox = {"enabled": False, "detector": "opencv", "yolo_classes": ""}

    return {
        "preprocess": preprocess,
        "products": products,
        "stages": stages,
        "bbox": bbox,
        "slots": slots,
        "require_any_kinds": _require_any_kinds_from_slots(slots),
    }


def _compile_inputs(
    card: dict[str, Any],
    by_key: dict[str, dict[str, Any]],
    slot_by_id: dict[str, dict[str, Any]],
    op: dict[str, Any] | None,
) -> list[str]:
    bindings = card.get("bindings") or {}
    if not isinstance(bindings, dict) or not bindings:
        return []
    out: list[str] = []
    for port in input_ports(op):
        for bind in _bind_list(bindings.get(str(port.get("id") or "in"))):
            resolved = _compile_one_bind(bind, by_key)
            if resolved and resolved not in out:
                out.append(resolved)
    return out


def _compile_one_bind(bind: dict[str, Any], by_key: dict[str, dict[str, Any]]) -> str | None:
    kind = str(bind.get("kind") or "")
    if kind == "slot":
        slot_id = str(bind.get("slot_id") or "").strip()
        return slot_id or None
    if kind != "upstream":
        return None
    up = by_key.get(str(bind.get("step_key") or ""))
    if not up:
        return None
    produces = effective_produces(up, get_operator(str(up.get("op_id") or "")))
    if is_source_card(up) and not produces:
        produces = [str(k).strip() for k in (up.get("kinds") or []) if str(k).strip()]
    port_id = str(bind.get("port_id") or "").strip()
    if port_id and port_id in produces:
        return port_id
    if produces and port_id in {"", "out"}:
        return produces[0]
    if is_source_card(up):
        sid = str(up.get("key") or "").strip()
        return sid or None
    return None


def _derive_when_kind(card: dict[str, Any], slot_by_id: dict[str, dict[str, Any]]) -> str | None:
    bindings = card.get("bindings") or {}
    if not isinstance(bindings, dict):
        return None
    for raw in bindings.values():
        for bind in _bind_list(raw):
            if str(bind.get("kind") or "") != "slot":
                continue
            slot = slot_by_id.get(str(bind.get("slot_id") or "").strip())
            wk = _when_kind_from_slot(slot)
            if wk:
                return wk
    return None


def binding_options(
    *,
    needed_types: list[str],
    slots: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compatible slot / upstream produce options for a port."""
    needed = [str(t).strip() for t in needed_types if str(t).strip()]
    options: list[dict[str, Any]] = []
    seen_slot_ids: set[str] = set()

    def _append_slot(sid: str, kinds: list[str], title: str) -> None:
        if not sid or sid in seen_slot_ids:
            return
        if any(type_compatible(kind, need) for kind in kinds for need in needed):
            seen_slot_ids.add(sid)
            label = title.strip() if title.strip() else f"槽位 {sid}"
            options.append({"kind": "slot", "slot_id": sid, "label": label})

    for slot in slots:
        sid = str(slot.get("id") or "").strip()
        kinds = [str(k).strip() for k in (slot.get("kinds") or []) if str(k).strip()]
        _append_slot(sid, kinds, str(slot.get("title") or ""))
    for card in upstream:
        if is_source_card(card):
            sid = str(card.get("key") or "").strip()
            kinds = [str(k).strip() for k in (card.get("kinds") or []) if str(k).strip()]
            _append_slot(sid, kinds, str(card.get("title") or sid))
            continue
        op = get_operator(str(card.get("op_id") or ""))
        produces = effective_produces(card, op)
        title = str((op or {}).get("title") or card.get("op_id") or "上游")
        labels = card.get("output_labels") if isinstance(card.get("output_labels"), dict) else {}
        for name in produces:
            if any(type_compatible(name, need) for need in needed):
                port_label = str(labels.get(name) or name)
                options.append(
                    {
                        "kind": "upstream",
                        "step_key": str(card.get("key") or ""),
                        "port_id": name,
                        "label": f"{title} · {port_label}",
                    }
                )
    return options


def new_step_from_op(op_id: str, *, key: str, slots: list[dict[str, Any]], upstream: list[dict[str, Any]]) -> dict[str, Any]:
    op = get_operator(op_id) or {}
    role = str(op.get("role") or "preprocess")
    bindings, when_kind = _auto_bindings(op, slots, upstream)
    return {
        "key": key,
        "op_id": op_id,
        "role": role,
        "required": False,
        "when_kind": when_kind,
        "produces": default_produces(op) if op_id != "parse_bag" else list(PARSE_BAG_MODALITIES),
        "params": _default_params(op_id, op),
        "bindings": bindings,
        "bbox_enabled": op_id == "detect_bbox",
    }


def _default_params(op_id: str, op: dict[str, Any]) -> dict[str, Any]:
    if op_id == "label":
        return {"model": "default"}
    if op_id == "detect_bbox":
        return {"detector": "opencv", "yolo_classes": ""}
    if op_id == "parse_bag":
        return {"emit_modalities": list(PARSE_BAG_MODALITIES)}
    schema = op.get("params_schema") or {}
    if "model" in schema:
        return {"model": ""}
    return {}


def default_new_steps() -> list[dict[str, Any]]:
    """New DataType editor starts with a labeler card (previous label_enabled default)."""
    return [
        new_step_from_op("label", key="stage-label", slots=[], upstream=[]),
    ]
