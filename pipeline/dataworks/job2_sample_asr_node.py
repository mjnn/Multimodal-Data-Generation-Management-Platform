# =============================================================================
# DEPRECATED — 已拆分为 job2_sample_node.py + job2_asr_node.py
# 请勿再粘贴本文件到 DataWorks；见 dataworks/WORKFLOW.md「十节点编排」
# =============================================================================
# DataWorks PyODPS 3 节点：Job2-抽样+ASR（MaxFrame + DPE）— 已废弃
# 粘贴整文件到 PyODPS3 节点；Driver 需 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
# DPE worker：推荐 dpe_image=<MC 镜像名>（与 Job1 共用 docker/dpe-deps 即可）。
#
# 读 Job1 产物：clips/{clip_id}/runs/{run_id}/parsed/job1_mc_payload.json
# 写 Job2 产物：clips/{clip_id}/runs/{run_id}/job2/sample_manifest.jsonl
#              clips/{clip_id}/runs/{run_id}/job2/job2_mc_payload.json
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
#   job2_config_json=              # 可选，覆盖 config.yaml cloud.job2
#
# 节点参数
#   clip_id=sha256:...
#   run_id=<Job1 相同>
#   sample_policy=                 # 留空=active_sample_policy（默认 uniform）
#   asr_segment_sec=30             # ASR 分段时长（秒）
#   asr_model=                     # 留空=仅分段，asr_text 为空（待接 MC AI）
#   asr_model_version=
# =============================================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options

_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}

DEFAULT_JOB2_CONFIG: dict[str, Any] = {
    "active_sample_policy": "uniform",
    "sample_policies": [
        {
            "name": "uniform",
            "type": "uniform",
            "params": {"interval_sec": 1.0, "cameras": "all"},
        },
        {
            "name": "event_dense",
            "type": "event_window",
            "params": {
                "pre_sec": 2.0,
                "post_sec": 2.0,
                "baseline_policy": "uniform",
                "baseline_interval_sec": 1.0,
            },
        },
        {
            "name": "hybrid_default",
            "type": "hybrid",
            "params": {
                "uniform_interval_sec": 2.0,
                "event_pre_sec": 3.0,
                "event_post_sec": 3.0,
            },
        },
    ],
    "asr": {
        "provider": "maxcompute_ai",
        "model": "",
        "model_version": "",
        "language": "zh-CN",
        "segment_sec": 30.0,
    },
}


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
    for env_name, arg_name in (("OSS_BUCKET", "oss_bucket"), ("CLOUD_REGION", "cloud_region")):
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


def load_job2_config() -> dict[str, Any]:
    raw = get_arg("job2_config_json")
    if not raw:
        return DEFAULT_JOB2_CONFIG
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


def _find_policy(config: dict[str, Any], name: str) -> dict[str, Any]:
    for policy in config.get("sample_policies", []):
        if policy.get("name") == name:
            return policy
    raise ValueError(f"Unknown sample policy: {name}")


def _filter_cameras(frames: list[dict[str, Any]], cameras: Any) -> list[dict[str, Any]]:
    if cameras in (None, "all", "*"):
        return frames
    if isinstance(cameras, str):
        cameras = [item.strip() for item in cameras.split(",") if item.strip()]
    allowed = set(cameras)
    return [frame for frame in frames if frame["camera"] in allowed]


