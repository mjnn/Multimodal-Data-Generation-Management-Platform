"""Pluggable frame detectors for annotate_bbox.

Detected objects are **elements**（元素）— not tied to any single domain
(face / person / vehicle / …). Choose a backend via ``BBOX_DETECTOR``;
set default element name with ``BBOX_ELEMENT`` (default ``element``).

Backends:

- ``noop`` — no boxes (default)
- ``stub`` / ``fake`` — centered fake box for smoke tests
- ``opencv`` / ``haar`` / ``face`` — OpenCV Haar cascade (one concrete backend;
  element name from ``BBOX_ELEMENT``, default ``element``)
- ``yolo`` — Ultralytics YOLO; class names become element names
  (optional extra ``oms-multimodal-sdk[bbox]``)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Protocol

from PIL import Image

from .types import BBox, default_element_name

logger = logging.getLogger(__name__)

_DEFAULT_CASCADE_FILE = "haarcascade_frontalface_default.xml"
_DEFAULT_YUNET_FILE = "face_detection_yunet_2023mar.onnx"
_PKG_CASCADE_DIR = Path(__file__).resolve().parent / "data"


def resolve_haar_cascade_path(cascade_name: str | None = None) -> Path:
    """Resolve a Haar cascade XML path for OpenCvHaarDetector (OpenCV 4.x).

    Lookup order:

    1. ``cascade_name`` / ``BBOX_OPENCV_CASCADE`` if it is an existing file path
       (absolute or relative)
    2. ``cv2.data.haarcascades`` + bare filename (OpenCV 4.x full wheels)
    3. Package-bundled ``oms_multimodal/bbox/data/<filename>``
       (covers headless wheels that ship an empty ``cv2/data``)

    Raises:
        RuntimeError: with tried paths and install / env hints when nothing matches.
    """
    raw = (cascade_name if cascade_name is not None else os.getenv("BBOX_OPENCV_CASCADE", "")).strip()
    candidates: list[Path] = []

    if raw:
        as_path = Path(raw).expanduser()
        candidates.append(as_path)
        cascade_file = as_path.name if as_path.suffix.lower() == ".xml" else raw
    else:
        cascade_file = _DEFAULT_CASCADE_FILE

    try:
        import cv2

        haarcascades = getattr(getattr(cv2, "data", None), "haarcascades", None)
        if haarcascades:
            candidates.append(Path(haarcascades) / cascade_file)
    except ImportError:
        pass

    candidates.append(_PKG_CASCADE_DIR / cascade_file)
    return _first_existing_file(
        candidates,
        kind="OpenCV Haar cascade",
        hints=(
            "opencv-python-headless often ships an empty cv2/data/ without XML cascades.\n"
            "Fix options:\n"
            "  - leave defaults (SDK bundles haarcascade_frontalface_default.xml), or\n"
            "  - set BBOX_OPENCV_CASCADE to an absolute path to a .xml cascade, or\n"
            "  - use BBOX_DETECTOR=stub for local HMI smoke without real detection"
        ),
    )


def resolve_yunet_model_path(model_name: str | None = None) -> Path:
    """Resolve YuNet ONNX path for OpenCV 5 ``FaceDetectorYN`` fallback."""
    raw = (model_name if model_name is not None else os.getenv("BBOX_OPENCV_YUNET", "")).strip()
    candidates: list[Path] = []
    if raw:
        as_path = Path(raw).expanduser()
        candidates.append(as_path)
        model_file = as_path.name if as_path.suffix.lower() == ".onnx" else raw
    else:
        model_file = _DEFAULT_YUNET_FILE
    candidates.append(_PKG_CASCADE_DIR / model_file)
    return _first_existing_file(
        candidates,
        kind="OpenCV YuNet face model",
        hints=(
            "OpenCV 5 removed CascadeClassifier from the main package.\n"
            "Fix options:\n"
            "  - leave defaults (SDK bundles face_detection_yunet_2023mar.onnx), or\n"
            "  - set BBOX_OPENCV_YUNET to an absolute path to a YuNet .onnx, or\n"
            "  - pip install 'opencv-python-headless<5' to restore Haar CascadeClassifier, or\n"
            "  - use BBOX_DETECTOR=stub for local HMI smoke without real detection"
        ),
    )


def _first_existing_file(candidates: list[Path], *, kind: str, hints: str) -> Path:
    tried: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        tried.append(key)
        if path.is_file():
            return path.resolve()
    tried_fmt = "\n  - ".join(tried) if tried else "(none)"
    raise RuntimeError(f"{kind} not found.\nTried:\n  - {tried_fmt}\n{hints}")


class BBoxDetector(Protocol):
    """Detect elements on a single image. Implementations must be pickle-free for DPE."""

    name: str

    def detect(self, image_path: str | Path) -> list[BBox]:
        ...


class NoOpDetector:
    """Returns no boxes (annotate still copies/skips drawing)."""

    name = "noop"

    def detect(self, image_path: str | Path) -> list[BBox]:
        return []


class StubDetector:
    """Centered fake box for pipeline smoke tests."""

    name = "stub"

    def detect(self, image_path: str | Path) -> list[BBox]:
        with Image.open(image_path) as im:
            w, h = im.size
        margin_x = w * 0.2
        margin_y = h * 0.2
        name = default_element_name()
        if name == "element":
            name = "stub_element"
        return [
            BBox(
                x1=margin_x,
                y1=margin_y,
                x2=w - margin_x,
                y2=h - margin_y,
                element=name,
                score=1.0,
                class_id=0,
            )
        ]


class OpenCvHaarDetector:
    """OpenCV element detector (Haar on OpenCV 4; YuNet on OpenCV 5).

    Historically used for frontal faces; outputs use the generic ``element``
    name (override with ``BBOX_ELEMENT``).

    Backend selection:

    - OpenCV 4.x: ``cv2.CascadeClassifier`` + Haar XML
      (``cv2.data.haarcascades`` or SDK-bundled XML)
    - OpenCV 5.x: ``cv2.FaceDetectorYN`` + SDK-bundled YuNet ONNX
      (Haar was moved out of the main package)

    Env:
      BBOX_ELEMENT — element name written on boxes (default ``element``)
      BBOX_OPENCV_CASCADE — absolute path to a cascade .xml, or a filename
        resolved via cv2.data.haarcascades then SDK ``bbox/data/``
      BBOX_OPENCV_YUNET — absolute path to YuNet .onnx (OpenCV 5 path)
      BBOX_OPENCV_SCALE_FACTOR / BBOX_OPENCV_MIN_NEIGHBORS / BBOX_OPENCV_MIN_SIZE
      (legacy aliases: BBOX_FACE_*; Haar path only)
      BBOX_OPENCV_SCORE_THRESHOLD — YuNet score threshold (default 0.7)
      BBOX_FACE_ATTRS — enable gender/age DNN after face detect (default on);
        graceful degrade when weights missing (see ``face_attrs``)
      BBOX_AGE_ONNX / BBOX_GENDER_ONNX — OpenCV 5+ Levi GoogleNet ``.onnx`` paths
      BBOX_AGE_MODEL / BBOX_GENDER_MODEL — OpenCV 4 Caffe ``.caffemodel`` paths
      BBOX_FACE_ATTRS_BACKEND — force ``onnx`` or ``caffe`` (default auto)
      BBOX_FACE_ATTRS_AUTO_DOWNLOAD — download missing weights on first use (default on)
    """

    name = "opencv"

    def __init__(
        self,
        *,
        cascade_name: str | None = None,
        scale_factor: float | None = None,
        min_neighbors: int | None = None,
        min_size: int | None = None,
        element: str | None = None,
    ) -> None:
        import cv2

        self.element = (element or default_element_name()).strip() or "element"
        self.scale_factor = float(
            scale_factor
            if scale_factor is not None
            else os.getenv(
                "BBOX_OPENCV_SCALE_FACTOR",
                os.getenv("BBOX_FACE_SCALE_FACTOR", "1.1"),
            )
        )
        self.min_neighbors = int(
            min_neighbors
            if min_neighbors is not None
            else os.getenv(
                "BBOX_OPENCV_MIN_NEIGHBORS",
                os.getenv("BBOX_FACE_MIN_NEIGHBORS", "5"),
            )
        )
        self.min_size = int(
            min_size
            if min_size is not None
            else os.getenv(
                "BBOX_OPENCV_MIN_SIZE",
                os.getenv("BBOX_FACE_MIN_SIZE", "30"),
            )
        )
        self.score_threshold = float(os.getenv("BBOX_OPENCV_SCORE_THRESHOLD", "0.7"))
        self._backend = "haar"
        self._cascade = None
        self._yunet = None
        self.cascade_path: Path | None = None
        self.yunet_path: Path | None = None

        if hasattr(cv2, "CascadeClassifier"):
            cascade_path = resolve_haar_cascade_path(cascade_name)
            self._cascade = cv2.CascadeClassifier(str(cascade_path))
            if self._cascade.empty():
                raise RuntimeError(f"failed to load Haar cascade: {cascade_path}")
            self.cascade_path = cascade_path
            self._backend = "haar"
            return

        if hasattr(cv2, "FaceDetectorYN_create") or hasattr(cv2, "FaceDetectorYN"):
            yunet_path = resolve_yunet_model_path()
            create = getattr(cv2, "FaceDetectorYN_create", None)
            if create is None:
                create = cv2.FaceDetectorYN.create
            # input_size is updated per-image in detect()
            self._yunet = create(str(yunet_path), "", (320, 320), self.score_threshold)
            self.yunet_path = yunet_path
            self._backend = "yunet"
            logger.info(
                "OpenCV %s has no CascadeClassifier; using FaceDetectorYN (%s)",
                getattr(cv2, "__version__", "?"),
                yunet_path,
            )
            return

        raise RuntimeError(
            "OpenCV build has neither CascadeClassifier nor FaceDetectorYN.\n"
            "Fix options:\n"
            "  - pip install 'opencv-python-headless>=4.8,<5' (Haar), or\n"
            "  - pip install opencv-python-headless>=5 (YuNet FaceDetectorYN), or\n"
            "  - use BBOX_DETECTOR=stub for local HMI smoke without real detection"
        )

    def detect(self, image_path: str | Path) -> list[BBox]:
        import cv2

        path = Path(image_path)
        img = cv2.imread(str(path))
        if img is None:
            logger.warning("OpenCvHaarDetector: cannot read %s", path)
            return []

        if self._backend == "yunet":
            boxes = self._detect_yunet(cv2, img)
        else:
            boxes = self._detect_haar(cv2, img)
        return self._maybe_enrich_face_attrs(img, boxes)

    _face_attrs_missing_logged = False

    def _maybe_enrich_face_attrs(self, img: object, boxes: list[BBox]) -> list[BBox]:
        """Attach gender/age when ``BBOX_FACE_ATTRS`` is on and models load."""
        if not boxes:
            return boxes
        try:
            from .face_attrs import enrich_face_boxes, face_attrs_enabled, get_face_attr_estimator

            if not face_attrs_enabled():
                return boxes
            if get_face_attr_estimator() is None:
                if not OpenCvHaarDetector._face_attrs_missing_logged:
                    OpenCvHaarDetector._face_attrs_missing_logged = True
                    logger.info(
                        "BBOX_FACE_ATTRS on but age/gender estimator unavailable; "
                        "writing face boxes without gender/age (see face_attrs logs)"
                    )
            return enrich_face_boxes(img, boxes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("face attrs skipped: %s", exc)
            return boxes

    def _detect_haar(self, cv2: object, img: object) -> list[BBox]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  # type: ignore[attr-defined]
        hits = self._cascade.detectMultiScale(  # type: ignore[union-attr]
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=(self.min_size, self.min_size),
        )
        boxes: list[BBox] = []
        for x, y, w, h in hits:
            boxes.append(
                BBox(
                    x1=float(x),
                    y1=float(y),
                    x2=float(x + w),
                    y2=float(y + h),
                    element=self.element,
                    score=None,
                    class_id=0,
                )
            )
        return boxes

    def _detect_yunet(self, cv2: object, img: object) -> list[BBox]:
        h, w = img.shape[:2]  # type: ignore[attr-defined]
        self._yunet.setInputSize((w, h))  # type: ignore[union-attr]
        _retval, faces = self._yunet.detect(img)  # type: ignore[union-attr]
        boxes: list[BBox] = []
        if faces is None:
            return boxes
        for row in faces:
            x, y, bw, bh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            # FaceDetectorYN layout: xywh + 5 landmarks (10) + score → score at index 14.
            # Older builds may put score at index 4; only accept values in [0, 1].
            score: float | None = None
            for idx in (14, 4):
                if len(row) <= idx:
                    continue
                try:
                    cand = float(row[idx])
                except (TypeError, ValueError):
                    continue
                if 0.0 <= cand <= 1.0:
                    score = cand
                    break
            boxes.append(
                BBox(
                    x1=x,
                    y1=y,
                    x2=x + bw,
                    y2=y + bh,
                    element=self.element,
                    score=score,
                    class_id=0,
                )
            )
        return boxes


# Backward-compatible alias
OpenCvFaceDetector = OpenCvHaarDetector


def yolo_available() -> bool:
    """True when optional ``ultralytics`` (``oms-multimodal-sdk[bbox]``) is importable."""
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return False
    return True


def require_yolo_extra() -> None:
    """Raise a clear RuntimeError if YOLO deps are missing."""
    if yolo_available():
        return
    raise RuntimeError(
        "BBOX_DETECTOR=yolo requires ultralytics. "
        'Install with: pip install "oms-multimodal-sdk[bbox]" '
        '(HMI local: pip install -r hmi/requirements-dev.txt which includes [bbox]). '
        "Or switch detector to stub/opencv/noop in pipeline settings."
    )


class YoloDetector:
    """Ultralytics YOLO detector (optional dependency).

    Predicted class names are stored as ``element`` (e.g. person, car).

    Env:
      BBOX_YOLO_MODEL — weights name/path (default yolov8n.pt)
      BBOX_YOLO_CONF — confidence threshold (default 0.25)
      BBOX_YOLO_CLASSES — comma-separated class **ids or names** to keep
        (empty = all). Names are matched case-insensitively against the
        loaded model vocabulary (COCO for yolov8n).
    """

    name = "yolo"

    def __init__(
        self,
        *,
        model: str | None = None,
        conf: float | None = None,
        class_ids: list[int] | None = None,
        class_filter: str | None = None,
    ) -> None:
        require_yolo_extra()
        from ultralytics import YOLO
        self._model_name = model or os.getenv("BBOX_YOLO_MODEL", "yolov8n.pt")
        self.conf = float(conf if conf is not None else os.getenv("BBOX_YOLO_CONF", "0.25"))
        self._model = YOLO(self._model_name)
        if class_ids is not None:
            self.class_ids = list(class_ids)
        else:
            raw = (
                class_filter
                if class_filter is not None
                else os.getenv("BBOX_YOLO_CLASSES", "")
            ).strip()
            self.class_ids = resolve_yolo_class_ids(raw, self._model.names or {})

    def detect(self, image_path: str | Path) -> list[BBox]:
        results = self._model.predict(
            source=str(image_path),
            conf=self.conf,
            verbose=False,
        )
        if not results:
            return []
        result = results[0]
        names = result.names or {}
        boxes: list[BBox] = []
        if result.boxes is None:
            return boxes
        for box in result.boxes:
            cls_id = int(box.cls.item()) if box.cls is not None else 0
            if self.class_ids and cls_id not in self.class_ids:
                continue
            xyxy = box.xyxy[0].tolist()
            score = float(box.conf.item()) if box.conf is not None else None
            element = str(names.get(cls_id, cls_id))
            boxes.append(
                BBox(
                    x1=float(xyxy[0]),
                    y1=float(xyxy[1]),
                    x2=float(xyxy[2]),
                    y2=float(xyxy[3]),
                    element=element,
                    score=score,
                    class_id=cls_id,
                )
            )
        return boxes


# COCO-80 names for yolov8n / common Ultralytics defaults (id order).
COCO80_CLASS_NAMES: tuple[str, ...] = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)


def list_yolo_class_catalog() -> list[dict[str, Any]]:
    """UI catalog: COCO-80 id + name (for yolov8n defaults)."""
    return [{"id": i, "name": name} for i, name in enumerate(COCO80_CLASS_NAMES)]


# Cabin leftover items that exist in standard YOLOv8n COCO-80.
# Note: COCO has no ``face`` class — use BBOX_DETECTOR=opencv for faces.
CABIN_LEFTOVER_COCO_NAMES: tuple[str, ...] = (
    "backpack",  # 24
    "umbrella",  # 25
    "handbag",  # 26
    "suitcase",  # 28
    "bottle",  # 39
    "cup",  # 41
    "laptop",  # 63
    "mouse",  # 64
    "remote",  # 65
    "keyboard",  # 66
    "cell phone",  # 67
    "book",  # 73
)


def list_yolo_class_presets() -> list[dict[str, Any]]:
    """Checklist UI presets (COCO names only; no fake face class).

    ``mode``:
      - ``add`` — merge into current selection
      - ``replace`` — set selection to these classes only
    """
    return [
        {
            "id": "person",
            "label": "人物",
            "mode": "add",
            "names": ["person"],
        },
        {
            "id": "vehicle",
            "label": "车辆",
            "mode": "add",
            "names": ["car", "bus", "truck", "motorcycle", "bicycle"],
        },
        {
            "id": "cabin_leftover",
            "label": "舱内遗留物",
            "mode": "replace",
            "names": list(CABIN_LEFTOVER_COCO_NAMES),
            "hint": "标准 YOLOv8n/COCO 无 face；人脸请改用检测器 OpenCV（Haar/YuNet）",
        },
    ]


def resolve_yolo_class_ids(
    raw: str,
    model_names: dict[Any, Any] | None = None,
) -> list[int]:
    """Parse ``BBOX_YOLO_CLASSES`` as comma-separated ids and/or class names.

    Empty / whitespace → keep all classes (return empty list as "no filter").
    """
    text = (raw or "").strip()
    if not text:
        return []
    name_to_id: dict[str, int] = {}
    if isinstance(model_names, dict) and model_names:
        for k, v in model_names.items():
            try:
                name_to_id[str(v).strip().lower()] = int(k)
            except (TypeError, ValueError):
                continue
    else:
        name_to_id = {n.lower(): i for i, n in enumerate(COCO80_CLASS_NAMES)}

    out: list[int] = []
    seen: set[int] = set()
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        cls_id: int | None = None
        if token.isdigit() or (token.startswith("-") and token[1:].isdigit()):
            cls_id = int(token)
        else:
            cls_id = name_to_id.get(token.lower())
        if cls_id is None or cls_id in seen:
            continue
        seen.add(cls_id)
        out.append(cls_id)
    return out


DetectorFactory = Callable[[], BBoxDetector]

_DETECTOR_ALIASES: dict[str, str] = {
    "noop": "noop",
    "none": "noop",
    "off": "noop",
    "stub": "stub",
    "fake": "stub",
    # OpenCV Haar backend (not domain-bound; element name via BBOX_ELEMENT)
    "opencv": "opencv",
    "haar": "opencv",
    "opencv_haar": "opencv",
    "face": "opencv",  # legacy alias
    "opencv_face": "opencv",
    "yolo": "yolo",
    "ultralytics": "yolo",
}

_DETECTOR_FACTORIES: dict[str, DetectorFactory] = {
    "noop": NoOpDetector,
    "stub": StubDetector,
    "opencv": OpenCvHaarDetector,
    "yolo": YoloDetector,
}


def list_detectors() -> list[dict[str, str]]:
    """Public catalog for CLI / docs / HMI later."""
    yolo_ready = yolo_available()
    yolo_desc = (
        "Ultralytics YOLO; class names → element"
        if yolo_ready
        else "Ultralytics YOLO (unavailable — pip install oms-multimodal-sdk[bbox])"
    )
    return [
        {"id": "noop", "aliases": "noop,none,off", "desc": "No detection (default)"},
        {"id": "stub", "aliases": "stub,fake", "desc": "Centered fake element box for smoke tests"},
        {
            "id": "opencv",
            "aliases": "opencv,haar,face,opencv_face",
            "desc": (
                "OpenCV face detector (Haar on cv2<5; YuNet FaceDetectorYN on cv2>=5); "
                "cabin 人脸推荐；可选性别/年龄 (BBOX_FACE_ATTRS)；element from BBOX_ELEMENT"
            ),
        },
        {
            "id": "yolo",
            "aliases": "yolo,ultralytics",
            "desc": (
                f"{yolo_desc}; COCO multi-class（无 face）；舱内遗留物见类别清单预设"
            ),
            "available": "1" if yolo_ready else "0",
        },
    ]


def resolve_detector(name: str | None = None) -> BBoxDetector:
    raw = (name or os.getenv("BBOX_DETECTOR", "noop")).strip().lower()
    key = _DETECTOR_ALIASES.get(raw, raw)
    factory = _DETECTOR_FACTORIES.get(key)
    if factory is None:
        known = ", ".join(sorted(_DETECTOR_FACTORIES))
        raise ValueError(f"unknown BBOX_DETECTOR={raw!r}; choose from: {known}")
    return factory()
