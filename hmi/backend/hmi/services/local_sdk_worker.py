"""本地轮询 rosbags/ 队列并写入 runtime 产物。

仅 data_source=local 时启用。有 recipe.graph 时走 capability kernel（舱内 SDK 单步 + 阵列本地 NVH 插件）。
无 graph 的舱内配方仍 plan_and_run；无 graph 的 audio_array_spec 仍走专用路径。

完成后镜像到本地 oss/clips/ 并更新 pipeline/dispatch/latest.json。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_OSS_ROOT, LOCAL_ROOT, REPO_ROOT, is_local_mode
from hmi.db import cache_clear
from hmi.local import bag_upload, pipeline_run as pr, store
from hmi.local.bag_upload import resolve_local_bag_path
from hmi.platform.file_kinds import modality_of

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_active_jobs = 0
_status: dict[str, Any] = {
    "enabled": False,
    "interval_sec": 20,
    "running_job": False,
    "last_error": None,
    "last_clip_id": None,
    "last_run_id": None,
    "last_finished_at": None,
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(5, int(raw))
    except ValueError:
        return default


def is_poll_enabled() -> bool:
    if not is_local_mode():
        return False
    return _env_bool("HMI_LOCAL_SDK_POLL_ENABLED", True)


def get_worker_status() -> dict[str, Any]:
    out = dict(_status)
    out["enabled"] = is_poll_enabled()
    out["thread_alive"] = bool(_thread and _thread.is_alive())
    out["running_job"] = _active_jobs > 0
    out["active_jobs"] = _active_jobs
    out["max_parallel"] = _max_parallel()
    return out


def ensure_poller_running() -> dict[str, Any]:
    """Start poller when local+enabled but thread missing (e.g. mode switch without restart)."""
    if is_poll_enabled():
        start_poller()
    else:
        stop_poller()
    return get_worker_status()


def _max_parallel() -> int:
    from hmi.local.pipeline_settings import resolve_sdk_parallel

    return resolve_sdk_parallel()


def _taxonomy_path() -> Path:
    from hmi.local.pipeline_settings import resolve_taxonomy_path

    return resolve_taxonomy_path()


def _clip_config_from_settings() -> "ClipConfig":
    from oms_multimodal.config import ClipConfig

    from hmi.local.pipeline_settings import get_pipeline_settings

    s = get_pipeline_settings()
    return ClipConfig(
        min_sec=float(s.get("min_sec") or 5.0),
        max_sec=float(s.get("max_sec") or 30.0),
        sample_fps=float(s.get("sample_fps") or 1.0),
        max_clips=int(s.get("max_clips") or 1),
    )


def _env_stale_infer_minutes() -> int:
    raw = os.getenv("HMI_LOCAL_SDK_STALE_INFER_MINUTES", "45").strip()
    try:
        return max(1, min(24 * 60, int(raw)))
    except ValueError:
        return 120


def _work_run_dir(clip_dir_name: str, clip_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", clip_dir_name).strip("_") or "clip"
    suffix = clip_id.replace("sha256:", "")[:12]
    return LOCAL_ROOT / "work" / "sdk_runs" / f"{safe}_{suffix}"


def _platform_manifest_dir(run_id: str) -> Path:
    return LOCAL_OSS_ROOT / "platform_runs" / run_id


def _sync_platform_run_status(run_id: str) -> None:
    from hmi.platform.store import get_run, set_run_status

    plat = get_run(run_id)
    if plat is None:
        return
    rows = store.query(
        "SELECT status FROM pipeline_run WHERE run_id = ? ORDER BY clip_id",
        (run_id,),
    )
    if not rows:
        return
    statuses = [str(r.get("status") or "pending").lower() for r in rows]
    if any(s == "failed" for s in statuses):
        set_run_status(run_id, "failed")
    elif all(s in {"completed", "success"} for s in statuses):
        label_rows = store.query(
            """
            SELECT clip_id, labels_json
            FROM fact_clip_label
            WHERE run_id = ? AND labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
            ORDER BY clip_id
            """,
            (run_id,),
        )
        if label_rows:
            if len(label_rows) == 1:
                y = json.loads(str(label_rows[0].get("labels_json") or "{}"))
            else:
                y = {
                    "clips": [
                        {
                            "clip_id": str(row.get("clip_id") or ""),
                            "labels": json.loads(str(row.get("labels_json") or "{}")),
                        }
                        for row in label_rows
                    ]
                }
            set_run_status(run_id, "labeled", y=y)
        else:
            set_run_status(run_id, "completed")
    elif any(s == "running" for s in statuses):
        set_run_status(run_id, "running")
    else:
        set_run_status(run_id, "queued")


def _resolve_source_media_path(src: dict[str, Any], kind: str) -> str:
    raw = str(src.get("local_path") or "").strip()
    p = Path(raw) if raw else None
    if p and p.is_file() and p.name == "source_manifest.json":
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            payload = {}
        rel = str(payload.get(kind) or payload.get(f"{kind}_path") or "").strip()
        cand = (p.parent / rel) if rel else None
        if cand is not None and cand.is_file():
            return str(cand.resolve())
        for name in (f"{kind}.wav", f"{kind}.dat", f"{kind}.mp4", f"{kind}.txt"):
            alt = p.parent / name
            if alt.is_file():
                return str(alt.resolve())
    if p and p.is_file():
        return str(p.resolve())
    return raw


def _build_platform_media_manifest(
    *,
    run_id: str,
    sample_id: str,
    sample_sources: list[dict[str, Any]],
) -> dict[str, Any] | None:
    by_kind: dict[str, dict[str, Any]] = {}
    for src in sample_sources:
        mod = modality_of(str(src.get("kind") or ""))
        if mod in {"video", "audio", "text"}:
            by_kind.setdefault(mod, src)
    if not by_kind:
        return None
    if any(modality_of(str(src.get("kind") or "")) == "image" for src in sample_sources):
        raise RuntimeError("image-only lake samples are not executable in this slice")
    run_dir = _platform_manifest_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "clip_id": sample_id,
        "source_name": sample_id[:32],
        "modalities": sorted(by_kind),
        "has_preencoded_video": "video" in by_kind,
        "source_ids": [
            str(s.get("source_id") or "").strip()
            for s in sample_sources
            if str(s.get("source_id") or "").strip()
        ],
        "sources_by_kind": {
            kind: str(src.get("source_id") or "").strip()
            for kind, src in by_kind.items()
            if str(src.get("source_id") or "").strip()
        },
    }
    for kind in ("video", "audio", "text"):
        src = by_kind.get(kind)
        abs_path = _resolve_source_media_path(src, kind) if src else ""
        payload[kind] = abs_path or None
        payload[f"{kind}_path"] = abs_path or None
    manifest_path = run_dir / "source_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "clip_id": sample_id,
        "clip_dir_name": sample_id[:24],
        "bag_oss_key": f"local://platform_runs/{run_id}/source_manifest.json",
        "local_manifest_path": str(manifest_path),
        "source_kind": "raw_media",
    }


def _compile_platform_run(run_id: str) -> dict[str, Any]:
    from hmi.local.pipeline_execution import create_execution_record, execution_label_now
    from hmi.platform.store import get_run, list_sample_sources, set_run_status

    plat = get_run(run_id)
    if plat is None:
        raise RuntimeError(f"platform_run not found: {run_id}")
    sample_sources = list_sample_sources(str(plat["sample_id"]))
    if not sample_sources:
        raise RuntimeError(f"platform_run sample has no sources: {plat['sample_id']}")

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    create_execution_record(
        run_id=run_id,
        label=execution_label_now(),
        started_at=started_at,
        data_type_id=str(plat["data_type_id"]),
    )

    rosbag_sources = [s for s in sample_sources if modality_of(str(s.get("kind") or "")) == "rosbag"]
    media_manifest = _build_platform_media_manifest(
        run_id=run_id,
        sample_id=str(plat["sample_id"]),
        sample_sources=sample_sources,
    )

    ds = datetime.now(timezone.utc).strftime("%Y%m%d")
    clip_count = 0
    for src in rosbag_sources:
        clip_id = str(src.get("source_id") or "").strip()
        bag_oss_key = str(src.get("local_oss_key") or "").strip()
        clip_dir_name = str(src.get("filename") or clip_id[:24]).strip() or clip_id[:24]
        pr.upsert_clip_row(
            clip_id=clip_id,
            clip_dir_name=clip_dir_name,
            content_hash=str(src.get("content_hash") or clip_id.replace("sha256:", ""))[:64],
            bag_oss_key=bag_oss_key,
            active_run_id=run_id,
        )
        pr.upsert_run(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            status="pending",
            started_at=started_at,
            reset_started_at=True,
        )
        pr.init_sdk_steps(run_id=run_id, clip_id=clip_id, ds=ds)
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_discover", status="success")
        clip_count += 1

    if media_manifest is not None:
        clip_id = str(media_manifest["clip_id"])
        pr.upsert_clip_row(
            clip_id=clip_id,
            clip_dir_name=str(media_manifest["clip_dir_name"]),
            content_hash=clip_id.replace("sha256:", "")[:64],
            bag_oss_key=str(media_manifest["bag_oss_key"]),
            active_run_id=run_id,
        )
        pr.upsert_run(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            status="pending",
            started_at=started_at,
            reset_started_at=True,
        )
        pr.init_sdk_steps(run_id=run_id, clip_id=clip_id, ds=ds)
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_discover", status="success")
        clip_count += 1

    if clip_count <= 0:
        set_run_status(run_id, "failed")
        raise RuntimeError("platform_run compiled zero executable clips")
    set_run_status(run_id, "running")
    return {"clip_count": clip_count}


def _claim_platform_runs(*, limit: int) -> None:
    from hmi.platform.store import list_runs_by_status, try_claim_run

    candidates = list_runs_by_status(["queued"], limit=max(1, limit))
    for row in candidates:
        run_id = str(row.get("run_id") or "")
        if not run_id or not try_claim_run(run_id):
            continue
        try:
            _compile_platform_run(run_id)
            logger.info("compiled platform_run=%s into local sdk queue", run_id)
        except Exception as exc:  # noqa: BLE001
            from hmi.platform.store import set_run_status

            logger.exception("compile platform_run failed run_id=%s", run_id)
            set_run_status(run_id, "failed")
            _status["last_error"] = str(exc)


def _client_config_overrides(recipe: dict[str, Any] | None = None) -> dict[str, Any]:
    from hmi.local.pipeline_settings import get_pipeline_settings, omni_label_prompt_overrides_for_worker
    from hmi.platform.label_model_params import compact_omni_prompt

    s = get_pipeline_settings()
    out: dict[str, Any] = {}
    omni = str(s.get("omni_model") or "default")
    embed = str(s.get("embedding_model") or "default")
    if omni and omni != "default":
        out["omni_model"] = omni
    if embed and embed != "default":
        out["embedding_model"] = embed
    prompt_overrides = omni_label_prompt_overrides_for_worker()
    if prompt_overrides:
        out["omni_label_prompt"] = dict(prompt_overrides)

    label_stage = ((recipe or {}).get("stages") or {}).get("label") or {}
    if not isinstance(label_stage, dict):
        return out
    # Recipe node params win over global pipeline settings.
    model_id = str(label_stage.get("omni_model_id") or "").strip()
    if model_id:
        out["omni_model"] = model_id
    node_prompt = compact_omni_prompt(label_stage.get("omni_label_prompt"))
    if node_prompt:
        merged = dict(out.get("omni_label_prompt") or {})
        merged.update(node_prompt)
        out["omni_label_prompt"] = merged
    return out


def _run_audio_array_spec(
    *,
    work_run: Path,
    source_manifest_path: Path | None,
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str,
    recipe: dict[str, Any] | None = None,
) -> None:
    from hmi.local.audio_spectrum import analyze_pcm_pa
    from hmi.local.head_dat import parse_head_dat_bytes

    if source_manifest_path is None or not source_manifest_path.is_file():
        raise RuntimeError("audio_array_spec requires source_manifest")
    base = source_manifest_path.parent
    man = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    pcm_path = base / "pcm_pa.npy"
    meta_path = base / "head_meta.json"
    pcm_pa = None
    fs = None
    ch_names: list[str] = []
    loaded_meta_path: Path | None = None

    def _load_pcm_from_paths(pcm_file: Path, meta_file: Path) -> None:
        nonlocal pcm_pa, fs, ch_names, loaded_meta_path
        import numpy as np

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        pcm_pa = np.load(pcm_file)
        fs = float(meta["fs_hz"])
        ch_names = [str(c.get("name") or f"ch{i+1}") for i, c in enumerate(meta.get("channels") or [])]
        loaded_meta_path = meta_file

    if pcm_path.is_file() and meta_path.is_file():
        _load_pcm_from_paths(pcm_path, meta_path)
    else:
        audio_rel = str(man.get("audio") or man.get("audio_path") or "").strip()
        audio_path = Path(audio_rel) if audio_rel and Path(audio_rel).is_file() else None
        if audio_path is not None:
            src_pcm = audio_path.parent / "pcm_pa.npy"
            src_meta = audio_path.parent / "head_meta.json"
            if src_pcm.is_file() and src_meta.is_file():
                _load_pcm_from_paths(src_pcm, src_meta)
        if pcm_pa is None:
            dat_path = base / "source.dat"
            if not dat_path.is_file():
                dat_path = audio_path if audio_path is not None else base / "audio.dat"
            if dat_path.suffix.lower() != ".dat" or not dat_path.is_file():
                raise RuntimeError(
                    "audio_array_spec 需要 HEAD 麦克风阵列 .dat（或同目录 pcm_pa.npy + head_meta.json）；"
                    f"当前源为 {dat_path.name if dat_path else '缺失'}，不能用 e2e/普通 wav 开跑"
                )
            parsed = parse_head_dat_bytes(dat_path.read_bytes())
            pcm_pa = parsed["pcm_pa"]
            fs = float(parsed["fs_hz"])
            ch_names = [str(c.get("name") or f"ch{i+1}") for c in parsed["channels"]]

    spec_dir = work_run / "audio_spec"
    summary = analyze_pcm_pa(pcm_pa, fs, ch_names, spec_dir)
    (work_run / "audio_spec_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Persist parse inputs next to L2 so deriver / artifacts are self-contained.
    import shutil

    import numpy as np

    from hmi.local.nvh_deriver import (
        derive_nvh_labels,
        persist_nvh_labels_artifact,
    )
    from hmi.platform.store import lookup_or_record_product

    # Product lineage: source → preprocess op → artifact (cache key for reuse).
    audio_sid = str((man.get("sources_by_kind") or {}).get("audio") or "").strip()
    input_ids = [audio_sid] if audio_sid else [
        str(x).strip() for x in (man.get("source_ids") or []) if str(x).strip()
    ]
    if not input_ids:
        input_ids = [clip_id]
    product_specs = [
        ("parse_head_dat", {"artifact": "pcm_pa.npy"}),
        ("stft_spectrogram", {"artifact": "audio_spec"}),
        ("mel_spectrogram", {"artifact": "audio_spec"}),
        ("third_octave", {"artifact": "audio_spec"}),
        ("spl_timeline", {"artifact": "audio_spec"}),
    ]
    for op_id, meta in product_specs:
        rel = str(meta["artifact"])
        art = work_run / rel
        lookup_or_record_product(
            input_ids=input_ids,
            op_id=op_id,
            params={"data_type_id": "audio_array_spec"},
            artifact_path=str(art) if art.exists() or art.is_dir() else rel,
            run_id=run_id,
        )

    if loaded_meta_path is not None and loaded_meta_path.is_file():
        shutil.copy2(loaded_meta_path, work_run / "head_meta.json")
    else:
        (work_run / "head_meta.json").write_text(
            json.dumps(
                {
                    "format": "head_acoustics_hdf_v4",
                    "fs_hz": fs,
                    "duration_s": float(pcm_pa.shape[0] / float(fs)),
                    "n_channels": int(pcm_pa.shape[1]),
                    "unit": "Pa",
                    "channels": [
                        {"name": n, "map_factor": 1.0}
                        for n in ch_names
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    np.save(work_run / "pcm_pa.npy", pcm_pa)
    nvh_labels = derive_nvh_labels(work_run, source_dir=base)
    # L6 semantic AI: only when recipe stages.label.enabled (default heuristic).
    label_stage = ((recipe or {}).get("stages") or {}).get("label") or {}
    if bool(label_stage.get("enabled")):
        from hmi.local.nvh_ai_label import fill_nvh_semantic_labels

        ast_top_k = label_stage.get("ast_top_k")
        try:
            ast_top_k_i = int(ast_top_k) if ast_top_k is not None else None
        except (TypeError, ValueError):
            ast_top_k_i = None
        nvh_labels = fill_nvh_semantic_labels(
            work_run,
            nvh_labels,
            model=str(label_stage.get("model") or "nvh_sem_heuristic"),
            ast_top_k=ast_top_k_i,
            vl_prompt=str(label_stage.get("vl_prompt") or "").strip() or None,
            vl_model=str(label_stage.get("vl_model") or "").strip() or None,
            reference_constraints=str(label_stage.get("reference_constraints") or "").strip() or None,
        )
        logger.info(
            "audio_array_spec semantic AI clip=%s run=%s model=%s mode=%s",
            clip_id,
            run_id,
            (nvh_labels.get("_meta") or {}).get("ai_model"),
            (nvh_labels.get("_meta") or {}).get("ai_mode"),
        )
    persist_nvh_labels_artifact(work_run, nvh_labels)
    _publish_nvh_run(
        work_run=work_run,
        source_manifest_path=source_manifest_path,
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        bag_oss_key=bag_oss_key,
        nvh_labels=nvh_labels,
        mark_infer_success=True,
    )


def _publish_nvh_run(
    *,
    work_run: Path,
    source_manifest_path: Path | None,
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str,
    nvh_labels: dict[str, Any] | None = None,
    mark_infer_success: bool = False,
    apply_nvh_facts: bool = True,
) -> None:
    import shutil

    from hmi.local.nvh_deriver import apply_nvh_labels_to_facts

    if apply_nvh_facts and nvh_labels is None:
        nvh_path = work_run / "nvh_labels.json"
        if not nvh_path.is_file():
            raise RuntimeError("NVH run missing nvh_labels.json")
        nvh_labels = json.loads(nvh_path.read_text(encoding="utf-8"))
        if not isinstance(nvh_labels, dict):
            raise RuntimeError("nvh_labels.json is not an object")
    elif nvh_labels is None:
        nvh_path = work_run / "nvh_labels.json"
        if nvh_path.is_file():
            try:
                loaded = json.loads(nvh_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    nvh_labels = loaded
            except json.JSONDecodeError:
                nvh_labels = None

    man: dict[str, Any] = {}
    if source_manifest_path is not None and source_manifest_path.is_file():
        try:
            loaded = json.loads(source_manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                man = loaded
        except json.JSONDecodeError:
            man = {}
    wr_man = work_run / "source_manifest.json"
    if not man and wr_man.is_file():
        try:
            loaded = json.loads(wr_man.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                man = loaded
        except json.JSONDecodeError:
            man = {}

    if mark_infer_success:
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="success")
    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="running")
    try:
        from hmi.data_source import artifacts_dir
        from hmi.local.oss_publish import mirror_artifacts_run_to_oss, write_local_dispatch_manifest

        dest = artifacts_dir(clip_id, run_id)
        dest.mkdir(parents=True, exist_ok=True)
        for path in work_run.rglob("*"):
            if not path.is_file():
                continue
            target = dest / path.relative_to(work_run)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        src_wav = Path(str(man.get("audio") or man.get("audio_path") or ""))
        if src_wav.is_file() and src_wav.suffix.lower() in {".wav", ".flac", ".mp3"}:
            preview = dest / "preview"
            preview.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_wav, preview / "audio.wav")
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="success")
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="running")
        n = mirror_artifacts_run_to_oss(clip_id, run_id)
        if n <= 0:
            raise RuntimeError("no files mirrored to local OSS")
        write_local_dispatch_manifest(
            clip_id=clip_id,
            run_id=run_id,
            bag_oss_key=bag_oss_key,
            ds=ds,
        )
        if apply_nvh_facts and isinstance(nvh_labels, dict):
            apply_nvh_labels_to_facts(
                clip_id=clip_id,
                run_id=run_id,
                ds=ds,
                labels=nvh_labels,
                update_platform_run=True,
            )
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="success")
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_dispatch", status="success")
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="completed")
    except Exception as exc:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_upload",
            status="failed",
            error_message=str(exc),
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        raise
    cache_clear()


def _maybe_create_graph_review(*, clip_id: str, run_id: str, taken: list[str]) -> None:
    if "review" not in taken:
        return
    from hmi.review_db import get_or_create_review

    labels: dict[str, Any] = {}
    try:
        rows = store.query(
            """
            SELECT labels_json FROM fact_clip_label
            WHERE clip_id = ? AND run_id = ?
            LIMIT 1
            """,
            (clip_id, run_id),
        )
        if rows:
            raw = rows[0].get("labels_json")
            if isinstance(raw, dict):
                labels = raw
            elif isinstance(raw, str) and raw.strip() and raw not in ("{}", "[]"):
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    labels = parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph review labels lookup failed clip=%s run=%s: %s", clip_id, run_id, exc)
        labels = {}
    get_or_create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
    )


def _run_sdk_and_ingest(
    *,
    bag_path: Path | None,
    source_manifest_path: Path | None,
    clip_id: str,
    run_id: str,
    ds: str,
    clip_dir_name: str,
    bag_oss_key: str,
) -> None:
    from oms_multimodal.capabilities import RunContext, RunRequest, plan_and_run
    from oms_multimodal.client import OmsMultimodalClient
    from oms_multimodal.config import ClientConfig

    from hmi.local.pipeline_settings import (
        apply_bbox_settings_to_environ,
        assert_bbox_settings_runnable,
        get_pipeline_settings,
    )

    work_run = _work_run_dir(clip_dir_name, clip_id)
    if work_run.is_dir():
        import shutil

        shutil.rmtree(work_run, ignore_errors=True)
    work_run.mkdir(parents=True, exist_ok=True)

    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="running")
    pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="running")
    cache_clear()

    settings = get_pipeline_settings()
    recipe: dict[str, Any] | None = None
    try:
        from hmi.local.pipeline_execution import get_execution_data_type_id
        from hmi.platform.run_bind import overlay_pipeline_settings, recipe_with_dag_overrides
        from hmi.platform.store import get_data_type

        dt_id = get_execution_data_type_id(run_id)
        if dt_id:
            recipe = get_data_type(dt_id)
            if recipe:
                recipe = recipe_with_dag_overrides(recipe, settings, dt_id)
                settings = overlay_pipeline_settings(settings, recipe)
                logger.info(
                    "local SDK data_type overlay clip=%s run=%s type=%s label=%s embed=%s bbox=%s",
                    clip_id,
                    run_id,
                    dt_id,
                    recipe.get("stages", {}).get("label", {}).get("enabled"),
                    recipe.get("stages", {}).get("embed", {}).get("enabled"),
                    recipe.get("bbox", {}).get("enabled"),
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_type overlay skipped clip=%s run=%s: %s", clip_id, run_id, exc)
    try:
        assert_bbox_settings_runnable(settings)
    except RuntimeError as exc:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_infer",
            status="failed",
            error_message=str(exc),
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        raise
    applied_env = apply_bbox_settings_to_environ(settings)
    try:
        from oms_multimodal.clip_video import resolve_ffmpeg

        os.environ["IMAGEIO_FFMPEG_EXE"] = resolve_ffmpeg()
        applied_env = {**applied_env, "IMAGEIO_FFMPEG_EXE": os.environ["IMAGEIO_FFMPEG_EXE"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffmpeg not resolved before SDK run: %s", exc)
    # Clear sticky face-attr load failure from earlier jobs (e.g. weights
    # downloaded after OpenCV5 Caffe miss) so this run can enrich gender/age.
    try:
        from oms_multimodal.bbox import reset_face_attr_estimator

        reset_face_attr_estimator()
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "local SDK bbox/encode env clip=%s run=%s %s",
        clip_id,
        run_id,
        applied_env,
    )

    # Copy source_manifest into run_dir so CapabilityPlanner can inspect modalities
    if source_manifest_path is not None and source_manifest_path.is_file():
        import json
        import shutil

        dest_man = work_run / "source_manifest.json"
        shutil.copy2(source_manifest_path, dest_man)
        # Rewrite relative media paths to absolute under the sources package dir
        try:
            payload = json.loads(dest_man.read_text(encoding="utf-8"))
            base = source_manifest_path.parent
            for key in ("video", "audio", "text", "video_path", "audio_path", "text_path"):
                rel = payload.get(key)
                if isinstance(rel, str) and rel.strip() and not Path(rel).is_file():
                    abs_p = base / rel
                    if abs_p.is_file():
                        payload[key] = str(abs_p.resolve())
            dest_man.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("normalize source_manifest paths failed: %s", exc)

    dt_id = None
    try:
        from hmi.local.pipeline_execution import get_execution_data_type_id

        dt_id = get_execution_data_type_id(run_id)
    except Exception:  # noqa: BLE001
        dt_id = None
    graph = (recipe or {}).get("graph") if recipe else None
    use_kernel = isinstance(graph, dict) and bool(graph.get("nodes"))
    if dt_id == "audio_array_spec" and source_manifest_path is not None and not use_kernel:
        _run_audio_array_spec(
            work_run=work_run,
            source_manifest_path=source_manifest_path,
            clip_id=clip_id,
            run_id=run_id,
            ds=ds,
            bag_oss_key=bag_oss_key,
            recipe=recipe,
        )
        return

    client_cfg = ClientConfig.from_env(taxonomy_path=_taxonomy_path())
    # Local / ECS pipeline worker always uses DashScope API; ignore MODEL_BACKEND=mc.
    client_cfg.model_backend = "api"
    for key, val in _client_config_overrides(recipe).items():
        setattr(client_cfg, key, val)
    label_stage = ((recipe or {}).get("stages") or {}).get("label") or {}
    work_dir = work_run / "work"
    client = OmsMultimodalClient(config=client_cfg, work_dir=work_dir)
    ctx = RunContext(
        run_dir=work_run,
        work_dir=work_dir,
        clip_id=clip_id,
        run_id=run_id,
        media_mode="local",
    )
    clip_cfg = _clip_config_from_settings()
    recipe_req: dict[str, Any] = {}
    graph_taken: list[str] = []
    if use_kernel:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.capability_sdk import sdk_runner_for_bundle
        from hmi.platform.graph_runtime import assert_runnable_locally, ctx0_from_source_nodes

        try:
            assert_runnable_locally(graph)
            graph_ctx0 = ctx0_from_source_nodes(
                graph,
                {
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "run_dir": str(work_run),
                    "source_manifest_path": str(source_manifest_path)
                    if source_manifest_path is not None
                    else str(work_run / "source_manifest.json"),
                    "record_lineage": True,
                },
            )

            def _on_node(key: str, status: str, err: str | None) -> None:
                pr.set_step(
                    run_id=run_id,
                    clip_id=clip_id,
                    ds=ds,
                    step_id=f"dag:{key}",
                    status=status,
                    error_message=err,
                )
                cache_clear()

            def _on_skipped(key: str) -> None:
                pr.set_step(
                    run_id=run_id,
                    clip_id=clip_id,
                    ds=ds,
                    step_id=f"dag:{key}",
                    status="skipped",
                )
                cache_clear()

            out = execute_recipe_graph(
                graph,
                ctx0=graph_ctx0,
                sdk_runner=sdk_runner_for_bundle(
                    run_dir=work_run,
                    bag_path=bag_path,
                    client=client,
                    clip_config=clip_cfg,
                    recipe=recipe,
                ),
                on_node=_on_node,
                on_skipped=_on_skipped,
            )
            by_key = {str(n.get("key")): n for n in (graph.get("nodes") or []) if isinstance(n, dict)}
            graph_taken = []
            for row in out.get("run") or []:
                if row.get("status") != "success":
                    continue
                node = by_key.get(str(row.get("key") or ""))
                if not node:
                    continue
                graph_taken.append(str(node.get("op_id") or node.get("type") or ""))
            logger.info(
                "local kernel graph clip=%s run=%s taken=%s",
                clip_id,
                run_id,
                graph_taken,
            )
            if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
                cache_clear()
                return
            pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="success")
            from hmi.platform.graph_label_publish import (
                decide_graph_label_publish,
                graph_ctx_labels,
                persist_recipe_clip_labels,
            )

            ctx_labels = graph_ctx_labels(out.get("ctx") if isinstance(out, dict) else None)
            publish_mode = decide_graph_label_publish(recipe, out.get("ctx") if isinstance(out, dict) else None)
            has_nvh = (work_run / "nvh_labels.json").is_file()
            if has_nvh or ctx_labels:
                _publish_nvh_run(
                    work_run=work_run,
                    source_manifest_path=source_manifest_path,
                    clip_id=clip_id,
                    run_id=run_id,
                    ds=ds,
                    bag_oss_key=bag_oss_key,
                    mark_infer_success=False,
                    apply_nvh_facts=publish_mode == "nvh" and has_nvh,
                )
                if publish_mode == "recipe" and ctx_labels:
                    persist_recipe_clip_labels(
                        clip_id=clip_id,
                        run_id=run_id,
                        ds=ds,
                        recipe=recipe,
                        labels=ctx_labels,
                    )
                try:
                    _maybe_create_graph_review(
                        clip_id=clip_id, run_id=run_id, taken=graph_taken
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "graph review node failed clip=%s run=%s: %s",
                        clip_id,
                        run_id,
                        exc,
                    )
                return
        except Exception as exc:
            pr.set_step(
                run_id=run_id,
                clip_id=clip_id,
                ds=ds,
                step_id="sdk_infer",
                status="failed",
                error_message=str(exc),
            )
            pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
            cache_clear()
            raise
    elif recipe is not None:
        from hmi.platform.run_bind import overlay_run_request

        recipe_req = overlay_run_request(recipe, settings)
    if not use_kernel:
        req = RunRequest(
            bag_path=bag_path,
            run_dir=work_run,
            source_manifest_path=(work_run / "source_manifest.json")
            if (work_run / "source_manifest.json").is_file()
            else None,
            encode_plain=bool(settings.get("encode_plain", True)),
            bbox_enabled=bool(
                recipe_req.get("bbox_enabled", settings.get("bbox_enabled", False))
            ),
            bbox_in_label_prompt=bool(
                label_stage["bbox_in_label_prompt"]
                if isinstance(label_stage.get("bbox_in_label_prompt"), bool)
                else settings.get("bbox_in_label_prompt", True)
            ),
            need_label=recipe_req.get("need_label"),
            need_embed=recipe_req.get("need_embed"),
        )
        try:
            result = plan_and_run(
                ctx,
                bag_path,
                client,
                request=req,
                clip_config=clip_cfg,
            )
            if result.errors:
                raise RuntimeError(str(result.errors[0]))
            logger.info(
                "local SDK plan clip=%s run=%s stages=%s",
                clip_id,
                run_id,
                result.stages_done,
            )
            if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
                cache_clear()
                return
            pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="success")
        except Exception as exc:
            pr.set_step(
                run_id=run_id,
                clip_id=clip_id,
                ds=ds,
                step_id="sdk_infer",
                status="failed",
                error_message=str(exc),
            )
            pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
            cache_clear()
            raise

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="running")
    env = os.environ.copy()
    env["HMI_RUNTIME_ROOT"] = str(LOCAL_ROOT)
    script = REPO_ROOT / "hmi" / "scripts" / "import_real_data_clips.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--from-path",
            str(work_run),
            "--no-review",
            "--run-id",
            run_id,
            "--clip-id",
            clip_id,
            "--bag-oss-key",
            bag_oss_key,
        ],
        cwd=str(REPO_ROOT / "hmi"),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raw = (proc.stderr or proc.stdout or "import failed")[:2000]
        if "no importable runs" in raw:
            work_labels = work_run / "labels.jsonl"
            work_embed = work_run / "fusion_embeddings.jsonl"
            if work_labels.is_file() and not work_embed.is_file():
                msg = (
                    "导入失败：有 labels.jsonl 但缺少 fusion_embeddings.jsonl。"
                    "未开向量化时应仍能导入标签；请确认当前导入脚本已允许缺 embeddings。\n"
                    + raw
                )
            elif not work_labels.is_file():
                msg = (
                    "导入失败：工作目录没有 labels.jsonl（打标步骤可能被跳过）。\n"
                    + raw
                )
            else:
                msg = "导入失败：\n" + raw
        else:
            msg = raw
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_mc_write",
            status="failed",
            error_message=msg,
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        raise RuntimeError(msg)
    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return
    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="success")

    try:
        _maybe_create_graph_review(clip_id=clip_id, run_id=run_id, taken=graph_taken)
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph review node failed clip=%s run=%s: %s", clip_id, run_id, exc)

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="running")
    try:
        from hmi.local.oss_publish import mirror_artifacts_run_to_oss, write_local_dispatch_manifest

        n = mirror_artifacts_run_to_oss(clip_id, run_id)
        if n <= 0:
            raise RuntimeError("no files mirrored to local OSS")
        write_local_dispatch_manifest(
            clip_id=clip_id,
            run_id=run_id,
            bag_oss_key=bag_oss_key,
            ds=ds,
        )
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="success")
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_dispatch", status="success")
    except Exception as exc:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_upload",
            status="failed",
            error_message=str(exc),
        )
        raise

    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return

    pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="completed")
    cache_clear()

    from hmi.services import oss_sync_poller

    if oss_sync_poller.is_auto_sync_enabled():
        try:
            from hmi.local.sync_from_oss import sync_runtime_from_local_oss

            sync_runtime_from_local_oss(clip_id, run_id, ds=ds)
            cache_clear()
        except Exception as exc:
            logger.warning("auto sync from local OSS failed: %s", exc)


def _process_one(row: dict[str, Any], *, bag_oss_key: str) -> None:
    clip_id = str(row["clip_id"])
    run_id = str(row["run_id"])
    ds = str(row["ds"])
    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return
    clip_dir_name = str(row.get("clip_dir_name") or clip_id[:16])

    from hmi.local.source_upload import resolve_local_source_manifest

    source_manifest = resolve_local_source_manifest(bag_oss_key)
    bag_path = resolve_local_bag_path(bag_oss_key) if source_manifest is None else None
    if bag_path is None and source_manifest is None:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_discover",
            status="failed",
            error_message="bag/source missing",
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        return
    _run_sdk_and_ingest(
        bag_path=bag_path,
        source_manifest_path=source_manifest,
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        clip_dir_name=clip_dir_name,
        bag_oss_key=bag_oss_key,
    )


def _process_one_wrapper(row: dict[str, Any], *, bag_oss_key: str) -> None:
    global _active_jobs
    clip_id = str(row.get("clip_id") or "")
    run_id = str(row.get("run_id") or "")
    ds = str(row.get("ds") or "")
    try:
        _status["last_clip_id"] = clip_id
        _status["last_run_id"] = run_id
        _status["last_error"] = None
        _process_one(row, bag_oss_key=bag_oss_key)
        _sync_platform_run_status(run_id)
        _status["last_finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        logger.exception("local SDK job failed")
        _status["last_error"] = str(exc)
        # Import/OSS failures are already on sdk_mc_write / sdk_upload.
        # Do not rewrite sdk_infer=success into failed — the progress UI would
        # then blame the first DAG node (ROSBAG 解析器) for an ingest error.
        if clip_id and run_id and ds:
            try:
                infer_status = pr.get_step_status(
                    run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer"
                )
                if infer_status in {None, "pending", "running"}:
                    pr.set_step(
                        run_id=run_id,
                        clip_id=clip_id,
                        ds=ds,
                        step_id="sdk_infer",
                        status="failed",
                        error_message=str(exc)[:500],
                    )
                pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
                cache_clear()
            except Exception:  # noqa: BLE001
                logger.exception("failed to mark sdk_infer failed after worker error")
        _sync_platform_run_status(run_id)
    finally:
        with _lock:
            _active_jobs = max(0, _active_jobs - 1)


def _tick() -> None:
    global _active_jobs
    if not is_poll_enabled():
        return
    store.ensure_db()
    stale = pr.reset_stale_sdk_infer_jobs(stale_minutes=_env_stale_infer_minutes())
    if stale:
        logger.warning("reset %s stale sdk_infer job(s) to pending", stale)
        cache_clear()
    max_parallel = _max_parallel()
    with _lock:
        slots = max_parallel - _active_jobs
        if slots <= 0:
            return
    _claim_platform_runs(limit=max(slots, 1))
    pending = pr.list_runs_needing_sdk(limit=max(slots * 2, slots) if max_parallel > 1 else 1)
    if not pending:
        return
    for row in pending:
        clip_id = str(row.get("clip_id") or "")
        run_id = str(row.get("run_id") or "")
        ds = str(row.get("ds") or "")
        if not clip_id or not run_id or not ds:
            continue
        if not pr.try_claim_sdk_infer(run_id=run_id, clip_id=clip_id, ds=ds):
            continue
        bag_key = str(row.get("bag_oss_key") or "")
        with _lock:
            if _active_jobs >= max_parallel:
                # Claim already flipped sdk_infer→running; roll back so another tick can retry.
                pr.set_step(
                    run_id=run_id,
                    clip_id=clip_id,
                    ds=ds,
                    step_id="sdk_infer",
                    status="pending",
                )
                pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="pending")
                continue
            _active_jobs += 1
        if max_parallel == 1:
            _process_one_wrapper(row, bag_oss_key=bag_key)
            return
        threading.Thread(
            target=_process_one_wrapper,
            args=(row,),
            kwargs={"bag_oss_key": bag_key},
            daemon=True,
        ).start()


def _loop() -> None:
    interval = _env_int("HMI_LOCAL_SDK_POLL_INTERVAL_SEC", 20)
    _status["interval_sec"] = interval
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("local SDK poller tick")
        _stop.wait(interval)


def start_poller() -> None:
    global _thread
    _status["enabled"] = is_poll_enabled()
    if not is_poll_enabled():
        return
    if _thread and _thread.is_alive():
        # Resume a thread that stop_poller() signalled but has not exited yet.
        _stop.clear()
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="local-sdk-poller", daemon=True)
    _thread.start()
    logger.info(
        "local SDK poller started interval_sec=%s",
        _status.get("interval_sec") or _env_int("HMI_LOCAL_SDK_POLL_INTERVAL_SEC", 20),
    )


def stop_poller() -> None:
    _stop.set()
    _status["enabled"] = False


def wait_idle(*, timeout_sec: float = 120.0) -> bool:
    """Wait until in-flight SDK jobs finish (poller may already be stopped)."""
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while time.monotonic() < deadline:
        with _lock:
            if _active_jobs <= 0:
                return True
        time.sleep(0.25)
    with _lock:
        return _active_jobs <= 0
