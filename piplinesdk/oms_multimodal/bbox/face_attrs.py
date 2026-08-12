"""OpenCV DNN age/gender attributes for face boxes (local SDK).

Backends (auto-selected):

1. **ONNX** (preferred on OpenCV 5+): Levi GoogleNet
   ``age_googlenet.onnx`` / ``gender_googlenet.onnx`` via ``cv2.dnn.readNetFromONNX``.
   OpenCV 5 removed Caffe importers (``readNetFromCaffe`` / Caffe ``readNet``).
2. **Caffe** (OpenCV 4.x): Gil Levi / learnopencv
   ``age_net.caffemodel`` + ``age_deploy.prototxt`` (and gender pair).

Weights (~24MB ONNX / ~45MB Caffe each) download on first use into ``bbox/data/``
when ``BBOX_FACE_ATTRS_AUTO_DOWNLOAD=1`` (default).

Env:

- ``BBOX_FACE_ATTRS`` — ``1``/``0`` (default on). When off, skip attrs.
- ``BBOX_AGE_ONNX`` / ``BBOX_GENDER_ONNX`` — override ONNX model paths
- ``BBOX_AGE_PROTO`` / ``BBOX_AGE_MODEL`` — Caffe prototxt / caffemodel
- ``BBOX_GENDER_PROTO`` / ``BBOX_GENDER_MODEL`` — same for gender
- ``BBOX_FACE_ATTRS_AUTO_DOWNLOAD`` — ``1``/``0`` (default on)
- ``BBOX_FACE_ATTRS_BACKEND`` — force ``onnx`` / ``caffe`` (default: auto)

Missing weights → graceful degrade (faces still detected, no gender/age).
"""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PKG_DATA_DIR = Path(__file__).resolve().parent / "data"

# Gil Levi AgeGenderDeepLearning buckets (learnopencv AgeGender / onnx models)
AGE_BUCKETS: tuple[str, ...] = (
    "0-2",
    "4-6",
    "8-12",
    "15-20",
    "25-32",
    "38-43",
    "48-53",
    "60-100",
)
AGE_APPROX: tuple[int, ...] = (1, 5, 10, 17, 28, 40, 50, 80)
GENDER_LABELS: tuple[str, ...] = ("male", "female")

# ONNX Levi GoogleNet (onnx/models age_gender): 224×224, mean 104/117/123, BGR
_ONNX_MEAN = (104.0, 117.0, 123.0)
_ONNX_BLOB_SIZE = (224, 224)

# Caffe Gil Levi AlexNet-style (learnopencv): 227×227
_CAFFE_MEAN = (78.4263377603, 87.7689143744, 114.895847746)
_CAFFE_BLOB_SIZE = (227, 227)

_DEFAULT_AGE_PROTO = "age_deploy.prototxt"
_DEFAULT_GENDER_PROTO = "gender_deploy.prototxt"
_DEFAULT_AGE_MODEL = "age_net.caffemodel"
_DEFAULT_GENDER_MODEL = "gender_net.caffemodel"
_DEFAULT_AGE_ONNX = "age_googlenet.onnx"
_DEFAULT_GENDER_ONNX = "gender_googlenet.onnx"

_AGE_ONNX_URLS: tuple[str, ...] = (
    "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx",
    "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx",
)
_GENDER_ONNX_URLS: tuple[str, ...] = (
    "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx",
    "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx",
)

# Official learnopencv Dropbox mirrors (+ dl=1); secondary GitHub raw mirrors.
_AGE_MODEL_URLS: tuple[str, ...] = (
    "https://www.dropbox.com/s/xfb20y596869vbb/age_net.caffemodel?dl=1",
    "https://github.com/smahesh29/Gender-and-Age-Detection/raw/master/age_net.caffemodel",
)
_GENDER_MODEL_URLS: tuple[str, ...] = (
    "https://www.dropbox.com/s/iyv483wz7ztr9gh/gender_net.caffemodel?dl=1",
    "https://github.com/smahesh29/Gender-and-Age-Detection/raw/master/gender_net.caffemodel",
)

# Module-level singleton (lazy); reset in tests via ``reset_face_attr_estimator``.
_estimator: FaceAttrEstimator | None = None
_estimator_failed = False


