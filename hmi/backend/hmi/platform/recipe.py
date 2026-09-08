"""DataType 配方校验与内置种子。

种子：oms_cabin（舱内 OMS）、ivi_ui_stub（IVI 占位）、audio_array_spec（阵列 NVH）、
audio_defect（问题音频：wav+JSON tag → if → 标签树输入）。
`audio_array_spec.stages.label.model` 现为 nvh_sem_ast；taxonomy audio_nvh-v2 保持 draft，禁止 publish。
audio_defect-v1 同样保持 draft，勿发布以免顶掉 OMS label_tree_baseline。
配方图基线来自线上 DataType ``test``（2026-09-08）。
bbox 检测器只允许 opencv/yolo，拒绝 vl。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hmi.platform.file_kinds import (
    AUDIO_EXTS,
    IMAGE_EXTS,
    PARSE_BAG_MODALITIES,
    VIDEO_EXTS,
    normalize_parse_bag_modality,
    normalize_source_kind,
    singleton_kind_groups,
)
from hmi.platform.operators import (
    BBOX_DETECTORS,
    OPERATORS,
    STAGE_OPERATORS,
    param_keys_for_op,
)
from hmi.platform.views import VIEW_TEMPLATE_IDS, hydrate_overview

RECIPE_STATUSES = frozenset({"draft", "published"})
STAGE_KEYS = ("label", "embed")

OMS_TAXONOMY_ID = "oms"
IVI_TAXONOMY_ID = "ivi_ui_stub"
AUDIO_NVH_TAXONOMY_ID = "audio_nvh"
AUDIO_DEFECT_TAXONOMY_ID = "audio_defect"
AUDIO_DEFECT_VERSION_CODE = "audio_defect-v1"


def _require_str(recipe: dict[str, Any], key: str) -> str:
    val = recipe.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"recipe.{key} is required")
    return val.strip()


def validate_recipe(recipe: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy or raise ValueError."""
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    out = deepcopy(recipe)
    out["id"] = _require_str(out, "id")
    out["title"] = _require_str(out, "title")
    out["purpose"] = _require_str(out, "purpose")
    out["owner"] = str(out.get("owner") or "platform").strip() or "platform"
    out["taxonomy_id"] = _require_str(out, "taxonomy_id")
    view = _require_str(out, "overview_view")
    if view not in VIEW_TEMPLATE_IDS:
        raise ValueError(f"unknown overview_view={view!r}")
    out["overview_view"] = view
    status = str(out.get("status") or "draft").strip().lower()
    if status not in RECIPE_STATUSES:
        raise ValueError(f"invalid status={status!r}")
    out["status"] = status

    groups = out.get("require_any_kinds")
    if not isinstance(groups, list) or not groups:
        raise ValueError("recipe.require_any_kinds must be a non-empty list of kind groups")
    norm_groups: list[list[str]] = []
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError("each require_any_kinds group must be a non-empty list of kinds")
        kinds: list[str] = []
        for kind in group:
            k = normalize_source_kind(str(kind))
            if k is None:
                raise ValueError(f"unknown source kind={kind!r}")
            if k not in kinds:
                kinds.append(k)
        norm_groups.append(kinds)
    out["require_any_kinds"] = norm_groups

    slots_in = out.get("slots")
    if slots_in is None:
        slots_in = [
            {
                "id": f"group_{idx}",
                "kinds": list(group),
                "cardinality_min": 1,
                "cardinality_max": max(1, len(group)),
                "role": "input",
                "required": True,
            }
            for idx, group in enumerate(norm_groups)
        ]
    if not isinstance(slots_in, list) or not slots_in:
        raise ValueError("recipe.slots must be a non-empty list")
    norm_slots: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for slot in slots_in:
        if not isinstance(slot, dict):
            raise ValueError("each slot must be an object")
        slot_id = str(slot.get("id") or "").strip()
        if not slot_id:
            raise ValueError("slot.id is required")
        raw_kinds = slot.get("kinds")
        if not isinstance(raw_kinds, list) or not raw_kinds:
            raise ValueError(f"slot {slot_id!r} kinds must be a non-empty list")
        skinds: list[str] = []
        for kind in raw_kinds:
            k = normalize_source_kind(str(kind))
            if k is None:
                raise ValueError(f"unknown slot kind={kind!r}")
            if k not in skinds:
                skinds.append(k)
        cmin = int(slot.get("cardinality_min") or 1)
        cmax = int(slot.get("cardinality_max") or cmin)
        if cmin < 0 or cmax < cmin:
            raise ValueError(f"slot {slot_id!r} has invalid cardinality")
        title = str(slot.get("title") or slot_id).strip() or slot_id
        title_key = title.casefold()
        if title_key in seen_titles:
            raise ValueError("数据源名称不能重复")
        seen_titles.add(title_key)
        norm_slots.append(
            {
                "id": slot_id,
                "title": title,
                "kinds": skinds,
                "cardinality_min": cmin,
                "cardinality_max": cmax,
                "role": str(slot.get("role") or "input").strip() or "input",
                "required": bool(slot.get("required", True)),
            }
        )
    out["slots"] = norm_slots

    preprocess = out.get("preprocess") or []
    if not isinstance(preprocess, list):
        raise ValueError("recipe.preprocess must be a list")
    norm_prep: list[dict[str, Any]] = []
    for step in preprocess:
        if not isinstance(step, dict):
            raise ValueError("preprocess step must be an object")
        op_id = str(step.get("op_id") or "").strip()
        if op_id in STAGE_OPERATORS:
            raise ValueError(f"stage op_id={op_id!r} cannot appear in preprocess")
        if op_id not in OPERATORS:
            raise ValueError(f"unknown op_id={op_id!r}")
        when_kind = step.get("when_kind")
        if when_kind is not None:
            wk = normalize_source_kind(str(when_kind))
            if wk is None:
                raise ValueError(f"unknown when_kind={when_kind!r}")
            when_kind = wk
        produces = step.get("produces")
        if produces is not None and not isinstance(produces, list):
            raise ValueError(f"preprocess {op_id}.produces must be a list")
        inputs = step.get("inputs")
        if inputs is not None and not isinstance(inputs, list):
            raise ValueError(f"preprocess {op_id}.inputs must be a list")
        params_in = step.get("params")
        params: dict[str, Any] | None = None
        if params_in is not None:
            if not isinstance(params_in, dict):
                raise ValueError(f"preprocess {op_id}.params must be an object")
            allowed = param_keys_for_op(op_id)
            params = {}
            for key, val in params_in.items():
                k = str(key).strip()
                if k not in allowed:
                    raise ValueError(f"preprocess {op_id}.params unknown key={k!r}")
                if k == "detector":
                    det = str(val or "").strip().lower()
                    if det not in BBOX_DETECTORS:
                        raise ValueError(f"bbox.detector must be opencv|yolo, got {det!r}")
                    params[k] = det
                elif k == "emit_modalities":
                    if not isinstance(val, list):
                        raise ValueError(f"preprocess {op_id}.params.emit_modalities must be a list")
                    mods: list[str] = []
                    for item in val:
                        m = normalize_parse_bag_modality(str(item))
                        if m is None:
                            raise ValueError(
                                f"parse_bag emit_modalities must be frames|.wav|.json, got {item!r}"
                            )
                        if m not in mods:
                            mods.append(m)
                    params[k] = mods
                else:
                    params[k] = val
        entry: dict[str, Any] = {
            "op_id": op_id,
            "when_kind": when_kind,
            "required": bool(step.get("required", False)),
        }
        if inputs is not None:
            entry["inputs"] = [str(x).strip() for x in inputs if str(x).strip()]
        if produces is not None:
            entry["produces"] = [str(x).strip() for x in produces if str(x).strip()]
        if params:
            entry["params"] = params
        labels = step.get("output_labels")
        if labels is not None:
            if not isinstance(labels, dict):
                raise ValueError(f"preprocess {op_id}.output_labels must be an object")
            allowed = set(entry.get("produces") or [])
            clean: dict[str, str] = {}
            for pk, pv in labels.items():
                port = str(pk).strip()
                if allowed and port not in allowed:
                    raise ValueError(f"output_labels unknown port={port!r}")
                name = str(pv).strip()
                if name:
                    clean[port] = name
            if clean:
                entry["output_labels"] = clean
        norm_prep.append(entry)
    out["preprocess"] = norm_prep

    products_in = out.get("products") or []
    if not isinstance(products_in, list):
        raise ValueError("recipe.products must be a list")
    norm_products: list[dict[str, Any]] = []
    for prod in products_in:
        if not isinstance(prod, dict):
            raise ValueError("each product must be an object")
        pid = str(prod.get("id") or "").strip()
        if not pid:
            raise ValueError("product.id is required")
        from_op = str(prod.get("from_op") or "").strip()
        if from_op and from_op not in OPERATORS:
            raise ValueError(f"unknown product.from_op={from_op!r}")
        norm_products.append(
            {
                "id": pid,
                "from_op": from_op or None,
                "reusable": bool(prod.get("reusable", True)),
            }
        )
    out["products"] = norm_products

    stages_in = out.get("stages") or {}
    if not isinstance(stages_in, dict):
        raise ValueError("recipe.stages must be an object")
    stages: dict[str, dict[str, Any]] = {}
    for key in STAGE_KEYS:
        raw = stages_in.get(key) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"recipe.stages.{key} must be an object")
        stages[key] = {"enabled": bool(raw.get("enabled", False))}
        if raw.get("model"):
            stages[key]["model"] = str(raw["model"])
        inputs = raw.get("inputs")
        if inputs is not None:
            if not isinstance(inputs, list):
                raise ValueError(f"recipe.stages.{key}.inputs must be a list")
            stages[key]["inputs"] = [str(x).strip() for x in inputs if str(x).strip()]
        if key == "label":
            from hmi.platform.label_model_params import label_stage_extras

            stages[key].update(label_stage_extras(raw))
    out["stages"] = stages

    bbox = out.get("bbox") or {}
    if not isinstance(bbox, dict):
        raise ValueError("recipe.bbox must be an object")
    detector = str(bbox.get("detector") or "opencv").strip().lower()
    if detector not in BBOX_DETECTORS:
        raise ValueError(f"bbox.detector must be opencv|yolo, got {detector!r}")
    out["bbox"] = {
        "enabled": bool(bbox.get("enabled", False)),
        "detector": detector,
        "yolo_classes": str(bbox.get("yolo_classes") or ""),
    }
    graph_in = out.get("graph")
    if isinstance(graph_in, dict) and graph_in.get("nodes"):
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(graph_in)
        proj = project_graph(g)
        out["graph"] = g
        out["slots"] = proj["slots"]
        out["preprocess"] = proj["preprocess"]
        out["products"] = proj["products"]
        out["stages"] = proj["stages"]
        # Graph node params are source of truth; fall back to previous stages.label extras.
        prev_label = ((recipe.get("stages") or {}).get("label") or {})
        if out["stages"]["label"].get("enabled") and prev_label:
            if prev_label.get("model") and not out["stages"]["label"].get("model"):
                out["stages"]["label"]["model"] = prev_label["model"]
            from hmi.platform.label_model_params import label_stage_extras

            extras = label_stage_extras(out["stages"]["label"])
            if not extras:
                extras = label_stage_extras(prev_label)
            out["stages"]["label"].update(extras)
        out["bbox"] = proj["bbox"]
        out["require_any_kinds"] = proj["require_any_kinds"]
    out["overview"] = hydrate_overview(out)
    if not str(out.get("overview", {}).get("preset") or "").strip():
        out["overview"]["preset"] = view
    return out


