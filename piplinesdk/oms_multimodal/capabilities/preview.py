"""Capability: preview — 整理 preview/ 目录（sdk_upload 前）。"""
from __future__ import annotations

import shutil
from pathlib import Path

from .types import RunContext


def materialize_preview(ctx: RunContext) -> Path:
    """将 _sdk_work 下 clip_preview_*.mp4、audio.wav 拷到 run_dir/preview/。

    extract 把产物写在 ``work_dir/<bag_stem>/clips/``（见 RosbagExtractor），
    因此需同时兼容 ``work_dir/clips`` 与 ``work_dir/*/clips``。
    """
    preview_dir = ctx.run_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    work = ctx.work_dir
    if not work.is_dir():
        return preview_dir

    clips_roots: list[Path] = []
    direct = work / "clips"
    if direct.is_dir():
        clips_roots.append(direct)
    for child in work.iterdir():
        nested = child / "clips"
        if nested.is_dir() and nested not in clips_roots:
            clips_roots.append(nested)

    for clips_root in clips_roots:
        for clip_dir in clips_root.iterdir():
            if not clip_dir.is_dir():
                continue
            for mp4 in clip_dir.glob("clip_preview_*.mp4"):
                shutil.copy2(mp4, preview_dir / mp4.name)
            wav = clip_dir / "audio.wav"
            if wav.is_file():
                shutil.copy2(wav, preview_dir / "audio.wav")
            return preview_dir
    return preview_dir