def _dedupe_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, int]] = set()
    unique: list[dict[str, Any]] = []
    for frame in sorted(frames, key=lambda item: (item["camera"], int(item["timestamp_ns"]))):
        key = (str(frame["camera"]), int(frame["frame_idx"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(frame)
    return unique


def sample_uniform(
    frames: list[dict[str, Any]],
    *,
    interval_sec: float,
    cameras: Any = "all",
) -> list[dict[str, Any]]:
    interval_ns = int(interval_sec * 1_000_000_000)
    filtered = _filter_cameras(frames, cameras)
    by_camera: dict[str, list[dict[str, Any]]] = {}
    for frame in filtered:
        by_camera.setdefault(str(frame["camera"]), []).append(frame)

    selected: list[dict[str, Any]] = []
    for camera_frames in by_camera.values():
        camera_frames.sort(key=lambda item: int(item["timestamp_ns"]))
        last_kept: int | None = None
        for frame in camera_frames:
            ts = int(frame["timestamp_ns"])
            if last_kept is None or ts - last_kept >= interval_ns:
                selected.append(frame)
                last_kept = ts
    return _dedupe_frames(selected)


def _frames_in_window(
    frames: list[dict[str, Any]],
    *,
    start_ns: int,
    end_ns: int,
    cameras: Any = "all",
) -> list[dict[str, Any]]:
    filtered = _filter_cameras(frames, cameras)
    return [
        frame
        for frame in filtered
        if start_ns <= int(frame["timestamp_ns"]) <= end_ns
    ]


def sample_event_window(
    frames: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    pre_sec: float,
    post_sec: float,
    cameras: Any = "all",
    baseline_policy: str | None = None,
    baseline_interval_sec: float = 1.0,
    all_policies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pre_ns = int(pre_sec * 1_000_000_000)
    post_ns = int(post_sec * 1_000_000_000)
    selected: list[dict[str, Any]] = []
    for event in events:
        center = int(event["timestamp_ns"])
        selected.extend(
            _frames_in_window(
                frames,
                start_ns=center - pre_ns,
                end_ns=center + post_ns,
                cameras=cameras,
            )
        )
    if baseline_policy and all_policies:
        baseline = _find_policy({"sample_policies": all_policies}, baseline_policy)
        if baseline.get("type") == "uniform":
            params = baseline.get("params", {})
            selected.extend(
                sample_uniform(
                    frames,
                    interval_sec=float(params.get("baseline_interval_sec", baseline_interval_sec)),
                    cameras=params.get("cameras", cameras),
                )
            )
    return _dedupe_frames(selected)


def sample_hybrid(
    frames: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    uniform_interval_sec: float,
    event_pre_sec: float,
    event_post_sec: float,
    cameras: Any = "all",
) -> list[dict[str, Any]]:
    uniform_part = sample_uniform(
        frames,
        interval_sec=uniform_interval_sec,
        cameras=cameras,
    )
    event_part = sample_event_window(
        frames,
        events,
        pre_sec=event_pre_sec,
        post_sec=event_post_sec,
        cameras=cameras,
    )
    return _dedupe_frames(uniform_part + event_part)


def apply_sample_policy(
    policy: dict[str, Any],
    *,
    frames: list[dict[str, Any]],
    events: list[dict[str, Any]],
    all_policies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    policy_type = policy.get("type")
    params = policy.get("params") or {}
    cameras = params.get("cameras", "all")

    if policy_type == "uniform":
        return sample_uniform(
            frames,
            interval_sec=float(params.get("interval_sec", 1.0)),
            cameras=cameras,
        )
    if policy_type == "event_window":
        return sample_event_window(
            frames,
            events,
            pre_sec=float(params.get("pre_sec", 2.0)),
            post_sec=float(params.get("post_sec", 2.0)),
            cameras=cameras,
            baseline_policy=params.get("baseline_policy"),
            baseline_interval_sec=float(params.get("baseline_interval_sec", 1.0)),
            all_policies=all_policies,
        )
    if policy_type == "hybrid":
        return sample_hybrid(
            frames,
            events,
            uniform_interval_sec=float(params.get("uniform_interval_sec", 2.0)),
            event_pre_sec=float(params.get("event_pre_sec", 3.0)),
            event_post_sec=float(params.get("event_post_sec", 3.0)),
            cameras=cameras,
        )
    raise ValueError(f"Unsupported sample policy type: {policy_type}")


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


def run_asr_stub(
    segments: list[dict[str, Any]],
    *,
    model: str,
    model_version: str,
    language: str,
    wav_path: Path | None,
) -> list[dict[str, Any]]:
    """ASR 占位：model 未配置时仅输出分段元数据；后续可接 MC AI Function。"""
    resolved_version = model_version or ("none" if not model else model)
    results: list[dict[str, Any]] = []
    for segment in segments:
        asr_text = ""
        confidence = 0.0
        if model:
            # MC AI 接入点：当前版本保留分段结构，文本留空并记录模型名供下游排查。
            asr_text = ""
            confidence = 0.0
        results.append(
            {
                **segment,
                "asr_text": asr_text,
                "confidence": confidence,
                "model_version": resolved_version,
                "language": language,
                "wav_available": bool(wav_path and wav_path.is_file()),
            }
        )
    return results


def _build_job2_process_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job2_config: dict[str, Any],
    sample_policy_name: str,
    asr_segment_sec: float,
    asr_model: str,
    asr_model_version: str,
):
    def _job2_process_row(row):
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        job1_payload_path = parsed_root / "job1_mc_payload.json"
        if not job1_payload_path.is_file():
            raise FileNotFoundError(f"Job1 payload not found: {job1_payload_path}")

        job1_payload = _read_json(job1_payload_path)
        parse_result = job1_payload["parse_result"]
        frames = parse_result.get("frames") or []
        events = parse_result.get("events") or []
        audio_chunks = parse_result.get("audio_chunks") or []
        bag_stem = str(job1_payload.get("bag_stem") or row["bag_stem"])

        all_policies = job2_config.get("sample_policies") or DEFAULT_JOB2_CONFIG["sample_policies"]
        policy = _find_policy({"sample_policies": all_policies}, sample_policy_name)
        sampled_frames = apply_sample_policy(
            policy,
            frames=frames,
            events=events,
            all_policies=all_policies,
        )

        bag_output = parsed_root / bag_stem
        audio_dir = bag_output / "audio"
        wav_path = audio_dir / "audio.wav"
        chunks_path = audio_dir / "chunks.jsonl"
        if chunks_path.is_file():
            chunk_rows = _read_jsonl(chunks_path)
        else:
            chunk_rows = audio_chunks

        asr_cfg = job2_config.get("asr") or DEFAULT_JOB2_CONFIG["asr"]
        segments = build_asr_segments(chunk_rows, segment_sec=asr_segment_sec)
        audio_segments = run_asr_stub(
            segments,
            model=asr_model or str(asr_cfg.get("model") or ""),
            model_version=asr_model_version or str(asr_cfg.get("model_version") or ""),
            language=str(asr_cfg.get("language") or "zh-CN"),
            wav_path=wav_path if wav_path.is_file() else None,
        )

        job2_root = Path(mount_path) / row["job2_relpath"]
        job2_root.mkdir(parents=True, exist_ok=True)

        manifest_rows = []
        for frame in sampled_frames:
            image_relpath = f"{bag_stem}/{frame['image_path']}"
            manifest_rows.append(
                {
                    "camera": frame["camera"],
                    "frame_idx": int(frame["frame_idx"]),
                    "timestamp_ns": int(frame["timestamp_ns"]),
                    "topic": frame.get("topic"),
                    "image_relpath": image_relpath,
                    "sample_policy": sample_policy_name,
                }
            )

        manifest_path = job2_root / "sample_manifest.jsonl"
        with manifest_path.open("w", encoding="utf-8") as manifest_file:
            for item in manifest_rows:
                manifest_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": str(job1_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job1_payload.get("run_id") or row["run_id"]),
            "bag_stem": bag_stem,
            "sample_policy_name": sample_policy_name,
            "sample_policy_params": policy.get("params") or {},
            "sampled_frames": manifest_rows,
            "audio_segments": [
                {
                    "segment_id": int(item["segment_id"]),
                    "start_ns": int(item["start_ns"]),
                    "end_ns": int(item["end_ns"]),
                    "asr_text": item.get("asr_text", ""),
                    "confidence": float(item.get("confidence", 0.0)),
                    "model_version": item.get("model_version", "none"),
                    "source_chunk_from": int(item["source_chunk_from"]),
                    "source_chunk_to": int(item["source_chunk_to"]),
                }
                for item in audio_segments
            ],
            "processed_at": _utc_now_iso(),
        }
        payload_path = job2_root / "job2_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": payload["clip_id"],
            "run_id": payload["run_id"],
            "sample_policy_name": sample_policy_name,
            "sampled_frame_count": len(manifest_rows),
            "audio_segment_count": len(audio_segments),
            "payload_relpath": f"{row['job2_relpath']}/job2_mc_payload.json",
            "manifest_relpath": f"{row['job2_relpath']}/sample_manifest.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job2_process_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def main() -> None:
    raise RuntimeError(
        "DEPRECATED: job2_sample_asr_node.py 已废弃。"
        "请改用 dataworks/job2_sample_node.py 与 dataworks/job2_asr_node.py，"
        "编排见 dataworks/WORKFLOW.md"
    )


def _deprecated_main() -> None:
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")

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
    sample_policy_name = get_arg("sample_policy") or str(
        job2_config.get("active_sample_policy") or "uniform"
    )
    asr_cfg = job2_config.get("asr") or DEFAULT_JOB2_CONFIG["asr"]
    asr_segment_sec = get_float_arg("asr_segment_sec", float(asr_cfg.get("segment_sec", 30.0)))
    asr_model = get_arg("asr_model") or str(asr_cfg.get("model") or "")
    asr_model_version = get_arg("asr_model_version") or str(asr_cfg.get("model_version") or "")

    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    parsed_relpath = f"{clip_prefix}/runs/{run_id}/parsed"
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False

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

    _job2_process_row = _build_job2_process_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=_storage_options(role_arn, account),
        job2_config=job2_config,
        sample_policy_name=sample_policy_name,
        asr_segment_sec=asr_segment_sec,
        asr_model=asr_model,
        asr_model_version=asr_model_version,
    )

    try:
        print(f"Logview: {session.get_logview_address()}")
        if not asr_model:
            print("WARN: asr_model empty; writing audio segments with empty asr_text (stub mode)")
        result_df = input_df.apply(
            _job2_process_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "clip_id": "string",
                "run_id": "string",
                "sample_policy_name": "string",
                "sampled_frame_count": "int64",
                "audio_segment_count": "int64",
                "payload_relpath": "string",
                "manifest_relpath": "string",
            },
            skip_infer=True,
        )
        result = result_df.execute().fetch()
        if result.empty:
            raise RuntimeError("Job2 sample+ASR returned no rows")
        row = result.iloc[0]
        print(
            f"Job2 sample+ASR done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"policy={row['sample_policy_name']} "
            f"sampled_frames={row['sampled_frame_count']} "
            f"audio_segments={row['audio_segment_count']} "
            f"payload={row['payload_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