def _gnode(
    key: str,
    ntype: str,
    op_id: str,
    title: str,
    x: float,
    y: float,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": ntype,
        "op_id": op_id,
        "title": title,
        "params": dict(params or {}),
        "position": {"x": x, "y": y},
    }


def _gedge(src: str, tgt: str, source_port: str = "out", target_port: str = "in") -> dict[str, Any]:
    return {
        "id": f"{src}->{tgt}",
        "source": src,
        "source_port": source_port,
        "target": tgt,
        "target_port": target_port,
    }


def _list_cards(*widget_ids: str) -> list[dict[str, Any]]:
    return [{"key": f"list-{wid}", "widget_id": wid, "bindings": {}} for wid in widget_ids]


def _spectrum_cards(step_key: str, n: int, sync: str) -> list[dict[str, Any]]:
    return [
        {
            "key": f"detail-spectrum-ch{i}",
            "widget_id": "spectrum_timeline",
            "sync_group": sync,
            "bindings": {
                "in": {"kind": "upstream", "step_key": step_key, "port_id": f"ch{i}"},
            },
        }
        for i in range(1, n + 1)
    ]


def _video_cards(step_key: str, n: int, sync: str) -> list[dict[str, Any]]:
    return [
        {
            "key": f"detail-video-ch{i}",
            "widget_id": "video_timeline",
            "sync_group": sync,
            "bindings": {
                "in": {"kind": "upstream", "step_key": step_key, "port_id": f"ch{i}"},
            },
        }
        for i in range(1, n + 1)
    ]


