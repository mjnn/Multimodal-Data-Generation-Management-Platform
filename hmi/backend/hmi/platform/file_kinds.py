"""Source kinds are lake file suffixes (.bag, .mp4, .wav), not generic video/audio."""

from __future__ import annotations

from pathlib import Path

VIDEO_EXTS = frozenset({".mp4", ".webm", ".mov", ".mkv", ".avi"})
AUDIO_EXTS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".dat"})
TEXT_EXTS = frozenset({".txt", ".json", ".md", ".csv"})
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
BAG_EXTS = frozenset({".bag"})

SOURCE_KINDS = VIDEO_EXTS | AUDIO_EXTS | TEXT_EXTS | IMAGE_EXTS | BAG_EXTS

LEGACY_KIND_ALIASES = {
    "rosbag": ".bag",
    "bag": ".bag",
    "video": ".mp4",
    "audio": ".wav",
    "image": ".jpg",
    "text": ".txt",
}

PARSE_BAG_MODALITIES = ("frames", ".wav", ".json")
PARSE_BAG_MODALITY_ALIASES = {
    "video": "frames",
    ".mp4": "frames",
    "mp4": "frames",
    "audio": ".wav",
    "text": ".json",
    **{m: m for m in PARSE_BAG_MODALITIES},
}


def normalize_source_kind(raw: str | None) -> str | None:
    k = str(raw or "").strip().lower()
    if not k:
        return None
    if k in LEGACY_KIND_ALIASES:
        return LEGACY_KIND_ALIASES[k]
    if not k.startswith("."):
        k = f".{k}"
    return k if k in SOURCE_KINDS else None


def kind_from_filename(filename: str | None) -> str | None:
    name = Path(str(filename or "").replace("\\", "/")).name.lower()
    suffix = Path(name).suffix
    return suffix if suffix in SOURCE_KINDS else None


def resolve_source_kind(*, kind: str | None = None, filename: str | None = None) -> str | None:
    """Prefer the uploaded filename suffix; fall back to a declared/legacy kind."""
    from_name = kind_from_filename(filename)
    if from_name:
        return from_name
    return normalize_source_kind(kind)


def modality_of(kind: str | None) -> str | None:
    k = normalize_source_kind(kind) or str(kind or "").strip().lower()
    if k in BAG_EXTS or k in {"rosbag", "bag"}:
        return "rosbag"
    if k in VIDEO_EXTS or k == "video":
        return "video"
    if k in AUDIO_EXTS or k == "audio":
        return "audio"
    if k in TEXT_EXTS or k == "text":
        return "text"
    if k in IMAGE_EXTS or k == "image":
        return "image"
    return None


def normalize_parse_bag_modality(raw: str | None) -> str | None:
    k = str(raw or "").strip().lower()
    if not k:
        return None
    if k in PARSE_BAG_MODALITY_ALIASES:
        return PARSE_BAG_MODALITY_ALIASES[k]
    if k in PARSE_BAG_MODALITIES:
        return k
    if not k.startswith("."):
        k = f".{k}"
    return k if k in PARSE_BAG_MODALITIES else None


def singleton_kind_groups(*exts: str) -> list[list[str]]:
    return [[e] for e in exts if e]


def list_source_kinds() -> list[str]:
    return sorted(SOURCE_KINDS)
