# =============================================================================
# DataWorks PyODPS 3 节点：Job2-ASR（MaxFrame + DPE + MaxFrame AI Function）
#
# ★★★ DataWorks 必须粘贴 bundled 整文件，勿粘贴本文件 ★★★
#   python scripts/bundle_dataworks_node.py dataworks/job2_asr_node.py
#   → 粘贴 dataworks/bundled/job2_asr_node.py（约 1100+ 行，含 mf_ai_function 内联）
#
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 依赖：Job1 完成（parsed/ 含 audio.wav、chunks.jsonl、audio_info.json）
# 写 OSS：
#   clips/{clip_id}/runs/{run_id}/job2/asr_segments/{segment_id:04d}.wav
#   clips/{clip_id}/runs/{run_id}/job2/job2_asr_payload.json
#
# 工作流参数（AI OSS 读音频 URL，与 Job3 VL 相同）：
#   oss_vl_access_key_id= / oss_vl_access_key_secret=  （长期 OSS AK/SK，非 STS.*）
#   ※ oss_ram_role_arn 仅 DPE 挂载；input_audio OSS URL 须 AK/SK
#
# 编排：Job1 → Job2_asr（与 Job2_sample、Job3 可并行）；Job4 依赖本节点产物
#
# 节点参数（AI Function running_options，与 Job3/Job4 一致）
#   total_rpm_limit=12000
#   request_timeout=300
#   ai_memory=8G
# =============================================================================

from __future__ import annotations

import json
import os
import re
import wave
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

from pipeline_dispatch import exit_if_pipeline_idle, resolve_pipeline_context

_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}

DEFAULT_JOB2_ASR_CONFIG: dict[str, Any] = {
    "asr": {
        "provider": "maxframe_ai_function",
        "model": "",
        "model_version": "",
        "language": "zh-CN",
        "segment_sec": 30.0,
    }
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
        "resolve_asr_model",
        "ai_transcribe_segments",
        "extract_asr_plain_text",
        "build_vl_oss_storage_options",
    ):
        if hasattr(module, name):
            globals()[name] = getattr(module, name)


_load_mf_ai_function()


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


def get_float_arg(name: str, default: float) -> float:
    value = get_arg(name)
    return default if value is None else float(value)


def _resolve_oss_vl_ak_sk() -> tuple[str, str]:
    ak = get_arg("oss_vl_access_key_id") or get_arg("oss_access_key_id") or ""
    sk = get_arg("oss_vl_access_key_secret") or get_arg("oss_access_key_secret") or ""
    return ak, sk


def load_job2_config() -> dict[str, Any]:
    raw = get_arg("job2_config_json")
    if not raw:
        return DEFAULT_JOB2_ASR_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("job2_config_json must be a JSON object")
    return loaded


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    region_id = region.replace("_", "-")
    normalized = prefix.strip("/")
    if not normalized:
        return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/"
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{normalized}/"


def _oss_object_url(region: str, bucket: str, object_key: str) -> str:
    region_id = region.replace("_", "-")
    key = object_key.strip("/")
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{key}"


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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(json.loads(text))
    return rows


def build_asr_segments(
    chunks: list[dict[str, Any]],
    *,
    segment_sec: float,
) -> list[dict[str, Any]]:
    if not chunks:
        return []
    segment_ns = int(segment_sec * 1_000_000_000)
    sorted_chunks = sorted(chunks, key=lambda item: int(item["chunk_idx"]))
    segments: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []
    bucket_duration = 0

    def flush_bucket() -> None:
        nonlocal bucket, bucket_duration
        if not bucket:
            return
        start_ns = int(bucket[0]["timestamp_ns"])
        last = bucket[-1]
        end_ns = int(last["timestamp_ns"]) + int(last.get("duration_ns", 0))
        segments.append(
            {
                "segment_id": len(segments),
                "start_ns": start_ns,
                "end_ns": end_ns,
                "source_chunk_from": int(bucket[0]["chunk_idx"]),
                "source_chunk_to": int(bucket[-1]["chunk_idx"]),
            }
        )
        bucket = []
        bucket_duration = 0

    for chunk in sorted_chunks:
        duration_ns = int(chunk.get("duration_ns", 0))
        if bucket and bucket_duration + duration_ns > segment_ns:
            flush_bucket()
        bucket.append(chunk)
        bucket_duration += duration_ns
    flush_bucket()
    return segments