def _labels_card() -> dict[str, Any]:
    return {"key": "detail-labels", "widget_id": "labels_tree", "bindings": {}}


def _oms_cabin_graph() -> dict[str, Any]:
    """Authored cabin DAG: catalog/palette ops only (no linear prep-N hydrate aliases)."""
    parse = OPERATORS["parse_bag"]
    extract = OPERATORS["extract_frames"]
    encode = OPERATORS["encode_preview"]
    asr = OPERATORS["transcribe"]
    embed = STAGE_OPERATORS["embed"]
    label = STAGE_OPERATORS["label"]
    modalities = list(PARSE_BAG_MODALITIES)
    return {
        "nodes": [
            _gnode(
                "rosbag",
                "source",
                "source",
                "舱内 bag",
                40,
                0,
                {
                    "kinds": [".bag"],
                    "cardinality_min": 1,
                    "cardinality_max": 8,
                    "role": "bag",
                    "required": False,
                },
            ),
            _gnode(
                "video",
                "source",
                "source",
                "舱内视频",
                240,
                0,
                {
                    "kinds": sorted(VIDEO_EXTS),
                    "cardinality_min": 1,
                    "cardinality_max": 4,
                    "role": "video",
                    "required": False,
                },
            ),
            _gnode(
                "image",
                "source",
                "source",
                "舱内图片",
                440,
                0,
                {
                    "kinds": sorted(IMAGE_EXTS),
                    "cardinality_min": 1,
                    "cardinality_max": 64,
                    "role": "frame",
                    "required": False,
                },
            ),
            _gnode(
                "audio",
                "source",
                "source",
                "舱内音频",
                640,
                0,
                {
                    "kinds": sorted(AUDIO_EXTS),
                    "cardinality_min": 1,
                    "cardinality_max": 4,
                    "role": "audio",
                    "required": False,
                },
            ),
            _gnode(
                "parse_bag",
                "op",
                "parse_bag",
                str(parse["title"]),
                40,
                140,
                {
                    "when_kind": ".bag",
                    "produces": modalities,
                    "emit_modalities": modalities,
                },
            ),
            _gnode(
                "extract_frames",
                "op",
                "extract_frames",
                str(extract["title"]),
                240,
                280,
                {"when_kind": ".mp4", "produces": ["frames"]},
            ),
            _gnode(
                "encode_preview",
                "op",
                "encode_preview",
                str(encode["title"]),
                440,
                420,
                {"when_kind": ".jpg", "produces": ["preview_mp4"], "channel_count": 4},
            ),
            _gnode(
                "transcribe",
                "op",
                "transcribe",
                str(asr["title"]),
                640,
                560,
                {"when_kind": ".wav", "produces": ["asr_jsonl"]},
            ),
            _gnode("embed", "op", "embed", str(embed["title"]), 440, 700, {}),
            _gnode(
                "stage-label",
                "label",
                "label",
                str(label["title"]),
                440,
                840,
                {"model": "default"},
            ),
        ],
        "edges": [
            _gedge("rosbag", "parse_bag"),
            _gedge("parse_bag", "extract_frames"),
            _gedge("video", "extract_frames"),
            _gedge("extract_frames", "encode_preview"),
            _gedge("image", "encode_preview"),
            _gedge("audio", "transcribe"),
            _gedge("transcribe", "embed"),
            _gedge("embed", "stage-label"),
        ],
    }


