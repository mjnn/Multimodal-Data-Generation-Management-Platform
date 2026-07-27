# =============================================================================
# DataWorks PyODPS 3 节点：Job4-向量化（MaxFrame + DPE）
#
# ★★★ DataWorks 必须粘贴 bundled 整文件，勿粘贴本文件 ★★★
#   python scripts/bundle_dataworks_node.py dataworks/job4_embed_node.py
#   → 粘贴 dataworks/bundled/job4_embed_node.py（约 1500+ 行，含 mf_ai_function 内联）
#
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 读 Job3：clips/{clip_id}/runs/{run_id}/job3/job3_mc_payload.json（抽样帧）
# 读 Job2：clips/{clip_id}/runs/{run_id}/job2/job2_asr_payload.json（ASR 分段）
# 写 Job4：clips/{clip_id}/runs/{run_id}/job4/embeddings.jsonl
#          clips/{clip_id}/runs/{run_id}/job4/job4_mc_payload.json
#
# storage_mode：separate | unified | both（见 config.yaml cloud.job4_embed）
#
# ---------------------------------------------------------------------------
# 工作流参数（与 Job1 共用）
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   oss_ram_role_arn=
#   oss_mount_prefix=
#   oss_prefix_template=clips/{clip_id}/
#   dpe_cpu=2
#   dpe_memory_gb=8
#   dpe_mount_path=/mnt/oss
#   dpe_image=rosbag_dpe_deps
#   job4_config_json=
#   oss_vl_access_key_id=           # VL 图像 embedding（qwen3-vl-embedding）读 OSS
#   oss_vl_access_key_secret=
#   ※ oss_ram_role_arn 仅 DPE 挂载；IMAGE_URL 须 AK/SK
#
# 节点参数
#   clip_id=sha256:...
#   run_id=<Job1 相同>
#   storage_mode=separate          # separate|unified|both，留空=配置默认
#   embed_batch_size=64
#   image_embed_model=
#   text_embed_model=
#   unified_embed_model=
#   total_rpm_limit=12000          # AI Function running_options；0=不传
#   request_timeout=300            # 单次请求超时（秒）；0=不传
#   ai_memory=8G                   # AI Function Worker 内存；留空=不传
# =============================================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import importlib.util
import sys

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options

from pipeline_dispatch import (
    exit_if_pipeline_idle,
    read_oss_json_object,
    resolve_oss_http_endpoint,
    resolve_pipeline_context,
    write_oss_object_text,
)

_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}

DEFAULT_JOB4_CONFIG: dict[str, Any] = {
    "provider": "maxframe_ai_function",
    "storage_mode": "separate",
    "models": {
        "image": {"model": "", "model_version": "", "dim": 768},
        "text": {"model": "", "model_version": "", "dim": 768},
        "unified": {"model": "", "model_version": "", "dim": 768},
    },
    "batch_size": 64,
}


def _load_mf_ai_function() -> None:
    """Local dev only; bundled DataWorks paste already inlines mf_ai_function.py."""
    if "configure_mf_ai_engine" in globals():
        return
    file_path = globals().get("__file__")
    if not file_path:
        return
    helper = Path(file_path).resolve().parent / "mf_ai_function.py"
    if not helper.is_file():
        return
    spec = importlib.util.spec_from_file_location("mf_ai_function", helper)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["mf_ai_function"] = module
    spec.loader.exec_module(module)
    for name in (
        "configure_mf_ai_engine",
        "apply_ai_quota",
        "prepare_mf_ai_runtime",
        "ai_embed_texts",
        "ai_embed_oss_image_urls",
        "is_vl_embedding_model",
        "build_vl_oss_storage_options",
        "oss_key_for_frame_image",
        "extract_asr_plain_text",
    ):
        if hasattr(module, name):
            globals()[name] = getattr(module, name)


_load_mf_ai_function()


def _asr_text_for_embed(segment: dict[str, Any]) -> str:
    raw = segment.get("asr_text")
    if "extract_asr_plain_text" in globals():
        return extract_asr_plain_text(raw)
    return str(raw or "").strip()