def _ns_to_frame_index(timestamp_ns: int, start_time_ns: int, sample_rate: int) -> int:
    if sample_rate <= 0:
        return 0
    delta_sec = max(0.0, (timestamp_ns - start_time_ns) / 1_000_000_000)
    return int(delta_sec * sample_rate)


def _extract_segment_wav(
    *,
    wav_path: Path,
    start_ns: int,
    end_ns: int,
    start_time_ns: int,
    sample_rate: int,
    channels: int,
    sample_width: int,
    output_path: Path,
) -> None:
    start_frame = _ns_to_frame_index(start_ns, start_time_ns, sample_rate)
    end_frame = max(start_frame + 1, _ns_to_frame_index(end_ns, start_time_ns, sample_rate))
    frame_count = end_frame - start_frame

    with wave.open(str(wav_path), "rb") as source_wav:
        if source_wav.getnchannels() != channels:
            channels = source_wav.getnchannels()
        if source_wav.getsampwidth() != sample_width:
            sample_width = source_wav.getsampwidth()
        if source_wav.getframerate() != sample_rate:
            sample_rate = source_wav.getframerate()
        source_wav.setpos(min(start_frame, source_wav.getnframes()))
        pcm = source_wav.readframes(frame_count)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as out_wav:
        out_wav.setnchannels(channels)
        out_wav.setsampwidth(sample_width)
        out_wav.setframerate(sample_rate)
        out_wav.writeframes(pcm)


