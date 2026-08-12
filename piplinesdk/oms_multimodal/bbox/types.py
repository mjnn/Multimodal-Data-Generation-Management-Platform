"""Bounding-box types for annotate_bbox capability.

Semantic name for a detection is **element**（元素）— domain-agnostic
(face / person / vehicle / UI widget / …). ``label`` is kept as a
backward-compatible alias of ``element``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def default_element_name() -> str:
    """Canonical element name when a detector does not supply a class label.

    Env ``BBOX_ELEMENT`` (alias ``BBOX_ELEMENT_LABEL``), default ``element``.
    """
    return (
        os.getenv("BBOX_ELEMENT", "").strip()
        or os.getenv("BBOX_ELEMENT_LABEL", "").strip()
        or "element"
    )


@dataclass
class BBox:
    """Axis-aligned box in pixel coordinates (xyxy).

    ``element`` is the preferred field for what was detected (通用元素).
    ``label`` mirrors ``element`` for older consumers.

    Optional face attributes (OpenCV cabin path):

    - ``gender``: ``male`` / ``female``
    - ``age_range``: bucket like ``25-32``
    - ``age_approx``: midpoint int for ``~28y`` captions
    - ``gender_score`` / ``age_score``: attribute confidences in ``[0, 1]``
    """

    x1: float
    y1: float
    x2: float
    y2: float
    element: str = ""
    label: str = ""
    score: float | None = None
    class_id: int | None = None
    gender: str | None = None
    age_range: str | None = None
    age_approx: int | None = None
    gender_score: float | None = None
    age_score: float | None = None

    def __post_init__(self) -> None:
        if self.element and not self.label:
            self.label = self.element
        elif self.label and not self.element:
            self.element = self.label
        if self.gender:
            self.gender = str(self.gender).strip().lower() or None
        if self.age_range:
            self.age_range = str(self.age_range).strip().strip("()") or None
        if self.age_approx is not None:
            try:
                self.age_approx = int(self.age_approx)
            except (TypeError, ValueError):
                self.age_approx = None
        for attr in ("gender_score", "age_score", "score"):
            val = getattr(self, attr)
            if val is None:
                continue
            try:
                setattr(self, attr, float(val))
            except (TypeError, ValueError):
                setattr(self, attr, None)

    def base_name(self) -> str:
        """Element / class name without gender/age suffix."""
        return (self.element or self.label or "").strip()

    def display_name(self) -> str:
        """Caption for draw / prompts — includes face attrs when present.

        Example: ``face/female/~28y``.
        """
        from .face_attrs import format_face_attr_label

        base = self.base_name()
        if self.gender or self.age_range or self.age_approx is not None:
            return format_face_attr_label(
                base or "element",
                gender=self.gender,
                age_range=self.age_range,
                age_approx=self.age_approx,
            )
        return base

    def to_dict(self) -> dict[str, Any]:
        name = self.base_name()
        out: dict[str, Any] = {
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "element": name,
            "label": name,  # alias for older readers
            "score": self.score,
            "class_id": self.class_id,
        }
        if self.gender:
            out["gender"] = self.gender
        if self.age_range:
            out["age_range"] = self.age_range
        if self.age_approx is not None:
            out["age_approx"] = self.age_approx
        if self.gender_score is not None:
            out["gender_score"] = self.gender_score
        if self.age_score is not None:
            out["age_score"] = self.age_score
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BBox:
        name = str(raw.get("element") or raw.get("label") or "")

        def _opt_float(key: str) -> float | None:
            if raw.get(key) is None:
                return None
            try:
                return float(raw[key])
            except (TypeError, ValueError):
                return None

        def _opt_int(key: str) -> int | None:
            if raw.get(key) is None:
                return None
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                return None

        return cls(
            x1=float(raw["x1"]),
            y1=float(raw["y1"]),
            x2=float(raw["x2"]),
            y2=float(raw["y2"]),
            element=name,
            label=name,
            score=_opt_float("score"),
            class_id=_opt_int("class_id"),
            gender=str(raw["gender"]) if raw.get("gender") is not None else None,
            age_range=str(raw["age_range"]) if raw.get("age_range") is not None else None,
            age_approx=_opt_int("age_approx"),
            gender_score=_opt_float("gender_score"),
            age_score=_opt_float("age_score"),
        )


@dataclass
class FrameBBoxes:
    """Detections for one frame (elements with boxes)."""

    clip_id: str
    topic: str
    timestamp_ns: int
    image_path: str
    boxes: list[BBox] = field(default_factory=list)
    annotated_image_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "topic": self.topic,
            "timestamp_ns": self.timestamp_ns,
            "image_path": self.image_path,
            "annotated_image_path": self.annotated_image_path,
            "boxes": [b.to_dict() for b in self.boxes],
            "elements": [b.to_dict() for b in self.boxes],  # explicit alias
        }