def _parse_skynet_args(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return {str(k): str(v) for k, v in loaded.items()}
    parsed: dict[str, str] = {}
    for token in re.split(r"[;\s]+", text):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _all_arg_sources() -> dict[str, str]:
    merged: dict[str, str] = {}
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    for env_name, arg_name in (
        ("OSS_BUCKET", "oss_bucket"),
        ("CLOUD_REGION", "cloud_region"),
        ("OSS_VL_ACCESS_KEY_ID", "oss_vl_access_key_id"),
        ("OSS_VL_ACCESS_KEY_SECRET", "oss_vl_access_key_secret"),
        ("OSS_ACCESS_KEY_ID", "oss_access_key_id"),
        ("OSS_ACCESS_KEY_SECRET", "oss_access_key_secret"),
    ):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            merged[arg_name] = env_value
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            for key, value in node_args.items():
                if value is not None and str(value).strip():
                    merged[str(key)] = str(value).strip()
    except NameError:
        pass
    return merged


def get_arg(name: str, default: str | None = None) -> str | None:
    if default is None:
        default = _PROJECT_DEFAULTS.get(name)
    value = _all_arg_sources().get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        resolved = _all_arg_sources()
        raise ValueError(
            f"Missing required parameter: {name}. "
            f"Resolved keys: {sorted(resolved.keys()) or '(empty)'}"
        )
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def _resolve_oss_vl_ak_sk() -> tuple[str, str]:
    ak = get_arg("oss_vl_access_key_id") or get_arg("oss_access_key_id") or ""
    sk = get_arg("oss_vl_access_key_secret") or get_arg("oss_access_key_secret") or ""
    return ak, sk


def load_job4_config() -> dict[str, Any]:
    raw = get_arg("job4_config_json")
    if not raw:
        return DEFAULT_JOB4_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("job4_config_json must be a JSON object")
    return loaded


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    region_id = region.replace("_", "-")
    normalized = prefix.strip("/")
    if not normalized:
        return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/"
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{normalized}/"


def _storage_options(role_arn: str | None, account: Any) -> dict[str, str]:
    if role_arn:
        return {"role_arn": role_arn}
    return {
        "oss_access_key_id": account.access_id,
        "oss_access_key_secret": account.secret_access_key,
    }


def _apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stub_vector(dim: int) -> list[float]:
    return [0.0] * dim


def _resolve_model_version(model_cfg: dict[str, Any]) -> str:
    model = str(model_cfg.get("model") or "")
    version = str(model_cfg.get("model_version") or "")
    if version:
        return version
    return "none" if not model else model


def _resolve_frame_image_path(parsed_root: Path, frame: dict[str, Any]) -> Path:
    raw = str(frame.get("image_relpath") or frame.get("image_path") or "").strip().lstrip("/")
    candidates = [parsed_root / raw]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        candidates.append(parsed_root / raw.rsplit(parsed_marker, 1)[-1].lstrip("/"))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _embed_frame_stub(
    *,
    frame: dict[str, Any],
    parsed_root: Path,
    model_cfg: dict[str, Any],
    storage_mode: str,
) -> dict[str, Any]:
    dim = int(model_cfg.get("dim") or 768)
    image_path = _resolve_frame_image_path(parsed_root, frame)
    image_bytes = image_path.read_bytes() if image_path.is_file() else b""
    vector = _stub_vector(dim)
    model = str(model_cfg.get("model") or "")
    if model:
        # MC AI 接入点：当前版本输出零向量占位，保留 dim/model_version。
        pass
    return {
        "object_type": "frame",
        "object_id": str(frame["frame_id"]),
        "timestamp_ns": int(frame["timestamp_ns"]),
        "start_ns": None,
        "end_ns": None,
        "vector_json": vector,
        "model_version": _resolve_model_version(model_cfg),
        "dim": dim,
        "storage_mode": storage_mode,
        "source_bytes": len(image_bytes),
    }


def _embed_audio_segment_stub(
    *,
    segment: dict[str, Any],
    model_cfg: dict[str, Any],
    storage_mode: str,
) -> dict[str, Any]:
    dim = int(model_cfg.get("dim") or 768)
    asr_text = _asr_text_for_embed(segment)
    vector = _stub_vector(dim)
    model = str(model_cfg.get("model") or "")
    if model:
        pass
    return {
        "object_type": "audio_segment",
        "object_id": str(int(segment["segment_id"])),
        "timestamp_ns": int(segment["start_ns"]),
        "start_ns": int(segment["start_ns"]),
        "end_ns": int(segment["end_ns"]),
        "vector_json": vector,
        "model_version": _resolve_model_version(model_cfg),
        "dim": dim,
        "storage_mode": storage_mode,
        "source_text_len": len(asr_text),
    }


def _merge_model_cfg(
    base: dict[str, Any],
    *,
    model_override: str,
    version_override: str,
) -> dict[str, Any]:
    merged = dict(base)
    if model_override:
        merged["model"] = model_override
    if version_override:
        merged["model_version"] = version_override
    return merged


def build_embeddings(
    *,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    parsed_root: Path,
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    batch_size: int,
) -> list[dict[str, Any]]:
    models = job4_config.get("models") or DEFAULT_JOB4_CONFIG["models"]
    image_cfg = _merge_model_cfg(
        models.get("image") or {},
        model_override=model_overrides.get("image", ""),
        version_override=version_overrides.get("image", ""),
    )
    text_cfg = _merge_model_cfg(
        models.get("text") or {},
        model_override=model_overrides.get("text", ""),
        version_override=version_overrides.get("text", ""),
    )
    unified_cfg = _merge_model_cfg(
        models.get("unified") or {},
        model_override=model_overrides.get("unified", ""),
        version_override=version_overrides.get("unified", ""),
    )

    embeddings: list[dict[str, Any]] = []

    def process_frames(cfg: dict[str, Any], mode: str) -> None:
        for start in range(0, len(labeled_frames), batch_size):
            batch = labeled_frames[start : start + batch_size]
            for frame in batch:
                embeddings.append(
                    _embed_frame_stub(
                        frame=frame,
                        parsed_root=parsed_root,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )

    def process_segments(cfg: dict[str, Any], mode: str) -> None:
        for start in range(0, len(audio_segments), batch_size):
            batch = audio_segments[start : start + batch_size]
            for segment in batch:
                embeddings.append(
                    _embed_audio_segment_stub(
                        segment=segment,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )

    if storage_mode in {"separate", "both"}:
        process_frames(image_cfg, "separate")
        process_segments(text_cfg, "separate")

    if storage_mode in {"unified", "both"}:
        process_frames(unified_cfg, "unified")
        process_segments(unified_cfg, "unified")

    if storage_mode not in {"separate", "unified", "both"}:
        raise ValueError(f"Unsupported storage_mode: {storage_mode}")

    return embeddings


def _embed_texts_with_ai(
    texts: list[str],
    model_cfg: dict[str, Any],
    odps_entry: Any,
    *,
    modelset_project: str,
    parallel_partitions: int,
    storage_mode: str,
    object_type: str,
    object_ids: list[str],
    timestamps: list[int],
    starts: list[int | None],
    ends: list[int | None],
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    model = str(model_cfg.get("model") or "")
    if not model:
        return []
    if "ai_embed_texts" not in globals():
        raise RuntimeError(
            "mf_ai_function not loaded. DataWorks 请粘贴 "
            "dataworks/bundled/job4_embed_node.py（非 job4_embed_node.py）。"
            "本地生成: python scripts/bundle_dataworks_node.py dataworks/job4_embed_node.py"
        )

    vectors = ai_embed_texts(
        texts,
        model,
        odps_entry,
        modelset_project=modelset_project,
        parallel_partitions=parallel_partitions,
        total_rpm_limit=total_rpm_limit,
        request_timeout=request_timeout,
        ai_memory=ai_memory,
    )
    dim = int(model_cfg.get("dim") or (len(vectors[0]) if vectors and vectors[0] else 768))
    model_version = _resolve_model_version(model_cfg)
    results: list[dict[str, Any]] = []
    for idx, vector in enumerate(vectors):
        vec = vector if vector else _stub_vector(dim)
        results.append(
            {
                "object_type": object_type,
                "object_id": object_ids[idx],
                "timestamp_ns": timestamps[idx],
                "start_ns": starts[idx],
                "end_ns": ends[idx],
                "vector_json": vec,
                "model_version": model_version,
                "dim": len(vec),
                "storage_mode": storage_mode,
            }
        )
    return results


def build_embeddings_with_ai(
    *,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    odps_entry: Any,
    modelset_project: str,
    parallel_partitions: int,
    cloud_region: str,
    oss_bucket: str,
    parsed_relpath: str | None = None,
    vl_storage_options: dict[str, str] | None = None,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    models = job4_config.get("models") or DEFAULT_JOB4_CONFIG["models"]
    image_cfg = _merge_model_cfg(
        models.get("image") or {},
        model_override=model_overrides.get("image", ""),
        version_override=version_overrides.get("image", ""),
    )
    text_cfg = _merge_model_cfg(
        models.get("text") or {},
        model_override=model_overrides.get("text", ""),
        version_override=version_overrides.get("text", ""),
    )
    unified_cfg = _merge_model_cfg(
        models.get("unified") or {},
        model_override=model_overrides.get("unified", ""),
        version_override=version_overrides.get("unified", ""),
    )

    embeddings: list[dict[str, Any]] = []
    region_id = cloud_region.replace("_", "-")

    def add_frame_embeddings(cfg: dict[str, Any], mode: str) -> None:
        if not str(cfg.get("model") or ""):
            for frame in labeled_frames:
                embeddings.append(
                    _embed_frame_stub(
                        frame=frame,
                        parsed_root=Path("."),
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )
            return
        model = str(cfg.get("model") or "")
        use_vl_image = (
            "is_vl_embedding_model" in globals()
            and is_vl_embedding_model(model)
            and "ai_embed_oss_image_urls" in globals()
        )
        if use_vl_image:
            if not vl_storage_options:
                raise ValueError(
                    "image_embed_model is VL embedding but OSS VL AK/SK missing. "
                    "Set oss_vl_access_key_id + oss_vl_access_key_secret"
                )
            frame_parsed_relpath = (parsed_relpath or "").strip() or None
            image_urls: list[str] = []
            for frame in labeled_frames:
                image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "")
                if "oss_key_for_frame_image" in globals():
                    oss_key = oss_key_for_frame_image(
                        image_relpath,
                        parsed_relpath=frame_parsed_relpath,
                    )
                else:
                    oss_key = image_relpath.strip("/")
                image_urls.append(
                    f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{oss_key}"
                )
            vectors = ai_embed_oss_image_urls(
                image_urls,
                model,
                odps_entry,
                storage_options=vl_storage_options,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
            dim = int(cfg.get("dim") or (len(vectors[0]) if vectors and vectors[0] else 768))
            model_version = _resolve_model_version(cfg)
            for frame, vector in zip(labeled_frames, vectors):
                vec = vector if vector else _stub_vector(dim)
                embeddings.append(
                    {
                        "object_type": "frame",
                        "object_id": str(frame["frame_id"]),
                        "timestamp_ns": int(frame["timestamp_ns"]),
                        "start_ns": None,
                        "end_ns": None,
                        "vector_json": vec,
                        "model_version": model_version,
                        "dim": len(vec),
                        "storage_mode": mode,
                    }
                )
            return
        texts = []
        for frame in labeled_frames:
            image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "").strip("/")
            texts.append(
                f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{image_relpath}"
            )
        embeddings.extend(
            _embed_texts_with_ai(
                texts,
                cfg,
                odps_entry,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                storage_mode=mode,
                object_type="frame",
                object_ids=[str(f["frame_id"]) for f in labeled_frames],
                timestamps=[int(f["timestamp_ns"]) for f in labeled_frames],
                starts=[None] * len(labeled_frames),
                ends=[None] * len(labeled_frames),
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
        )

    def add_segment_embeddings(cfg: dict[str, Any], mode: str) -> None:
        if not str(cfg.get("model") or ""):
            for segment in audio_segments:
                embeddings.append(
                    _embed_audio_segment_stub(
                        segment=segment,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )
            return
        texts = [_asr_text_for_embed(segment) for segment in audio_segments]
        embeddings.extend(
            _embed_texts_with_ai(
                texts,
                cfg,
                odps_entry,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                storage_mode=mode,
                object_type="audio_segment",
                object_ids=[str(int(s["segment_id"])) for s in audio_segments],
                timestamps=[int(s["start_ns"]) for s in audio_segments],
                starts=[int(s["start_ns"]) for s in audio_segments],
                ends=[int(s["end_ns"]) for s in audio_segments],
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
        )

    if storage_mode in {"separate", "both"}:
        add_frame_embeddings(image_cfg, "separate")
        add_segment_embeddings(text_cfg, "separate")
    if storage_mode in {"unified", "both"}:
        add_frame_embeddings(unified_cfg, "unified")
        add_segment_embeddings(unified_cfg, "unified")
    if storage_mode not in {"separate", "unified", "both"}:
        raise ValueError(f"Unsupported storage_mode: {storage_mode}")
    return embeddings


def _build_job4_prepare_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job4_prepare_row(row):
        job3_payload_path = Path(mount_path) / row["job3_payload_relpath"]
        job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
        if not job3_payload_path.is_file():
            raise FileNotFoundError(f"Job3 payload not found: {job3_payload_path}")
        if not job2_payload_path.is_file():
            raise FileNotFoundError(f"Job2 payload not found: {job2_payload_path}")

        job3_payload = _read_json(job3_payload_path)
        job2_payload = _read_json(job2_payload_path)
        labeled_frames = job3_payload.get("labeled_frames") or []
        audio_segments = job2_payload.get("audio_segments") or []
        if not labeled_frames and not audio_segments:
            raise ValueError("Job4 has no frames or audio segments to embed")

        return {
            "clip_id": str(job3_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job3_payload.get("run_id") or row["run_id"]),
            "parsed_relpath": row["parsed_relpath"],
            "job4_relpath": row["job4_relpath"],
            "labeled_frames_json": json.dumps(labeled_frames, ensure_ascii=False),
            "audio_segments_json": json.dumps(audio_segments, ensure_ascii=False),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_prepare_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job4_write_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    storage_mode: str,
):
    def _job4_write_row(row):
        embeddings = json.loads(str(row["embeddings_json"]))
        labeled_frames = json.loads(str(row["labeled_frames_json"]))
        audio_segments = json.loads(str(row["audio_segments_json"]))

        job4_root = Path(mount_path) / row["job4_relpath"]
        job4_root.mkdir(parents=True, exist_ok=True)
        embeddings_path = job4_root / "embeddings.jsonl"
        with embeddings_path.open("w", encoding="utf-8") as embed_file:
            for item in embeddings:
                embed_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "storage_mode": storage_mode,
            "embeddings": embeddings,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "processed_at": _utc_now_iso(),
        }
        payload_path = job4_root / "job4_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "storage_mode": storage_mode,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "payload_relpath": f"{row['job4_relpath']}/job4_mc_payload.json",
            "embeddings_relpath": f"{row['job4_relpath']}/embeddings.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_write_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job4_embed_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    batch_size: int,
):
    def _job4_embed_row(row):
        job3_payload_path = Path(mount_path) / row["job3_payload_relpath"]
        job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
        if not job3_payload_path.is_file():
            raise FileNotFoundError(f"Job3 payload not found: {job3_payload_path}")
        if not job2_payload_path.is_file():
            raise FileNotFoundError(f"Job2 payload not found: {job2_payload_path}")

        job3_payload = _read_json(job3_payload_path)
        job2_payload = _read_json(job2_payload_path)
        labeled_frames = job3_payload.get("labeled_frames") or []
        audio_segments = job2_payload.get("audio_segments") or []

        if not labeled_frames and not audio_segments:
            raise ValueError("Job4 has no frames or audio segments to embed")

        parsed_root = Path(mount_path) / row["parsed_relpath"]
        embeddings = build_embeddings(
            labeled_frames=labeled_frames,
            audio_segments=audio_segments,
            parsed_root=parsed_root,
            job4_config=job4_config,
            storage_mode=storage_mode,
            model_overrides=model_overrides,
            version_overrides=version_overrides,
            batch_size=batch_size,
        )

        job4_root = Path(mount_path) / row["job4_relpath"]
        job4_root.mkdir(parents=True, exist_ok=True)

        embeddings_path = job4_root / "embeddings.jsonl"
        with embeddings_path.open("w", encoding="utf-8") as embed_file:
            for item in embeddings:
                embed_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": str(job3_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job3_payload.get("run_id") or row["run_id"]),
            "storage_mode": storage_mode,
            "embeddings": embeddings,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "processed_at": _utc_now_iso(),
        }
        payload_path = job4_root / "job4_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": payload["clip_id"],
            "run_id": payload["run_id"],
            "storage_mode": storage_mode,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "payload_relpath": f"{row['job4_relpath']}/job4_mc_payload.json",
            "embeddings_relpath": f"{row['job4_relpath']}/embeddings.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_embed_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _write_job4_artifacts_to_oss(
    *,
    clip_id: str,
    run_id: str,
    job4_relpath: str,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    embeddings: list[dict[str, Any]],
    storage_mode: str,
    oss_bucket: str,
    cloud_region: str,
    account: Any,
) -> dict[str, Any]:
    """Write embeddings.jsonl + job4_mc_payload.json on Driver (avoid MaxFrame 8MB tunnel)."""
    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    embeddings_key = f"{job4_relpath}/embeddings.jsonl"
    payload_key = f"{job4_relpath}/job4_mc_payload.json"
    embeddings_text = "".join(
        json.dumps(item, ensure_ascii=False) + "\n" for item in embeddings
    )
    payload = {
        "clip_id": clip_id,
        "run_id": run_id,
        "storage_mode": storage_mode,
        "embeddings": embeddings,
        "frame_count": len(labeled_frames),
        "audio_segment_count": len(audio_segments),
        "embedding_count": len(embeddings),
        "processed_at": _utc_now_iso(),
    }
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(f"Job4 writing oss://{oss_bucket}/{embeddings_key} ({len(embeddings_text)} bytes)")
    write_oss_object_text(
        bucket_name=oss_bucket,
        object_key=embeddings_key,
        endpoint=endpoint,
        account=account,
        text=embeddings_text,
        region=cloud_region,
        get_arg=get_arg,
    )
    print(f"Job4 writing oss://{oss_bucket}/{payload_key} ({len(payload_text)} bytes)")
    write_oss_object_text(
        bucket_name=oss_bucket,
        object_key=payload_key,
        endpoint=endpoint,
        account=account,
        text=payload_text,
        region=cloud_region,
        get_arg=get_arg,
    )
    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "storage_mode": storage_mode,
        "frame_count": len(labeled_frames),
        "audio_segment_count": len(audio_segments),
        "embedding_count": len(embeddings),
        "payload_relpath": payload_key,
        "embeddings_relpath": embeddings_key,
    }


def _load_job4_inputs_from_oss(
    *,
    oss_bucket: str,
    cloud_region: str,
    account: Any,
    job3_payload_key: str,
    job2_payload_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    job3_payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=job3_payload_key,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if job3_payload is None:
        raise FileNotFoundError(
            f"Job3 payload not found: oss://{oss_bucket}/{job3_payload_key}"
        )
    job2_payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=job2_payload_key,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if job2_payload is None:
        raise FileNotFoundError(
            f"Job2 payload not found: oss://{oss_bucket}/{job2_payload_key}"
        )
    labeled_frames = job3_payload.get("labeled_frames") or []
    audio_segments = job2_payload.get("audio_segments") or []
    if not labeled_frames and not audio_segments:
        raise ValueError("Job4 has no frames or audio segments to embed")
    clip_id = str(job3_payload.get("clip_id") or "")
    run_id = str(job3_payload.get("run_id") or "")
    return labeled_frames, audio_segments, clip_id, run_id


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job4_embed"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    role_arn = get_arg("oss_ram_role_arn")
    oss_mount_prefix = get_arg("oss_mount_prefix", "") or ""
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_cpu = get_int_arg("dpe_cpu", 2)
    dpe_memory = get_int_arg("dpe_memory_gb", 8)
    dpe_image = get_arg("dpe_image")

    job4_config = load_job4_config()
    storage_mode = (
        get_arg("storage_mode") or str(job4_config.get("storage_mode") or "separate")
    ).strip().lower()
    batch_size = get_int_arg("embed_batch_size", int(job4_config.get("batch_size", 64)))

    model_overrides = {
        "image": get_arg("image_embed_model") or "",
        "text": get_arg("text_embed_model") or "",
        "unified": get_arg("unified_embed_model") or "",
    }
    version_overrides = {
        "image": get_arg("image_embed_model_version") or "",
        "text": get_arg("text_embed_model_version") or "",
        "unified": get_arg("unified_embed_model_version") or "",
    }
    ai_modelset_project = get_arg("ai_modelset_project") or "bigdata_public_modelset"
    ai_parallel_partitions = get_int_arg("ai_parallel_partitions", 4)
    total_rpm_limit = get_int_arg("total_rpm_limit", 12000)
    request_timeout = get_int_arg("request_timeout", 300)
    ai_memory = get_arg("ai_memory", "8G") or ""
    ai_cu_quota_name = get_arg("ai_cu_quota_name")
    ai_gu_quota_name = get_arg("ai_gu_quota_name")
    oss_vl_access_key_id, oss_vl_access_key_secret = _resolve_oss_vl_ak_sk()
    vl_storage_options = (
        build_vl_oss_storage_options(
            role_arn=role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "build_vl_oss_storage_options" in globals()
        else None
    )

    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    parsed_relpath = f"{clip_prefix}/runs/{run_id}/parsed"
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"
    job3_relpath = f"{clip_prefix}/runs/{run_id}/job3"
    job4_relpath = f"{clip_prefix}/runs/{run_id}/job4"

    models = job4_config.get("models") or {}
    embed_model_names = [
        model_overrides["image"] or str((models.get("image") or {}).get("model") or ""),
        model_overrides["text"] or str((models.get("text") or {}).get("model") or ""),
        model_overrides["unified"] or str((models.get("unified") or {}).get("model") or ""),
    ]
    primary_embed_model = next((name for name in embed_model_names if name), "")

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.local_execution.enabled = False

    if primary_embed_model and "prepare_mf_ai_runtime" in globals():
        prepare_mf_ai_runtime(
            model_name=primary_embed_model,
            dpe_image=dpe_image,
            cu_quota_name=ai_cu_quota_name,
            gu_quota_name=ai_gu_quota_name,
        )
    else:
        mf_options.dag.settings = {
            "engine_order": ["DPE"],
            "unavailable_engines": ["MCSQL", "SPE"],
        }

    account = o.account  # type: ignore[name-defined]
    oss_mount_url = _oss_internal_url(cloud_region, oss_bucket, oss_mount_prefix)
    session = new_session(o)  # type: ignore[name-defined]

    job_row = {
        "clip_id": clip_id,
        "run_id": run_id,
        "parsed_relpath": parsed_relpath,
        "job2_payload_relpath": f"{job2_relpath}/job2_asr_payload.json",
        "job3_payload_relpath": f"{job3_relpath}/job3_mc_payload.json",
        "job4_relpath": job4_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    any_model = bool(primary_embed_model)

    try:
        print(f"Logview: {session.get_logview_address()}")
        print(f"Job4 storage_mode={storage_mode}")

        if any_model:
            ak_hint = (
                f"{oss_vl_access_key_id[:4]}...{oss_vl_access_key_id[-4:]}"
                if len(oss_vl_access_key_id) >= 8
                else "(empty)"
            )
            print(f"Job4 MaxFrame AI Function embed oss_ak_hint={ak_hint}")
            print(
                f"Job4 AI running_options={{total_rpm_limit={total_rpm_limit if total_rpm_limit > 0 else 'off'}, "
                f"request_timeout={request_timeout if request_timeout > 0 else 'off'}, "
                f"memory={ai_memory or 'off'}}}"
            )
            image_embed_model = embed_model_names[0]
            if (
                image_embed_model
                and "is_vl_embedding_model" in globals()
                and is_vl_embedding_model(image_embed_model)
                and not vl_storage_options
            ):
                raise ValueError(
                    "image_embed_model requires oss_vl_access_key_id/secret for OSS IMAGE_URL"
                )
            job3_payload_key = f"{job3_relpath}/job3_mc_payload.json"
            job2_payload_key = f"{job2_relpath}/job2_asr_payload.json"
            print(
                f"Job4 reading inputs from OSS: {job3_payload_key}, {job2_payload_key}"
            )
            labeled_frames, audio_segments, resolved_clip_id, resolved_run_id = (
                _load_job4_inputs_from_oss(
                    oss_bucket=oss_bucket,
                    cloud_region=cloud_region,
                    account=account,
                    job3_payload_key=job3_payload_key,
                    job2_payload_key=job2_payload_key,
                )
            )
            clip_id = resolved_clip_id or clip_id
            run_id = resolved_run_id or run_id

            embeddings = build_embeddings_with_ai(
                labeled_frames=labeled_frames,
                audio_segments=audio_segments,
                job4_config=job4_config,
                storage_mode=storage_mode,
                model_overrides=model_overrides,
                version_overrides=version_overrides,
                odps_entry=o,  # type: ignore[name-defined]
                modelset_project=ai_modelset_project,
                parallel_partitions=ai_parallel_partitions,
                cloud_region=cloud_region,
                oss_bucket=oss_bucket,
                parsed_relpath=parsed_relpath,
                vl_storage_options=vl_storage_options,
                total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                request_timeout=request_timeout if request_timeout > 0 else None,
                ai_memory=ai_memory.strip() if ai_memory.strip() else None,
            )

            row = _write_job4_artifacts_to_oss(
                clip_id=clip_id,
                run_id=run_id,
                job4_relpath=job4_relpath,
                labeled_frames=labeled_frames,
                audio_segments=audio_segments,
                embeddings=embeddings,
                storage_mode=storage_mode,
                oss_bucket=oss_bucket,
                cloud_region=cloud_region,
                account=account,
            )
        else:
            print("WARN: embed models empty; writing zero-vector stubs (model_version=none)")
            _job4_embed_row = _build_job4_embed_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                job4_config=job4_config,
                storage_mode=storage_mode,
                model_overrides=model_overrides,
                version_overrides=version_overrides,
                batch_size=batch_size,
            )
            result = input_df.apply(
                _job4_embed_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "storage_mode": "string",
                    "frame_count": "int64",
                    "audio_segment_count": "int64",
                    "embedding_count": "int64",
                    "payload_relpath": "string",
                    "embeddings_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch()
            if result.empty:
                raise RuntimeError("Job4 embed returned no rows")
            row = result.iloc[0]

        print(
            f"Job4 embed done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"mode={row['storage_mode']} frames={row['frame_count']} "
            f"audio_segments={row['audio_segment_count']} "
            f"embeddings={row['embedding_count']} payload={row['payload_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
        print("PIPELINE_DONE clip_id={clip_id} run_id={run_id}".format(
            clip_id=row["clip_id"], run_id=row["run_id"]
        ))
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