def _ivi_ui_graph() -> dict[str, Any]:
    """Authored IVI DAG: catalog ops only (no linear prep-N hydrate aliases)."""
    extract = OPERATORS["extract_frames"]
    detect = OPERATORS["detect_bbox"]
    label = STAGE_OPERATORS["label"]
    return {
        "nodes": [
            _gnode(
                "ui_media",
                "source",
                "source",
                "IVI 画面",
                80,
                0,
                {
                    "kinds": sorted(VIDEO_EXTS | IMAGE_EXTS),
                    "cardinality_min": 1,
                    "cardinality_max": 32,
                    "role": "primary",
                    "required": True,
                },
            ),
            _gnode(
                "extract_frames",
                "op",
                "extract_frames",
                str(extract["title"]),
                80,
                160,
                {"when_kind": ".mp4", "produces": ["frames"]},
            ),
            _gnode(
                "detect_bbox",
                "op",
                "detect_bbox",
                str(detect["title"]),
                80,
                320,
                {
                    "when_kind": None,
                    "produces": ["bboxes_jsonl"],
                    "detector": "opencv",
                    "yolo_classes": "",
                    "required": True,
                },
            ),
            _gnode(
                "stage-label",
                "label",
                "label",
                str(label["title"]),
                80,
                480,
                {"model": "default"},
            ),
        ],
        "edges": [
            _gedge("ui_media", "extract_frames"),
            _gedge("extract_frames", "detect_bbox"),
            _gedge("ui_media", "detect_bbox"),
            _gedge("detect_bbox", "stage-label"),
        ],
    }


