"""DataType recipe validation and built-in seeds."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hmi.platform.operators import BBOX_DETECTORS, OPERATORS, SOURCE_KINDS
from hmi.platform.views import VIEW_TEMPLATE_IDS

RECIPE_STATUSES = frozenset({"draft", "published"})
STAGE_KEYS = ("label", "embed")

OMS_TAXONOMY_ID = "oms"
IVI_TAXONOMY_ID = "ivi_ui_stub"
AUDIO_NVH_TAXONOMY_ID = "audio_nvh"


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
            k = str(kind).strip().lower()
            if k not in SOURCE_KINDS:
                raise ValueError(f"unknown source kind={k!r}")
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
            k = str(kind).strip().lower()
            if k not in SOURCE_KINDS:
                raise ValueError(f"unknown slot kind={k!r}")
            skinds.append(k)
        cmin = int(slot.get("cardinality_min") or 1)
        cmax = int(slot.get("cardinality_max") or cmin)
        if cmin < 0 or cmax < cmin:
            raise ValueError(f"slot {slot_id!r} has invalid cardinality")
        norm_slots.append(
            {
                "id": slot_id,
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
        if op_id not in OPERATORS:
            raise ValueError(f"unknown op_id={op_id!r}")
        when_kind = step.get("when_kind")
        if when_kind is not None:
            wk = str(when_kind).strip().lower()
            if wk not in SOURCE_KINDS:
                raise ValueError(f"unknown when_kind={wk!r}")
            when_kind = wk
        produces = step.get("produces")
        if produces is not None and not isinstance(produces, list):
            raise ValueError(f"preprocess {op_id}.produces must be a list")
        inputs = step.get("inputs")
        if inputs is not None and not isinstance(inputs, list):
            raise ValueError(f"preprocess {op_id}.inputs must be a list")
        entry: dict[str, Any] = {
            "op_id": op_id,
            "when_kind": when_kind,
            "required": bool(step.get("required", False)),
        }
        if inputs is not None:
            entry["inputs"] = [str(x).strip() for x in inputs if str(x).strip()]
        if produces is not None:
            entry["produces"] = [str(x).strip() for x in produces if str(x).strip()]
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
    return out


SEED_RECIPES: dict[str, dict[str, Any]] = {
    "oms_cabin": {
        "id": "oms_cabin",
        "title": "舱内 OMS/DMS 多模",
        "purpose": "舱内人机共驾多模场景打标（画面 + 语音 + 结构化标签）",
        "owner": "platform",
        "taxonomy_id": OMS_TAXONOMY_ID,
        "overview_view": "cabin_timeline",
        "status": "published",
        "require_any_kinds": [["rosbag"], ["video"], ["image"], ["audio"]],
        "slots": [
            {"id": "rosbag", "kinds": ["rosbag"], "cardinality_min": 1, "cardinality_max": 8, "role": "bag", "required": False},
            {"id": "video", "kinds": ["video"], "cardinality_min": 1, "cardinality_max": 4, "role": "video", "required": False},
            {"id": "image", "kinds": ["image"], "cardinality_min": 1, "cardinality_max": 64, "role": "frame", "required": False},
            {"id": "audio", "kinds": ["audio"], "cardinality_min": 1, "cardinality_max": 4, "role": "audio", "required": False},
        ],
        "preprocess": [
            {"op_id": "parse_bag", "when_kind": "rosbag", "required": False, "produces": ["frames_audio_topics"]},
            {"op_id": "extract_frames", "when_kind": "video", "required": False, "produces": ["frames"]},
            {"op_id": "encode_preview", "when_kind": "image", "required": False, "produces": ["preview_mp4"]},
            {"op_id": "transcribe", "when_kind": "audio", "required": False, "produces": ["asr_jsonl"]},
            {"op_id": "mel_spectrogram", "when_kind": "audio", "required": False, "produces": ["mel_matrix"]},
            {"op_id": "text_to_json", "when_kind": "text", "required": False, "produces": ["structured_json"]},
            {"op_id": "detect_bbox", "when_kind": None, "required": False, "produces": ["bboxes_jsonl"]},
        ],
        "products": [
            {"id": "preview_mp4", "from_op": "encode_preview", "reusable": True},
            {"id": "asr_jsonl", "from_op": "transcribe", "reusable": True},
            {"id": "bboxes_jsonl", "from_op": "detect_bbox", "reusable": True},
        ],
        "stages": {"label": {"enabled": True, "model": "default"}, "embed": {"enabled": True}},
        "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
    },
    "ivi_ui_stub": {
        "id": "ivi_ui_stub",
        "title": "车机 UI（占位）",
        "purpose": "车机界面抽帧 + bbox 的可插拔占位类型（第一切片不要求业务效果）",
        "owner": "platform",
        "taxonomy_id": IVI_TAXONOMY_ID,
        "overview_view": "frame_gallery_bbox",
        "status": "published",
        "require_any_kinds": [["video"], ["image"]],
        "slots": [
            {
                "id": "ui_media",
                "kinds": ["video", "image"],
                "cardinality_min": 1,
                "cardinality_max": 32,
                "role": "primary",
                "required": True,
            }
        ],
        "preprocess": [
            {"op_id": "extract_frames", "when_kind": "video", "required": False, "produces": ["frames"]},
            {"op_id": "detect_bbox", "when_kind": None, "required": True, "produces": ["bboxes_jsonl"]},
        ],
        "products": [{"id": "bboxes_jsonl", "from_op": "detect_bbox", "reusable": True}],
        "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
        "bbox": {"enabled": True, "detector": "opencv", "yolo_classes": ""},
    },
    "audio_array_spec": {
        "id": "audio_array_spec",
        "title": "麦克风阵列频谱",
        "purpose": (
            "四通道同步声压频谱（STFT / 梅尔 / 1/3 倍频程 / SPL）；"
            "客观 NVH 由 deriver；L6 语义由 stages.label（默认 nvh_sem_heuristic，可选 nvh_sem_vl）；"
            "绑定 draft audio_nvh-v2，勿全局 publish"
        ),
        "owner": "platform",
        "taxonomy_id": AUDIO_NVH_TAXONOMY_ID,
        "taxonomy_version_code": "audio_nvh-v2",
        "overview_view": "audio_nvh_timeline",
        "status": "published",
        "require_any_kinds": [["audio"]],
        "slots": [
            {
                "id": "audio_primary",
                "kinds": ["audio"],
                "cardinality_min": 1,
                "cardinality_max": 1,
                "role": "primary",
                "required": True,
            }
        ],
        "preprocess": [
            {"op_id": "parse_head_dat", "when_kind": "audio", "required": False, "inputs": ["audio_primary"], "produces": ["pcm_pa"]},
            {"op_id": "stft_spectrogram", "when_kind": "audio", "required": True, "inputs": ["audio_primary"], "produces": ["stft_matrix"]},
            {"op_id": "mel_spectrogram", "when_kind": "audio", "required": True, "inputs": ["audio_primary"], "produces": ["mel_matrix"]},
            {"op_id": "third_octave", "when_kind": "audio", "required": True, "inputs": ["audio_primary"], "produces": ["third_octave"]},
            {"op_id": "spl_timeline", "when_kind": "audio", "required": True, "inputs": ["audio_primary"], "produces": ["spl_timeline"]},
        ],
        "products": [
            {"id": "mel_png", "from_op": "mel_spectrogram", "reusable": True},
            {"id": "spl_timeline", "from_op": "spl_timeline", "reusable": True},
        ],
        "stages": {
            "label": {"enabled": True, "model": "nvh_sem_heuristic"},
            "embed": {"enabled": False},
        },
        "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
    },
}


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
