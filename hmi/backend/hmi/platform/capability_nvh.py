"""Local NVH plugins: HEAD parse + spectrum products (wav or .dat)."""

from __future__ import annotations

import json
import shutil
import wave
from pathlib import Path
from typing import Any

import numpy as np

LOCAL_NVH_OPS = frozenset(
    {
        "parse_head_dat",
        "stft_spectrogram",
        "mel_spectrogram",
        "third_octave",
        "spl_timeline",
    }
)

_PCM_WAV_EXTS = frozenset({".wav"})
_COMPRESSED_AUDIO_EXTS = frozenset({".mp3", ".m4a", ".flac", ".ogg", ".aac"})


def _run_dir(ctx: dict[str, Any]) -> Path:
    raw = str(ctx.get("run_dir") or "").strip()
    if not raw:
        raise RuntimeError("NVH capability 需要 ctx.run_dir")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(ctx: dict[str, Any]) -> Path | None:
    raw = str(ctx.get("source_manifest_path") or "").strip()
    if raw:
        p = Path(raw)
        if p.is_file():
            return p
    run = Path(str(ctx.get("run_dir") or ""))
    candidate = run / "source_manifest.json"
    return candidate if candidate.is_file() else None


def _load_manifest(ctx: dict[str, Any]) -> dict[str, Any]:
    path = _manifest_path(ctx)
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_dir(ctx: dict[str, Any]) -> Path | None:
    man = _manifest_path(ctx)
    return man.parent if man is not None else None


def _load_pcm_from_paths(pcm_file: Path, meta_file: Path) -> dict[str, Any]:
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    pcm_pa = np.load(pcm_file)
    fs = float(meta["fs_hz"])
    ch_names = [str(c.get("name") or f"ch{i+1}") for i, c in enumerate(meta.get("channels") or [])]
    return {
        "pcm_pa": pcm_pa,
        "fs": fs,
        "ch_names": ch_names,
        "meta_path": meta_file,
        "meta": meta,
    }


def _resolve_audio_file(ctx: dict[str, Any], man: dict[str, Any]) -> Path | None:
    """Resolve lake-relative audio names (audio.wav) against the manifest directory."""
    man_path = _manifest_path(ctx)
    base = man_path.parent if man_path is not None else _run_dir(ctx)
    rel = str(man.get("audio") or man.get("audio_path") or "").strip()
    candidates: list[Path] = []
    if rel:
        raw = Path(rel)
        candidates.append(raw)
        if not raw.is_absolute():
            candidates.append(base / rel)
            candidates.append(base / raw.name)
    for name in ("audio.wav", "source.wav", "source.dat", "audio.dat"):
        candidates.append(base / name)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _pcm_from_wav_frames(raw: bytes, sampwidth: int) -> np.ndarray:
    if sampwidth == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    if sampwidth == 2:
        return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if sampwidth == 3:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (
            packed[:, 0].astype(np.int32)
            | (packed[:, 1].astype(np.int32) << 8)
            | (packed[:, 2].astype(np.int32) << 16)
        )
        ints = np.where(ints >= (1 << 23), ints - (1 << 24), ints)
        return ints.astype(np.float64) / 8388608.0
    if sampwidth == 4:
        return np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    raise RuntimeError(f"不支持的 wav 采样位宽 {sampwidth}")


