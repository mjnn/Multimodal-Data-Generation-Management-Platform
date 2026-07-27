"""Encode clip frame images for fast browser preview (progressive JPEG)."""

from __future__ import annotations

from pathlib import Path

WEB_FRAME_MAX_WIDTH = 1280
WEB_FRAME_JPEG_QUALITY = 85


def encode_frame_image(path: Path, *, max_width: int = WEB_FRAME_MAX_WIDTH, quality: int = WEB_FRAME_JPEG_QUALITY) -> Path | None:
    """Re-encode image in place as optimized RGB JPEG. Returns final path if updated."""
    path = Path(path)
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return None
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for frame encoding; pip install Pillow") from exc

    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w > max_width:
            new_h = max(1, int(h * max_width / w))
            im = im.resize((max_width, new_h), Image.Resampling.LANCZOS)
        out_path = path.with_suffix(".jpg") if suffix not in {".jpg", ".jpeg"} else path
        im.save(
            out_path,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        if out_path != path and path.is_file():
            path.unlink(missing_ok=True)
    return out_path


def encode_frames_under(directory: Path, *, pattern: str = "*") -> int:
    """Encode all matching images under directory; returns count updated."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    count = 0
    for path in sorted(directory.rglob(pattern)):
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            if encode_frame_image(path) is not None:
                count += 1
    return count