def _audio_array_graph() -> dict[str, Any]:
    """Authored NVH DAG: catalog spectrogram ops only (no prep-N / transcribe aliases)."""
    parse_dat = OPERATORS["parse_head_dat"]
    stft = OPERATORS["stft_spectrogram"]
    mel = OPERATORS["mel_spectrogram"]
    third = OPERATORS["third_octave"]
    spl = OPERATORS["spl_timeline"]
    label = STAGE_OPERATORS["label"]
    return {
        "nodes": [
            _gnode(
                "audio_primary",
                "source",
                "source",
                "阵列音频",
                80,
                0,
                {
                    "kinds": sorted(AUDIO_EXTS),
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                    "role": "primary",
                    "required": True,
                },
            ),
            _gnode(
                "parse_head_dat",
                "op",
                "parse_head_dat",
                str(parse_dat["title"]),
                80,
                140,
                {"when_kind": ".dat", "produces": ["pcm_pa"], "required": False},
            ),
            _gnode(
                "stft_spectrogram",
                "op",
                "stft_spectrogram",
                str(stft["title"]),
                80,
                260,
                {"when_kind": ".wav", "produces": ["stft_matrix"], "required": True, "channel_count": 4},
            ),
            _gnode(
                "mel_spectrogram",
                "op",
                "mel_spectrogram",
                str(mel["title"]),
                80,
                380,
                {"when_kind": ".wav", "produces": ["mel_png"], "required": True, "channel_count": 4},
            ),
            _gnode(
                "third_octave",
                "op",
                "third_octave",
                str(third["title"]),
                80,
                500,
                {"when_kind": ".wav", "produces": ["third_octave"], "required": True, "channel_count": 4},
            ),
            _gnode(
                "spl_timeline",
                "op",
                "spl_timeline",
                str(spl["title"]),
                80,
                620,
                {"when_kind": ".wav", "produces": ["spl_timeline"], "required": True, "channel_count": 4},
            ),
            _gnode(
                "stage-label",
                "label",
                "label",
                str(label["title"]),
                80,
                740,
                {"model": "nvh_sem_ast"},
            ),
        ],
        "edges": [
            _gedge("audio_primary", "parse_head_dat"),
            _gedge("parse_head_dat", "stft_spectrogram"),
            _gedge("stft_spectrogram", "mel_spectrogram"),
            _gedge("mel_spectrogram", "third_octave"),
            _gedge("third_octave", "spl_timeline"),
            _gedge("spl_timeline", "stage-label"),
        ],
    }