def _build_job2_asr_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    asr_segment_sec: float,
):
    def _job2_asr_row(row):
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        job1_payload_path = parsed_root / "job1_mc_payload.json"
        if not job1_payload_path.is_file():
            raise FileNotFoundError(f"Job1 payload not found: {job1_payload_path}")

        job1_payload = _read_json(job1_payload_path)
        parse_result = job1_payload["parse_result"]
        audio_chunks = parse_result.get("audio_chunks") or []
        bag_stem = str(job1_payload.get("bag_stem") or row["bag_stem"])
        metadata = parse_result.get("metadata") or {}
        start_time_ns = int(metadata.get("start_time_ns") or 0)

        bag_output = parsed_root / bag_stem
        audio_dir = bag_output / "audio"
        wav_path = audio_dir / "audio.wav"
        chunks_path = audio_dir / "chunks.jsonl"
        audio_info_path = audio_dir / "audio_info.json"

        if chunks_path.is_file():
            chunk_rows = _read_jsonl(chunks_path)
        else:
            chunk_rows = audio_chunks

        sample_rate = 16000
        channels = 1
        sample_width = 2
        if audio_info_path.is_file():
            audio_info = _read_json(audio_info_path)
            sample_rate = int(audio_info.get("sample_rate") or sample_rate)
            channels = int(audio_info.get("channels") or channels)
            sample_width = 2

        segments = build_asr_segments(chunk_rows, segment_sec=asr_segment_sec)

        job2_root = Path(mount_path) / row["job2_relpath"]
        seg_dir = job2_root / "asr_segments"
        seg_dir.mkdir(parents=True, exist_ok=True)

        segment_records: list[dict[str, Any]] = []
        for segment in segments:
            seg_id = int(segment["segment_id"])
            audio_relpath = f"{row['job2_relpath']}/asr_segments/{seg_id:04d}.wav"
            segment_out = {
                **segment,
                "audio_relpath": audio_relpath,
                "wav_available": False,
            }
            if wav_path.is_file():
                _extract_segment_wav(
                    wav_path=wav_path,
                    start_ns=int(segment["start_ns"]),
                    end_ns=int(segment["end_ns"]),
                    start_time_ns=start_time_ns,
                    sample_rate=sample_rate,
                    channels=channels,
                    sample_width=sample_width,
                    output_path=seg_dir / f"{seg_id:04d}.wav",
                )
                segment_out["wav_available"] = True
            segment_records.append(segment_out)

        return {
            "segments_json": json.dumps(segment_records, ensure_ascii=False),
            "clip_id": str(job1_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job1_payload.get("run_id") or row["run_id"]),
            "bag_stem": bag_stem,
            "segment_count": len(segment_records),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job2_asr_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _transcribe_segments_ai_function(
    client: Any,
    segments: list[dict[str, Any]],
    *,
    model: str,
    model_version: str,
    language: str,
    oss_bucket: str,
    cloud_region: str,
    modelset_project: str,
    parallel_partitions: int,
    cu_quota_name: str | None,
    gu_quota_name: str | None,
    dpe_image: str | None,
    oss_storage_options: dict[str, str] | None = None,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    resolved_version = model_version or ("none" if not model else model)
    if not model:
        return [
            {
                "segment_id": int(segment["segment_id"]),
                "start_ns": int(segment["start_ns"]),
                "end_ns": int(segment["end_ns"]),
                "asr_text": "",
                "confidence": 0.0,
                "model_version": resolved_version,
                "language": language,
                "source_chunk_from": int(segment["source_chunk_from"]),
                "source_chunk_to": int(segment["source_chunk_to"]),
                "audio_relpath": str(segment.get("audio_relpath") or ""),
                "wav_available": bool(segment.get("wav_available")),
            }
            for segment in segments
        ]

    if "configure_mf_ai_engine" not in globals():
        raise RuntimeError(
            "mf_ai_function not loaded. DataWorks 请粘贴 "
            "dataworks/bundled/job2_asr_node.py（非 job2_asr_node.py）。"
            "本地生成: python scripts/bundle_dataworks_node.py dataworks/job2_asr_node.py"
        )

    transcribed = ai_transcribe_segments(
        segments,
        model,
        client,
        language=language,
        cloud_region=cloud_region,
        oss_bucket=oss_bucket,
        storage_options=oss_storage_options,
        modelset_project=modelset_project,
        parallel_partitions=parallel_partitions,
        total_rpm_limit=total_rpm_limit,
        request_timeout=request_timeout,
        ai_memory=ai_memory,
    )
    results: list[dict[str, Any]] = []
    for segment in transcribed:
        plain_text = (
            extract_asr_plain_text(segment.get("asr_text"))
            if "extract_asr_plain_text" in globals()
            else str(segment.get("asr_text") or "").strip()
        )
        confidence = float(segment.get("confidence") or 0.0)
        if plain_text and confidence <= 0.0:
            confidence = 1.0
        if not plain_text:
            confidence = 0.0
        results.append(
            {
                "segment_id": int(segment["segment_id"]),
                "start_ns": int(segment["start_ns"]),
                "end_ns": int(segment["end_ns"]),
                "asr_text": plain_text,
                "confidence": confidence,
                "model_version": resolved_version,
                "language": language,
                "source_chunk_from": int(segment["source_chunk_from"]),
                "source_chunk_to": int(segment["source_chunk_to"]),
                "audio_relpath": str(segment.get("audio_relpath") or ""),
                "wav_available": bool(segment.get("wav_available")),
            }
        )
    return results


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job2_asr"):
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

    job2_config = load_job2_config()
    asr_cfg = job2_config.get("asr") or DEFAULT_JOB2_ASR_CONFIG["asr"]
    asr_segment_sec = get_float_arg("asr_segment_sec", float(asr_cfg.get("segment_sec", 30.0)))
    asr_model = get_arg("asr_model") or str(asr_cfg.get("model") or "")
    asr_model_version = get_arg("asr_model_version") or str(asr_cfg.get("model_version") or "")
    asr_language = get_arg("asr_language") or str(asr_cfg.get("language") or "zh-CN")
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

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.local_execution.enabled = False

    if asr_model and "prepare_mf_ai_runtime" in globals():
        effective_asr = resolve_asr_model(asr_model) if "resolve_asr_model" in globals() else asr_model
        prepare_mf_ai_runtime(
            model_name=effective_asr,
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
        "bag_stem": "output",
        "parsed_relpath": parsed_relpath,
        "job2_relpath": job2_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    _job2_asr_row = _build_job2_asr_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=_storage_options(role_arn, account),
        asr_segment_sec=asr_segment_sec,
    )

    try:
        print(f"Logview: {session.get_logview_address()}")
        if not asr_model:
            print("WARN: asr_model empty; writing segments with empty asr_text (stub mode)")
        else:
            ak_hint = (
                f"{oss_vl_access_key_id[:4]}...{oss_vl_access_key_id[-4:]}"
                if len(oss_vl_access_key_id) >= 8
                else "(empty)"
            )
            print(
                f"Job2 ASR MaxFrame AI Function model={asr_model} oss_ak_hint={ak_hint} "
                f"running_options={{total_rpm_limit={total_rpm_limit if total_rpm_limit > 0 else 'off'}, "
                f"request_timeout={request_timeout if request_timeout > 0 else 'off'}, "
                f"memory={ai_memory or 'off'}}}"
            )
            if asr_model and not vl_storage_options:
                print(
                    "WARN: oss_vl_access_key_id/secret missing; ASR OSS audio URL may fail "
                    "(oss_ram_role_arn is mount-only)"
                )
        result_df = input_df.apply(
            _job2_asr_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "segments_json": "string",
                "clip_id": "string",
                "run_id": "string",
                "bag_stem": "string",
                "segment_count": "int64",
            },
            skip_infer=True,
        )
        row = result_df.execute().fetch().iloc[0]
        segments = json.loads(str(row["segments_json"]))

        audio_segments = _transcribe_segments_ai_function(
            o,  # type: ignore[name-defined]
            segments,
            model=asr_model,
            model_version=asr_model_version,
            language=asr_language,
            oss_bucket=oss_bucket,
            cloud_region=cloud_region,
            modelset_project=ai_modelset_project,
            parallel_partitions=ai_parallel_partitions,
            cu_quota_name=ai_cu_quota_name,
            gu_quota_name=ai_gu_quota_name,
            dpe_image=dpe_image,
            oss_storage_options=vl_storage_options,
            total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
            request_timeout=request_timeout if request_timeout > 0 else None,
            ai_memory=ai_memory.strip() if ai_memory.strip() else None,
        )

        payload = {
            "clip_id": str(row["clip_id"]),
            "run_id": str(row["run_id"]),
            "bag_stem": str(row["bag_stem"]),
            "asr_model": asr_model or "none",
            "asr_model_version": asr_model_version or ("none" if not asr_model else asr_model),
            "language": asr_language,
            "audio_segments": audio_segments,
            "processed_at": _utc_now_iso(),
        }

        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        write_df = md.DataFrame(
            pd.DataFrame(
                [
                    {
                        "payload_relpath": f"{job2_relpath}/job2_asr_payload.json",
                        "payload_json": payload_json,
                    }
                ]
            )
        )

        @with_running_options(engine="dpe", cpu=1, memory=2)
        @with_fs_mount(oss_mount_url, mount_path, storage_options=_storage_options(role_arn, account))
        def _write_asr_payload(row):
            path = Path(mount_path) / row["payload_relpath"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(row["payload_json"]), encoding="utf-8")
            return {"written": 1}

        write_df.apply(
            _write_asr_payload,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={"written": "int64"},
            skip_infer=True,
        ).execute()

        print(
            f"Job2 ASR done: clip_id={payload['clip_id']} run_id={payload['run_id']} "
            f"segments={len(audio_segments)} model={payload['asr_model']} "
            f"payload={job2_relpath}/job2_asr_payload.json"
        )
        print(f"NEXT_NODE_PARAM run_id={payload['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={payload['clip_id']}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