def face_attrs_enabled() -> bool:
    """True when ``BBOX_FACE_ATTRS`` is unset/empty or truthy."""
    raw = os.getenv("BBOX_FACE_ATTRS", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def auto_download_enabled() -> bool:
    raw = os.getenv("BBOX_FACE_ATTRS_AUTO_DOWNLOAD", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def age_approx_from_range(age_range: str | None) -> int | None:
    """Map ``25-32`` → ``28`` (bucket midpoint used in ``~28y`` labels)."""
    if not age_range:
        return None
    key = str(age_range).strip().strip("()")
    try:
        idx = AGE_BUCKETS.index(key)
    except ValueError:
        # Allow "(25-32)" style already stripped partially
        for i, bucket in enumerate(AGE_BUCKETS):
            if key == bucket or key == f"({bucket})":
                idx = i
                break
        else:
            return None
    return AGE_APPROX[idx]


def format_face_attr_label(
    element: str,
    *,
    gender: str | None = None,
    age_range: str | None = None,
    age_approx: int | None = None,
) -> str:
    """Build prompt/draw caption like ``face/female/~28y``.

    Base ``element`` is always first. Gender and age are appended when present.
    """
    base = (element or "element").strip() or "element"
    parts: list[str] = [base]
    g = (gender or "").strip().lower()
    if g in {"male", "female", "m", "f"}:
        parts.append("male" if g in {"male", "m"} else "female")
    approx = age_approx
    if approx is None:
        approx = age_approx_from_range(age_range)
    if approx is not None:
        parts.append(f"~{int(approx)}y")
    elif age_range:
        cleaned = str(age_range).strip().strip("()")
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


def box_prompt_name(box: dict[str, Any]) -> str:
    """Element name for Omni Detected-objects summary (attrs → slash label)."""
    element = str(box.get("element") or box.get("label") or "").strip() or "element"
    gender = box.get("gender")
    age_range = box.get("age_range")
    age_approx = box.get("age_approx")
    if gender or age_range or age_approx is not None:
        try:
            approx_i = int(age_approx) if age_approx is not None else None
        except (TypeError, ValueError):
            approx_i = None
        return format_face_attr_label(
            element,
            gender=str(gender) if gender else None,
            age_range=str(age_range) if age_range else None,
            age_approx=approx_i,
        )
    return element


def _env_path(key: str) -> Path | None:
    raw = os.getenv(key, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def resolve_attr_file(
    *,
    env_key: str,
    default_name: str,
    kind: str,
    required: bool = True,
) -> Path | None:
    """Resolve prototxt/model path: env → package ``bbox/data/``."""
    candidates: list[Path] = []
    env_p = _env_path(env_key)
    if env_p is not None:
        candidates.append(env_p)
    candidates.append(_PKG_DATA_DIR / default_name)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    if required:
        tried = "\n  - ".join(str(p) for p in candidates)
        logger.warning("%s not found (tried:\n  - %s)", kind, tried)
    return None


def _download_file(urls: tuple[str, ...], dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    timeout_sec = float(os.getenv("BBOX_FACE_ATTRS_DOWNLOAD_TIMEOUT", "180"))
    for url in urls:
        try:
            logger.info("Downloading face-attr model from %s → %s", url, dest)
            req = urllib.request.Request(url, headers={"User-Agent": "oms-multimodal-sdk"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
                data = resp.read()
            if len(data) < 1_000_000:
                logger.warning("Download too small (%s bytes) from %s", len(data), url)
                continue
            tmp.write_bytes(data)
            tmp.replace(dest)
            return True
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            logger.warning("Failed to download %s: %s", url, exc)
            if tmp.is_file():
                tmp.unlink(missing_ok=True)
    return False


def ensure_weight_file(dest_name: str, urls: tuple[str, ...], *, env_key: str) -> Path | None:
    """Return existing weight path, optionally downloading into package data."""
    env_p = _env_path(env_key)
    if env_p is not None and env_p.is_file():
        return env_p.resolve()
    dest = _PKG_DATA_DIR / dest_name
    if dest.is_file() and dest.stat().st_size > 1_000_000:
        return dest.resolve()
    if not auto_download_enabled():
        logger.info(
            "Face-attr model %s missing and BBOX_FACE_ATTRS_AUTO_DOWNLOAD=0; skipping attrs",
            dest_name,
        )
        return None
    if _download_file(urls, dest):
        return dest.resolve()
    return None


# Back-compat alias used by older call sites / docs snippets
ensure_caffemodel = ensure_weight_file


def _caffe_importer_available(cv2: Any) -> bool:
    return callable(getattr(cv2.dnn, "readNetFromCaffe", None))


def _forced_backend() -> str | None:
    raw = os.getenv("BBOX_FACE_ATTRS_BACKEND", "").strip().lower()
    if raw in {"onnx", "caffe"}:
        return raw
    return None


class FaceAttrEstimator:
    """Predict gender + age bucket for a BGR face crop."""

    def __init__(
        self,
        age_net: Any,
        gender_net: Any,
        *,
        backend: str,
        blob_size: tuple[int, int],
        model_mean: tuple[float, float, float],
    ) -> None:
        self._age_net = age_net
        self._gender_net = gender_net
        self.backend = backend
        self._blob_size = blob_size
        self._model_mean = model_mean

    def predict_bgr_crop(self, face_bgr: Any) -> dict[str, Any]:
        """Return ``{gender, age_range, age_approx, gender_score, age_score}`` or empty."""
        import cv2
        import numpy as np

        if face_bgr is None:
            return {}
        h, w = face_bgr.shape[:2]
        if h < 8 or w < 8:
            return {}
        blob = cv2.dnn.blobFromImage(
            face_bgr,
            1.0,
            self._blob_size,
            self._model_mean,
            swapRB=False,
        )
        out: dict[str, Any] = {}

        self._gender_net.setInput(blob)
        gender_preds = self._gender_net.forward()
        if gender_preds is not None and len(gender_preds) > 0:
            row = np.asarray(gender_preds[0]).reshape(-1)
            gi = int(row.argmax())
            if 0 <= gi < len(GENDER_LABELS):
                out["gender"] = GENDER_LABELS[gi]
                out["gender_score"] = float(row[gi])

        self._age_net.setInput(blob)
        age_preds = self._age_net.forward()
        if age_preds is not None and len(age_preds) > 0:
            row = np.asarray(age_preds[0]).reshape(-1)
            ai = int(row.argmax())
            if 0 <= ai < len(AGE_BUCKETS):
                out["age_range"] = AGE_BUCKETS[ai]
                out["age_approx"] = AGE_APPROX[ai]
                out["age_score"] = float(row[ai])
        return out


def _try_load_onnx(cv2: Any) -> FaceAttrEstimator | None:
    age_model = ensure_weight_file(
        _DEFAULT_AGE_ONNX,
        _AGE_ONNX_URLS,
        env_key="BBOX_AGE_ONNX",
    )
    gender_model = ensure_weight_file(
        _DEFAULT_GENDER_ONNX,
        _GENDER_ONNX_URLS,
        env_key="BBOX_GENDER_ONNX",
    )
    if age_model is None or gender_model is None:
        logger.warning(
            "Face age/gender ONNX models unavailable under %s "
            "(need %s / %s or set BBOX_AGE_ONNX / BBOX_GENDER_ONNX).",
            _PKG_DATA_DIR,
            _DEFAULT_AGE_ONNX,
            _DEFAULT_GENDER_ONNX,
        )
        return None
    try:
        age_net = cv2.dnn.readNetFromONNX(str(age_model))
        gender_net = cv2.dnn.readNetFromONNX(str(gender_model))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load face-attr ONNX nets: %s", exc)
        return None
    logger.info(
        "Loaded face age/gender DNN via ONNX (age=%s, gender=%s)",
        age_model.name,
        gender_model.name,
    )
    return FaceAttrEstimator(
        age_net,
        gender_net,
        backend="onnx",
        blob_size=_ONNX_BLOB_SIZE,
        model_mean=_ONNX_MEAN,
    )


def _try_load_caffe(cv2: Any) -> FaceAttrEstimator | None:
    if not _caffe_importer_available(cv2):
        logger.info(
            "cv2.dnn.readNetFromCaffe unavailable (OpenCV %s); skip Caffe face-attr backend",
            getattr(cv2, "__version__", "?"),
        )
        return None

    age_proto = resolve_attr_file(
        env_key="BBOX_AGE_PROTO",
        default_name=_DEFAULT_AGE_PROTO,
        kind="age prototxt",
    )
    gender_proto = resolve_attr_file(
        env_key="BBOX_GENDER_PROTO",
        default_name=_DEFAULT_GENDER_PROTO,
        kind="gender prototxt",
    )
    if age_proto is None or gender_proto is None:
        return None

    age_model = ensure_weight_file(
        _DEFAULT_AGE_MODEL,
        _AGE_MODEL_URLS,
        env_key="BBOX_AGE_MODEL",
    )
    gender_model = ensure_weight_file(
        _DEFAULT_GENDER_MODEL,
        _GENDER_MODEL_URLS,
        env_key="BBOX_GENDER_MODEL",
    )
    if age_model is None or gender_model is None:
        logger.warning(
            "Face age/gender caffemodels unavailable; place age_net.caffemodel / "
            "gender_net.caffemodel under %s or set BBOX_AGE_MODEL / BBOX_GENDER_MODEL.",
            _PKG_DATA_DIR,
        )
        return None

    try:
        age_net = cv2.dnn.readNetFromCaffe(str(age_proto), str(age_model))
        gender_net = cv2.dnn.readNetFromCaffe(str(gender_proto), str(gender_model))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load face-attr Caffe nets: %s", exc)
        return None
    logger.info(
        "Loaded face age/gender DNN via Caffe (age=%s, gender=%s)",
        age_model.name,
        gender_model.name,
    )
    return FaceAttrEstimator(
        age_net,
        gender_net,
        backend="caffe",
        blob_size=_CAFFE_BLOB_SIZE,
        model_mean=_CAFFE_MEAN,
    )


def try_load_face_attr_estimator() -> FaceAttrEstimator | None:
    """Load DNN nets when models are available; else None (no raise)."""
    if not face_attrs_enabled():
        return None
    try:
        import cv2
    except ImportError:
        logger.warning("cv2 not available; face attrs disabled")
        return None

    forced = _forced_backend()
    order: list[str]
    if forced == "onnx":
        order = ["onnx"]
    elif forced == "caffe":
        order = ["caffe"]
    elif not _caffe_importer_available(cv2):
        # OpenCV 5+: Caffe gone — ONNX only
        order = ["onnx"]
    else:
        # OpenCV 4: prefer Caffe (existing weights), ONNX fallback
        order = ["caffe", "onnx"]

    for backend in order:
        est = _try_load_onnx(cv2) if backend == "onnx" else _try_load_caffe(cv2)
        if est is not None:
            return est

    logger.warning(
        "Face age/gender nets unavailable; faces will be detected without attrs. "
        "See bbox/data/README.md (ONNX for OpenCV 5+, Caffe for OpenCV 4)."
    )
    return None


def _weight_files_present() -> bool:
    """True when at least one backend's weight pair exists on disk."""
    onnx_ok = (_PKG_DATA_DIR / _DEFAULT_AGE_ONNX).is_file() and (
        _PKG_DATA_DIR / _DEFAULT_GENDER_ONNX
    ).is_file()
    caffe_ok = (_PKG_DATA_DIR / _DEFAULT_AGE_MODEL).is_file() and (
        _PKG_DATA_DIR / _DEFAULT_GENDER_MODEL
    ).is_file()
    if _env_path("BBOX_AGE_ONNX") or _env_path("BBOX_GENDER_ONNX"):
        onnx_ok = True
    if _env_path("BBOX_AGE_MODEL") or _env_path("BBOX_GENDER_MODEL"):
        caffe_ok = True
    return onnx_ok or caffe_ok


def get_face_attr_estimator() -> FaceAttrEstimator | None:
    """Cached estimator; returns None after a failed load until reset.

    If a prior attempt failed because weights were missing, retry when weight
    files later appear (common after first-run download or OpenCV 5 ONNX drop-in).
    """
    global _estimator, _estimator_failed
    if not face_attrs_enabled():
        return None
    if _estimator is not None:
        return _estimator
    if _estimator_failed:
        if not _weight_files_present():
            return None
        _estimator_failed = False
    est = try_load_face_attr_estimator()
    if est is None:
        _estimator_failed = True
        return None
    _estimator = est
    return _estimator


def reset_face_attr_estimator() -> None:
    """Clear singleton (for tests)."""
    global _estimator, _estimator_failed
    _estimator = None
    _estimator_failed = False


def enrich_face_boxes(
    img_bgr: Any,
    boxes: list[Any],
    *,
    estimator: FaceAttrEstimator | None = None,
    pad_ratio: float = 0.3,
) -> list[Any]:
    """In-place enrich ``BBox`` list with gender/age when estimator is available.

    ``boxes`` items must be ``BBox``-like with x1/y1/x2/y2 and optional
    ``gender`` / ``age_range`` / ``age_approx`` attributes.
    """
    est = estimator if estimator is not None else get_face_attr_estimator()
    if est is None or img_bgr is None or not boxes:
        return boxes

    h, w = img_bgr.shape[:2]
    for box in boxes:
        try:
            x1, y1, x2, y2 = float(box.x1), float(box.y1), float(box.x2), float(box.y2)
        except AttributeError:
            continue
        bw = max(1.0, x2 - x1)
        bh = max(1.0, y2 - y1)
        px = bw * pad_ratio
        py = bh * pad_ratio
        xa = max(0, int(x1 - px))
        ya = max(0, int(y1 - py))
        xb = min(w, int(x2 + px))
        yb = min(h, int(y2 + py))
        if xb <= xa or yb <= ya:
            continue
        crop = img_bgr[ya:yb, xa:xb]
        try:
            attrs = est.predict_bgr_crop(crop)
        except Exception as exc:  # noqa: BLE001
            logger.debug("face attr predict failed: %s", exc)
            continue
        if not attrs:
            continue
        if "gender" in attrs:
            box.gender = attrs["gender"]
        if "age_range" in attrs:
            box.age_range = attrs["age_range"]
        if "age_approx" in attrs:
            box.age_approx = int(attrs["age_approx"])
        if "gender_score" in attrs:
            try:
                box.gender_score = float(attrs["gender_score"])
            except (TypeError, ValueError, AttributeError):
                pass
        if "age_score" in attrs:
            try:
                box.age_score = float(attrs["age_score"])
            except (TypeError, ValueError, AttributeError):
                pass
    return boxes