def _audio_defect_graph() -> dict[str, Any]:
    """Copied from live DataType ``test``: wav + JSON tag → if → label_tree_input."""
    json_src = "op-source-1788845633260"
    extract = "op-json_extract-1788845651418"
    mel = "op-mel_spectrogram-1788845699364"
    octave = "op-third_octave-1788845718012"
    spl = "op-spl_timeline-1788845725414"
    cond = "op-if-1788845784271"
    fill_yes = "op-label_tree_input-1788845853076"
    fill_no = "op-label_tree_input-1788845889559"
    return {
        "nodes": [
            {
                **_gnode(
                    "src-1",
                    "source",
                    "source",
                    "录音",
                    80.0,
                    0.0,
                    {
                        "kinds": [".wav"],
                        "required": True,
                        "cardinality_min": 1,
                        "cardinality_max": 1,
                    },
                ),
            },
            {
                **_gnode(
                    json_src,
                    "source",
                    "source",
                    "标签",
                    276.7751937984496,
                    0.8062015503875877,
                    {
                        "kinds": [".json"],
                        "required": True,
                        "cardinality_min": 1,
                        "cardinality_max": 1,
                    },
                ),
            },
            {
                **_gnode(
                    extract,
                    "op",
                    "json_extract",
                    str(OPERATORS["json_extract"]["title"]),
                    275.72180451127815,
                    108.38279781484962,
                    {"path_keys": ["tag"], "required": True},
                ),
                "bindings": {"in": {"kind": "slot", "slot_id": json_src}},
            },
            {
                **_gnode(
                    mel,
                    "op",
                    "mel_spectrogram",
                    str(OPERATORS["mel_spectrogram"]["title"]),
                    78.38696148459601,
                    108.89530239219205,
                    {"required": True},
                ),
                "bindings": {"in": {"kind": "slot", "slot_id": "src-1"}},
            },
            {
                **_gnode(
                    octave,
                    "op",
                    "third_octave",
                    str(OPERATORS["third_octave"]["title"]),
                    -127.34210526315783,
                    106.6648701832707,
                    {},
                ),
                "bindings": {"in": {"kind": "slot", "slot_id": "src-1"}},
            },
            {
                **_gnode(
                    spl,
                    "op",
                    "spl_timeline",
                    str(OPERATORS["spl_timeline"]["title"]),
                    -326.1052631578946,
                    106.07339638157899,
                    {},
                ),
                "bindings": {"in": {"kind": "slot", "slot_id": "src-1"}},
            },
            {
                **_gnode(
                    cond,
                    "if",
                    "if",
                    "条件",
                    275.1304948718771,
                    216.9436444226141,
                    {},
                ),
                "condition": {
                    "all": [
                        {
                            "field": f"{extract}.value",
                            "op": "eq",
                            "value": "有问题噪音",
                        }
                    ]
                },
            },
            {
                **_gnode(
                    fill_yes,
                    "op",
                    "label_tree_input",
                    str(OPERATORS["label_tree_input"]["title"]),
                    188.00912716478246,
                    359.9748896357209,
                    {
                        "assignments": [
                            {
                                "label_id": "audio.defect.has_problem",
                                "mode": "const",
                                "value": "是",
                            }
                        ],
                        "required": True,
                    },
                ),
            },
            {
                **_gnode(
                    fill_no,
                    "op",
                    "label_tree_input",
                    str(OPERATORS["label_tree_input"]["title"]),
                    420.2857142857143,
                    362.33805216165416,
                    {
                        "assignments": [
                            {
                                "label_id": "audio.defect.has_problem",
                                "mode": "const",
                                "value": "否",
                            }
                        ],
                        "required": True,
                    },
                ),
            },
        ],
        "edges": [
            {
                "id": f"{json_src}-out->{extract}-in",
                "source": json_src,
                "source_port": "out",
                "target": extract,
                "target_port": "in",
            },
            {
                "id": f"src-1-out->{mel}-in",
                "source": "src-1",
                "source_port": "out",
                "target": mel,
                "target_port": "in",
            },
            {
                "id": f"src-1-out->{octave}-in",
                "source": "src-1",
                "source_port": "out",
                "target": octave,
                "target_port": "in",
            },
            {
                "id": f"src-1-out->{spl}-in",
                "source": "src-1",
                "source_port": "out",
                "target": spl,
                "target_port": "in",
            },
            {
                "id": f"{extract}-out->{cond}-in",
                "source": extract,
                "source_port": "out",
                "target": cond,
                "target_port": "in",
            },
            {
                "id": f"{cond}-then->{fill_yes}-in",
                "source": cond,
                "source_port": "then",
                "target": fill_yes,
                "target_port": "in",
            },
            {
                "id": f"{cond}-else->{fill_no}-in",
                "source": cond,
                "source_port": "else",
                "target": fill_no,
                "target_port": "in",
            },
        ],
    }