def _load_wav_pcm(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as handle:
        n_ch = handle.getnchannels()
        sampwidth = handle.getsampwidth()
        fs = float(handle.getframerate())
        n_frames = handle.getnframes()
        raw = handle.readframes(n_frames)
        comptype = str(handle.getcomptype() or "NONE").upper()
    if comptype not in {"NONE", "UNKNOWN"}:
        raise RuntimeError(f"不支持压缩 wav（{comptype}）：{path.name}，请转成 PCM .wav")
    pcm = _pcm_from_wav_frames(raw, sampwidth)
    if n_ch < 1:
        raise RuntimeError(f"wav 声道数无效：{path.name}")
    if pcm.size % n_ch != 0:
        raise RuntimeError(f"wav PCM 长度与声道数不匹配：{path.name}")
    pcm = pcm.reshape(-1, n_ch).astype(np.float32)
    ch_names = [f"ch{i + 1}" for i in range(n_ch)]
    return {
        "pcm_pa": pcm,
        "fs": fs,
        "ch_names": ch_names,
        "meta_path": None,
        "meta": {
            "format": "pcm_wav",
            "source_file": path.name,
            "fs_hz": fs,
            "duration_s": float(pcm.shape[0] / fs) if fs else 0.0,
            "n_channels": int(n_ch),
            "unit": "normalized_fs",
            "channels": [{"name": n, "map_factor": 1.0} for n in ch_names],
        },
    }


def _bundle_from_head_dat(dat_path: Path) -> dict[str, Any]:
    from hmi.local.head_dat import parse_head_dat_bytes

    parsed = parse_head_dat_bytes(dat_path.read_bytes())
    ch_names = [str(c.get("name") or f"ch{i+1}") for c in parsed["channels"]]
    return {
        "pcm_pa": parsed["pcm_pa"],
        "fs": float(parsed["fs_hz"]),
        "ch_names": ch_names,
        "meta_path": None,
        "meta": {
            "format": "head_acoustics_hdf_v4",
            "fs_hz": float(parsed["fs_hz"]),
            "duration_s": float(parsed["pcm_pa"].shape[0] / float(parsed["fs_hz"])),
            "n_channels": int(parsed["pcm_pa"].shape[1]),
            "unit": "Pa",
            "channels": [{"name": n, "map_factor": 1.0} for n in ch_names],
        },
    }


def load_array_pcm(ctx: dict[str, Any], *, require_head: bool = False) -> dict[str, Any]:
    """Load PCM for spectrum: HEAD .dat, pcm_pa.npy, or (unless require_head) PCM .wav."""
    man = _load_manifest(ctx)
    man_path = _manifest_path(ctx)
    base = man_path.parent if man_path is not None else _run_dir(ctx)
    pcm_path = base / "pcm_pa.npy"
    meta_path = base / "head_meta.json"
    if pcm_path.is_file() and meta_path.is_file():
        return _load_pcm_from_paths(pcm_path, meta_path)

    audio_path = _resolve_audio_file(ctx, man)
    if audio_path is not None:
        src_pcm = audio_path.parent / "pcm_pa.npy"
        src_meta = audio_path.parent / "head_meta.json"
        if src_pcm.is_file() and src_meta.is_file():
            return _load_pcm_from_paths(src_pcm, src_meta)

    suffix = audio_path.suffix.lower() if audio_path is not None else ""
    if audio_path is not None and suffix in _PCM_WAV_EXTS and not require_head:
        return _load_wav_pcm(audio_path)
    if audio_path is not None and suffix == ".dat":
        return _bundle_from_head_dat(audio_path)
    if audio_path is not None and suffix in _COMPRESSED_AUDIO_EXTS:
        raise RuntimeError(
            f"梅尔频谱 / SPL 暂不解码 {suffix}，请先转成 PCM .wav 再入库（当前 {audio_path.name}）"
        )
    if require_head:
        raise RuntimeError(
            "parse_head_dat 需要 HEAD 麦克风阵列 .dat（或同目录 pcm_pa.npy + head_meta.json）；"
            f"当前源为 {audio_path.name if audio_path else '缺失'}"
        )
    raise RuntimeError(
        "梅尔频谱 / SPL 需要 PCM .wav 或 HEAD .dat（或同目录 pcm_pa.npy + head_meta.json）；"
        f"当前源为 {audio_path.name if audio_path else '缺失'}"
    )


def _persist_pcm(run_dir: Path, bundle: dict[str, Any]) -> None:
    pcm_pa = bundle["pcm_pa"]
    fs = float(bundle["fs"])
    ch_names = list(bundle["ch_names"])
    np.save(run_dir / "pcm_pa.npy", pcm_pa)
    meta_src = bundle.get("meta_path")
    if meta_src is not None and Path(meta_src).is_file():
        shutil.copy2(meta_src, run_dir / "head_meta.json")
    else:
        (run_dir / "head_meta.json").write_text(
            json.dumps(bundle.get("meta") or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    _ = (fs, ch_names)


def _record_product(ctx: dict[str, Any], op_id: str, rel: str) -> None:
    if not ctx.get("record_lineage"):
        return
    try:
        from hmi.platform.store import lookup_or_record_product
    except Exception:
        return
    man = _load_manifest(ctx)
    audio_sid = str((man.get("sources_by_kind") or {}).get("audio") or "").strip()
    input_ids = [audio_sid] if audio_sid else [
        str(x).strip() for x in (man.get("source_ids") or []) if str(x).strip()
    ]
    if not input_ids:
        cid = str(ctx.get("clip_id") or "").strip()
        input_ids = [cid] if cid else ["unknown"]
    run_dir = _run_dir(ctx)
    art = run_dir / rel
    try:
        lookup_or_record_product(
            input_ids=input_ids,
            op_id=op_id,
            params={"data_type_id": "audio_array_spec"},
            artifact_path=str(art) if art.exists() or art.is_dir() else rel,
            run_id=str(ctx.get("run_id") or "") or None,
        )
    except Exception:
        return


def _ensure_spectrum(ctx: dict[str, Any]) -> dict[str, Any]:
    from hmi.local.audio_spectrum import analyze_pcm_pa

    cached = ctx.get("audio_spec")
    if isinstance(cached, dict) and cached.get("ok"):
        return cached
    run_dir = _run_dir(ctx)
    pcm_path = run_dir / "pcm_pa.npy"
    meta_path = run_dir / "head_meta.json"
    if not pcm_path.is_file() or not meta_path.is_file():
        bundle = load_array_pcm(ctx)
        _persist_pcm(run_dir, bundle)
    else:
        bundle = _load_pcm_from_paths(pcm_path, meta_path)
    spec_dir = run_dir / "audio_spec"
    summary = analyze_pcm_pa(bundle["pcm_pa"], float(bundle["fs"]), list(bundle["ch_names"]), spec_dir)
    (run_dir / "audio_spec_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    patch = {"audio_spec": {"ok": True, "summary": summary, "path": str(spec_dir)}}
    ctx.update(patch)
    return patch["audio_spec"]


def adapt_parse_head_dat(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(ctx)
    bundle = load_array_pcm(ctx, require_head=True)
    _persist_pcm(run_dir, bundle)
    _record_product(ctx, "parse_head_dat", "pcm_pa.npy")
    return {
        "pcm_pa_wavs": {
            "path": str(run_dir / "pcm_pa.npy"),
            "fs_hz": float(bundle["fs"]),
            "n_channels": int(np.asarray(bundle["pcm_pa"]).shape[1]),
            "channels": list(bundle["ch_names"]),
        }
    }


def adapt_stft_spectrogram(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    spec = _ensure_spectrum(ctx)
    _record_product(ctx, "stft_spectrogram", "audio_spec")
    return {"stft_matrix": {"path": spec["path"]}}


def adapt_mel_spectrogram(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    spec = _ensure_spectrum(ctx)
    _record_product(ctx, "mel_spectrogram", "audio_spec")
    return {"mel_matrix": {"path": spec["path"]}}


def adapt_third_octave(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    spec = _ensure_spectrum(ctx)
    _record_product(ctx, "third_octave", "audio_spec")
    return {"third_octave_json": {"path": spec["path"]}}


def adapt_spl_timeline(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    from hmi.local.nvh_deriver import derive_nvh_labels, persist_nvh_labels_artifact

    spec = _ensure_spectrum(ctx)
    _record_product(ctx, "spl_timeline", "audio_spec")
    run_dir = _run_dir(ctx)
    labels = derive_nvh_labels(run_dir, source_dir=_source_dir(ctx))
    persist_nvh_labels_artifact(run_dir, labels)
    return {
        "spl_jsonl": {"path": spec["path"]},
        "nvh_objective": {"ok": True},
    }


LOCAL_NVH_ADAPTERS: dict[str, Any] = {
    "parse_head_dat": adapt_parse_head_dat,
    "stft_spectrogram": adapt_stft_spectrogram,
    "mel_spectrogram": adapt_mel_spectrogram,
    "third_octave": adapt_third_octave,
    "spl_timeline": adapt_spl_timeline,
}
