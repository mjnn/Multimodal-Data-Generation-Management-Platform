"""Draw bounding boxes onto images (Pillow only; no OpenCV required)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .types import BBox


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    candidates = (
        "arial.ttf",
        "Arial.ttf",
        "segoeui.ttf",
        "SegoeUI.ttf",
        "msyh.ttc",
        "msyhbd.ttc",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥10
    except TypeError:
        return ImageFont.load_default()


def _caption_for_box(box: BBox) -> str:
    parts = [box.display_name() or "element"]
    if box.score is not None and 0.0 <= float(box.score) <= 1.0:
        parts.append(f"det {box.score:.2f}")
    if box.gender and box.gender_score is not None and 0.0 <= float(box.gender_score) <= 1.0:
        parts.append(f"g {box.gender_score:.2f}")
    if (box.age_range or box.age_approx is not None) and box.age_score is not None:
        if 0.0 <= float(box.age_score) <= 1.0:
            parts.append(f"a {box.age_score:.2f}")
    return " · ".join(parts)


def draw_bboxes_on_image(
    src_path: str | Path,
    boxes: list[BBox],
    dst_path: str | Path,
    *,
    color: tuple[int, int, int] = (0, 255, 0),
    width: int | None = None,
) -> str:
    """Copy ``src_path`` to ``dst_path`` with boxes drawn. Returns resolved dst path."""
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        draw = ImageDraw.Draw(rgb)
        w, h = rgb.size
        # Scale line/font with frame size so captions stay readable after 1080p encode.
        line_w = width if width is not None else max(3, min(w, h) // 180)
        font_size = max(18, min(w, h) // 28)
        font = _load_font(font_size)
        for box in boxes:
            xy = [box.x1, box.y1, box.x2, box.y2]
            draw.rectangle(xy, outline=color, width=line_w)
            caption = _caption_for_box(box)
            if not caption:
                continue
            try:
                bbox = draw.textbbox((0, 0), caption, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            except Exception:  # noqa: BLE001
                tw, th = len(caption) * font_size // 2, font_size
            pad = max(2, font_size // 8)
            tx = max(0, min(int(box.x1), w - tw - 2 * pad))
            ty = int(box.y1) - th - 2 * pad
            if ty < 0:
                ty = min(h - th - 2 * pad, int(box.y1) + line_w)
            bg = [tx, ty, tx + tw + 2 * pad, ty + th + 2 * pad]
            draw.rectangle(bg, fill=(0, 0, 0))
            draw.text((tx + pad, ty + pad), caption, fill=color, font=font)
        rgb.save(dst, format="JPEG", quality=95)
    return str(dst.resolve())