SEED_RECIPES: dict[str, dict[str, Any]] = {
    "oms_cabin": {
        "id": "oms_cabin",
        "title": "舱内 OMS/DMS 多模",
        "purpose": "舱内人机共驾多模场景打标（画面 + 语音 + 结构化标签）",
        "owner": "platform",
        "taxonomy_id": OMS_TAXONOMY_ID,
        "overview_view": "custom",
        "overview": {
            "preset": "custom",
            "list": _list_cards("clip_metrics", "label_search", "clip_table"),
            "detail": [
                *_video_cards("encode_preview", 4, "cabin-main"),
                {"key": "detail-asr", "widget_id": "asr_panel", "bindings": {}},
                _labels_card(),
            ],
        },
        "status": "published",
        "require_any_kinds": singleton_kind_groups(
            ".bag", *sorted(VIDEO_EXTS), *sorted(IMAGE_EXTS), *sorted(AUDIO_EXTS)
        ),
        "slots": [
            {"id": "rosbag", "title": "舱内 bag", "kinds": [".bag"], "cardinality_min": 1, "cardinality_max": 8, "role": "bag", "required": False},
            {"id": "video", "title": "舱内视频", "kinds": sorted(VIDEO_EXTS), "cardinality_min": 1, "cardinality_max": 4, "role": "video", "required": False},
            {"id": "image", "title": "舱内图片", "kinds": sorted(IMAGE_EXTS), "cardinality_min": 1, "cardinality_max": 64, "role": "frame", "required": False},
            {"id": "audio", "title": "舱内音频", "kinds": sorted(AUDIO_EXTS), "cardinality_min": 1, "cardinality_max": 4, "role": "audio", "required": False},
        ],
        "preprocess": [
            {"op_id": "parse_bag", "when_kind": ".bag", "required": False, "produces": list(PARSE_BAG_MODALITIES)},
            {"op_id": "extract_frames", "when_kind": ".mp4", "required": False, "produces": ["frames"]},
            {"op_id": "encode_preview", "when_kind": ".jpg", "required": False, "produces": ["preview_mp4"]},
            {"op_id": "transcribe", "when_kind": ".wav", "required": False, "produces": ["asr_jsonl"]},
        ],
        "products": [
            {"id": "preview_mp4", "from_op": "encode_preview", "reusable": True},
            {"id": "asr_jsonl", "from_op": "transcribe", "reusable": True},
        ],
        "stages": {"label": {"enabled": True, "model": "default"}, "embed": {"enabled": True}},
        "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
        "graph": _oms_cabin_graph(),
    },
    "ivi_ui_stub": {
        "id": "ivi_ui_stub",
        "title": "车机 UI（占位）",
        "purpose": "车机界面抽帧 + bbox 的可插拔占位类型（第一切片不要求业务效果）",
        "owner": "platform",
        "taxonomy_id": IVI_TAXONOMY_ID,
        "overview_view": "custom",
        "overview": {
            "preset": "custom",
            "list": _list_cards("clip_metrics", "clip_table"),
            "detail": [
                {"key": "detail-gallery", "widget_id": "frame_gallery_bbox", "bindings": {}},
                _labels_card(),
            ],
        },
        "status": "published",
        "require_any_kinds": singleton_kind_groups(*sorted(VIDEO_EXTS), *sorted(IMAGE_EXTS)),
        "slots": [
            {
                "id": "ui_media",
                "title": "IVI 画面",
                "kinds": sorted(VIDEO_EXTS | IMAGE_EXTS),
                "cardinality_min": 1,
                "cardinality_max": 32,
                "role": "primary",
                "required": True,
            }
        ],
        "preprocess": [
            {"op_id": "extract_frames", "when_kind": ".mp4", "required": False, "produces": ["frames"]},
            {"op_id": "detect_bbox", "when_kind": None, "required": True, "produces": ["bboxes_jsonl"]},
        ],
        "products": [{"id": "bboxes_jsonl", "from_op": "detect_bbox", "reusable": True}],
        "stages": {"label": {"enabled": True, "model": "default"}, "embed": {"enabled": False}},
        "bbox": {"enabled": True, "detector": "opencv", "yolo_classes": ""},
        "graph": _ivi_ui_graph(),
    },
    "audio_array_spec": {
        "id": "audio_array_spec",
        "title": "麦克风阵列频谱",
        "purpose": (
            "四通道同步声压频谱（STFT / 梅尔 / 1/3 倍频程 / SPL）；"
            "客观 NVH 由 deriver；L6 语义由 stages.label（nvh_sem_ast AudioSet，heuristic 填等级）；"
            "绑定 draft audio_nvh-v2，勿全局 publish"
        ),
        "owner": "platform",
        "taxonomy_id": AUDIO_NVH_TAXONOMY_ID,
        "taxonomy_version_code": "audio_nvh-v2",
        "overview_view": "custom",
        "overview": {
            "preset": "custom",
            "list": _list_cards("clip_metrics", "nvh_spl_column", "clip_table"),
            "detail": [
                *_spectrum_cards("mel_spectrogram", 4, "nvh-main"),
                _labels_card(),
            ],
        },
        "status": "published",
        "require_any_kinds": singleton_kind_groups(*sorted(AUDIO_EXTS)),
        "slots": [
            {
                "id": "audio_primary",
                "title": "阵列音频",
                "kinds": sorted(AUDIO_EXTS),
                "cardinality_min": 1,
                "cardinality_max": 1,
                "role": "primary",
                "required": True,
            }
        ],
        "preprocess": [
            {"op_id": "parse_head_dat", "when_kind": ".dat", "required": False, "inputs": ["audio_primary"], "produces": ["pcm_pa"]},
            {"op_id": "stft_spectrogram", "when_kind": ".wav", "required": True, "inputs": ["audio_primary"], "produces": ["stft_matrix"]},
            {"op_id": "mel_spectrogram", "when_kind": ".wav", "required": True, "inputs": ["audio_primary"], "produces": ["mel_matrix"]},
            {"op_id": "third_octave", "when_kind": ".wav", "required": True, "inputs": ["audio_primary"], "produces": ["third_octave"]},
            {"op_id": "spl_timeline", "when_kind": ".wav", "required": True, "inputs": ["audio_primary"], "produces": ["spl_timeline"]},
        ],
        "products": [
            {"id": "mel_png", "from_op": "mel_spectrogram", "reusable": True},
            {"id": "spl_timeline", "from_op": "spl_timeline", "reusable": True},
        ],
        "stages": {
            "label": {"enabled": True, "model": "nvh_sem_ast"},
            "embed": {"enabled": False},
        },
        "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
        "graph": _audio_array_graph(),
    },
    "audio_defect": {
        "id": "audio_defect",
        "title": "问题音频判定",
        "purpose": (
            "对车内录音片段判定是否存在问题噪音。"
            "源为 wav + AudioLabel 导出 JSON；按 tag 条件写入「是否有问题音频」布尔值。"
        ),
        "owner": "platform",
        "taxonomy_id": AUDIO_DEFECT_TAXONOMY_ID,
        "taxonomy_version_code": AUDIO_DEFECT_VERSION_CODE,
        "overview_view": "custom",
        "overview": {
            "preset": "custom",
            "list": [],
            "detail": [
                {
                    "key": "detail-spectrum_timeline-1788845910941",
                    "widget_id": "spectrum_timeline",
                    "bindings": {
                        "in": [
                            {
                                "kind": "upstream",
                                "step_key": "op-mel_spectrogram-1788845699364",
                                "port_id": "ch1",
                            }
                        ]
                    },
                },
                {
                    "key": "detail-labels_tree-1788846181985",
                    "widget_id": "labels_tree",
                    "bindings": {
                        "in": [
                            {
                                "kind": "upstream",
                                "step_key": "op-label_tree_input-1788845853076",
                                "port_id": "out",
                            },
                            {
                                "kind": "upstream",
                                "step_key": "op-label_tree_input-1788845889559",
                                "port_id": "out",
                            },
                        ]
                    },
                },
            ],
        },
        "status": "published",
        "require_any_kinds": singleton_kind_groups(".wav", ".json"),
        "slots": [
            {
                "id": "src-1",
                "title": "录音",
                "kinds": [".wav"],
                "cardinality_min": 1,
                "cardinality_max": 1,
                "role": "input",
                "required": True,
            },
            {
                "id": "op-source-1788845633260",
                "title": "标签",
                "kinds": [".json"],
                "cardinality_min": 1,
                "cardinality_max": 1,
                "role": "input",
                "required": True,
            },
        ],
        "preprocess": [
            {"op_id": "json_extract", "when_kind": None, "required": False},
            {"op_id": "mel_spectrogram", "when_kind": None, "required": False},
            {"op_id": "third_octave", "when_kind": None, "required": False},
            {"op_id": "spl_timeline", "when_kind": None, "required": False},
        ],
        "products": [],
        "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
        "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
        "graph": _audio_defect_graph(),
    },
}

# Baseline DataTypes restored by 「重置测试数据」. Extra user-created types are dropped.
SEED_DATA_TYPE_IDS: tuple[str, ...] = tuple(SEED_RECIPES)


def eligible_kinds_for_recipe(recipe: dict[str, Any]) -> set[str]:
    """Union of kinds that can satisfy any slot / require_any_kinds group."""
    rec = validate_recipe(recipe)
    kinds: set[str] = set()
    for slot in rec.get("slots") or []:
        kinds.update(slot.get("kinds") or [])
    for group in rec.get("require_any_kinds") or []:
        kinds.update(group)
    return kinds


def seed_recipes() -> dict[str, dict[str, Any]]:
    return {k: validate_recipe(v) for k, v in SEED_RECIPES.items()}
