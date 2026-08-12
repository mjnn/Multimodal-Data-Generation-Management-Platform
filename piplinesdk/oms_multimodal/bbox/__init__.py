"""Bounding-box detection helpers for annotate_bbox capability.

Detections are domain-agnostic **elements**（元素）; backends (opencv/yolo/…)
are pluggable via ``BBOX_DETECTOR``.
"""
from __future__ import annotations

from .detector import (
    BBoxDetector,
    CABIN_LEFTOVER_COCO_NAMES,
    COCO80_CLASS_NAMES,
    NoOpDetector,
    OpenCvFaceDetector,
    OpenCvHaarDetector,
    StubDetector,
    YoloDetector,
    list_detectors,
    list_yolo_class_catalog,
    list_yolo_class_presets,
    require_yolo_extra,
    resolve_detector,
    resolve_haar_cascade_path,
    resolve_yolo_class_ids,
    resolve_yunet_model_path,
    yolo_available,
)
from .draw import draw_bboxes_on_image
from .face_attrs import (
    age_approx_from_range,
    box_prompt_name,
    face_attrs_enabled,
    format_face_attr_label,
    get_face_attr_estimator,
    reset_face_attr_estimator,
)
from .prompt_context import load_bbox_context_by_clip, summarize_bboxes_for_prompt
from .types import BBox, FrameBBoxes, default_element_name

__all__ = [
    "BBox",
    "BBoxDetector",
    "CABIN_LEFTOVER_COCO_NAMES",
    "COCO80_CLASS_NAMES",
    "FrameBBoxes",
    "NoOpDetector",
    "OpenCvFaceDetector",
    "OpenCvHaarDetector",
    "StubDetector",
    "YoloDetector",
    "age_approx_from_range",
    "box_prompt_name",
    "default_element_name",
    "draw_bboxes_on_image",
    "face_attrs_enabled",
    "format_face_attr_label",
    "get_face_attr_estimator",
    "list_detectors",
    "list_yolo_class_catalog",
    "list_yolo_class_presets",
    "load_bbox_context_by_clip",
    "require_yolo_extra",
    "reset_face_attr_estimator",
    "resolve_detector",
    "resolve_haar_cascade_path",
    "resolve_yolo_class_ids",
    "resolve_yunet_model_path",
    "summarize_bboxes_for_prompt",
    "yolo_available",
]
