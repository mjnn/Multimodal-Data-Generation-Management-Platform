# =============================================================================
# DataWorks PyODPS 3 节点：Job1-解析Rosbag（节点 1/2）
# 粘贴整文件到 PyODPS3 节点；Driver 需 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
# DPE worker：推荐工作流参数 dpe_image=<MC 镜像名>（docker/dpe-deps 构建并登记）。
# 未配 dpe_image 时回退 @with_python_requirements 在线装 rosbags（较慢）。
#
# bag 与 Job0 同路径（dim_clip.bag_oss_key 或节点参数 bag_oss_key），不拷贝大文件。
# 解析产物写入 clips/{clip_id}/runs/{run_id}/parsed/（与 bag 路径分离）。
#
# ---------------------------------------------------------------------------
# 工作流参数（key=value）
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   oss_ram_role_arn=              # 推荐；留空则用 o.account AK/SK
#   oss_mount_prefix=              # 空=挂载整桶根目录（推荐，配合 bag_oss_key）
#   oss_prefix_template=clips/{clip_id}/
#   oss_runs_subdir=runs/{run_id}/
#   dpe_cpu=4
#   dpe_memory_gb=16
#   dpe_mount_path=/mnt/oss
#   dpe_image=sq_maxframe              # MC 控制台登记的镜像名（默认 sq_maxframe）
#   pipeline_config_json=
#
#   clip_id= / run_id= 留空 → 读 job0_dispatch 写入的 pipeline/dispatch/latest.json
#   python scripts/bundle_pipeline_dispatch.py dataworks/job1_parse_node.py
#   clip_id=sha256:...             # 必填，来自 Job0 DISCOVERED_JSON
#   bag_oss_key=rosbags/.../x.bag  # 必填（或由 Job0 写入 dim_clip 后留空自动查 MC）
#   run_id=
#   clip_dir_name=2026-06-05_...
# =============================================================================

from __future__ import annotations

import hashlib
import json
import re
import wave
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_python_requirements, with_running_options

from pipeline_dispatch import exit_if_pipeline_idle, resolve_pipeline_context


DEFAULT_PIPELINE_CONFIG: dict[str, Any] = {
    "cloud": {
        "clip_id": {
            "algorithm": "sha256",
            "format": "sha256:{hex}",
        }
    },
    "bag": {
        "ros1_glob": "*.bag",
        "ros2_metadata_file": "metadata.yaml",
    },
    "output": {
        "bag_output_dir": "{bag_stem}",
        "images_subdir": "images",
        "audio_subdir": "audio",
        "labels_subdir": "labels",
        "metadata_file": "metadata.json",
        "audio_file": "audio.wav",
        "audio_chunks_file": "chunks.jsonl",
        "audio_info_file": "audio_info.json",
        "event_labels_file": "event_labels.jsonl",
        "image_filename": "{index:06d}_{timestamp}.{ext}",
    },
    "topics": {
        "compressed_image_suffix": "/CompressedImage",
        "audio_data_suffix": "/AudioData",
        "audio_info_suffix": "/AudioInfo",
        "string_suffix": "/String",
        "camera_pattern": "/camera(\\d+)/",
        "camera_name_template": "camera{index}",
    },
    "image": {
        "jpeg_aliases": ["jpeg", "jpg"],
        "default_extension": "bin",
    },
    "audio": {
        "sample_formats": {
            "S8": 1,
            "S16LE": 2,
            "S16BE": 2,
            "S24LE": 3,
            "S24BE": 3,
            "S32LE": 4,
            "S32BE": 4,
            "F32LE": 4,
            "F32BE": 4,
        }
    },
    "json": {
        "indent": 2,
        "ensure_ascii": False,
    },
}


def get_arg(name: str, default: str | None = None) -> str | None:
    try:
        value = args.get(name)  # type: ignore[name-defined]
    except NameError:
        value = None
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def _apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


def _build_job1_parse_udf(
    *,
    use_python_pack: bool,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    pipeline_config: dict[str, Any],
):
    def _job1_parse_row(row):
        bag_path = Path(mount_path) / row["bag_oss_key"]
        output_dir = Path(mount_path) / row["output_relpath"]
        output_dir.mkdir(parents=True, exist_ok=True)

        parse_result = parse_bag(bag_path, output_dir, pipeline_config)
        content_hash = _compute_content_hash_from_bag(bag_path)
        resolved_clip_id = _format_clip_id(content_hash, pipeline_config)
        if resolved_clip_id != row["clip_id"]:
            raise ValueError(
                f"clip_id mismatch: node_param={row['clip_id']} bag_hash={resolved_clip_id}"
            )
        bag_stem = bag_path.stem
        bag_output_relpath = f"{row['output_relpath']}/{pipeline_config['output']['bag_output_dir'].format(bag_stem=bag_stem)}"

        frames_for_mc = []
        for frame in parse_result["frames"]:
            frames_for_mc.append(
                {
                    **frame,
                    "image_path": f"{bag_output_relpath}/{frame['image_path']}",
                }
            )

        payload = {
            "clip_id": resolved_clip_id,
            "clip_dir_name": row["clip_dir_name"],
            "content_hash": content_hash,
            "bag_oss_key": row["bag_oss_key"],
            "run_id": row["run_id"],
            "bag_stem": bag_stem,
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "parse_result": {
                **parse_result,
                "frames": frames_for_mc,
            },
        }
        payload_path = output_dir / "job1_mc_payload.json"
        payload_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "clip_id": resolved_clip_id,
            "run_id": row["run_id"],
            "bag_stem": bag_stem,
            "payload_relpath": f"{row['output_relpath']}/job1_mc_payload.json",
            "frame_count": len(frames_for_mc),
            "audio_chunk_count": len(parse_result["audio_chunks"]),
        }

    wrapped = _job1_parse_row
    if use_python_pack:
        wrapped = with_python_requirements("rosbags>=0.10.0")(wrapped)
    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(wrapped)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def load_pipeline_config() -> dict[str, Any]:
    raw = get_arg("pipeline_config_json")
    if not raw:
        return DEFAULT_PIPELINE_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("pipeline_config_json must be a JSON object")
    return loaded


def _json_dump(data: Any, path: Path, json_config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            data,
            indent=json_config.get("indent", 2),
            ensure_ascii=json_config.get("ensure_ascii", False),
        ),
        encoding="utf-8",
    )


def _camera_dir_name(topic: str, topics_config: dict[str, Any]) -> str:
    pattern = topics_config["camera_pattern"]
    template = topics_config["camera_name_template"]
    match = re.search(pattern, topic)
    if match:
        return template.format(index=match.group(1))
    return topic.strip("/").replace("/", "_") or "unknown"


def _write_wav(path: Path, pcm_data: bytes, channels: int, sample_rate: int, sample_width: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)


def _parse_sample_format(sample_format: str, audio_config: dict[str, Any]) -> int:
    mapping = audio_config["sample_formats"]
    if sample_format not in mapping:
        raise ValueError(f"Unsupported audio sample format: {sample_format}")
    return int(mapping[sample_format])


def _image_extension(image_format: str, image_config: dict[str, Any]) -> str:
    normalized = image_format.lower()
    if normalized in image_config["jpeg_aliases"]:
        return "jpg"
    return normalized or image_config["default_extension"]


def _message_modality(msgtype: str, topics_config: dict[str, Any]) -> str:
    if msgtype.endswith(topics_config["compressed_image_suffix"]):
        return "frame"
    if msgtype.endswith(topics_config["audio_data_suffix"]):
        return "audio"
    if msgtype.endswith(topics_config["audio_info_suffix"]):
        return "metadata"
    if msgtype.endswith(topics_config["string_suffix"]):
        return "event"
    return "other"


def _build_audio_chunk_records(
    audio_chunks: list[tuple[int, bytes]],
    *,
    sample_rate: int,
    sample_width: int,
    channels: int,
) -> list[dict[str, Any]]:
    sorted_chunks = sorted(audio_chunks, key=lambda item: item[0])
    bytes_per_sample = sample_width * channels
    records: list[dict[str, Any]] = []
    byte_offset = 0
    for chunk_idx, (timestamp_ns, pcm_data) in enumerate(sorted_chunks):
        pcm_bytes = len(pcm_data)
        sample_count = pcm_bytes // bytes_per_sample if bytes_per_sample else 0
        duration_ns = int(sample_count / sample_rate * 1_000_000_000) if sample_rate else 0
        records.append(
            {
                "chunk_idx": chunk_idx,
                "timestamp_ns": timestamp_ns,
                "byte_offset": byte_offset,
                "byte_length": pcm_bytes,
                "sample_count": sample_count,
                "duration_ns": duration_ns,
                "pcm_bytes": pcm_bytes,
            }
        )
        byte_offset += pcm_bytes
    return records


def _write_audio_chunks_jsonl(
    chunk_records: list[dict[str, Any]],
    path: Path,
    json_config: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as chunks_file:
        for record in chunk_records:
            chunks_file.write(
                json.dumps(record, ensure_ascii=json_config.get("ensure_ascii", False)) + "\n"
            )


def _hash_file(hasher: hashlib._Hash, path: Path) -> None:
    hasher.update(path.name.encode("utf-8"))
    with path.open("rb") as bag_file:
        while True:
            block = bag_file.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)


def _compute_content_hash_from_bag(bag_path: Path) -> str:
    hasher = hashlib.sha256()
    _hash_file(hasher, bag_path)
    return hasher.hexdigest()


def _format_clip_id(content_hash: str, config: dict[str, Any]) -> str:
    clip_id_config = config["cloud"]["clip_id"]
    return str(clip_id_config["format"]).format(hex=content_hash)


def parse_bag(bag_path: Path, output_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    from rosbags.highlevel import AnyReader

    output_config = config["output"]
    topics_config = config["topics"]
    image_config = config["image"]
    audio_config = config["audio"]
    json_config = config["json"]

    bag_output = output_dir / output_config["bag_output_dir"].format(bag_stem=bag_path.stem)
    bag_output.mkdir(parents=True, exist_ok=True)

    topic_stats: dict[str, dict[str, Any]] = {}
    audio_chunks: list[tuple[int, bytes]] = []
    audio_info: dict[str, Any] | None = None
    event_labels: list[dict[str, Any]] = []
    image_counters: defaultdict[str, int] = defaultdict(int)
    timeline_messages: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    timeline_events: list[dict[str, Any]] = []
    topic_sequence: defaultdict[str, int] = defaultdict(int)

    with AnyReader([bag_path]) as reader:
        for topic, info in reader.topics.items():
            topic_stats[topic] = {"msgtype": info.msgtype, "count": 0}

        for connection, timestamp, rawdata in reader.messages():
            topic = connection.topic
            topic_stats[topic]["count"] += 1
            msg = reader.deserialize(rawdata, connection.msgtype)
            msgtype = connection.msgtype
            modality = _message_modality(msgtype, topics_config)
            sequence_idx = topic_sequence[topic]
            topic_sequence[topic] += 1
            timeline_messages.append(
                {
                    "topic": topic,
                    "msgtype": msgtype,
                    "modality": modality,
                    "timestamp_ns": timestamp,
                    "sequence_idx": sequence_idx,
                }
            )

            if msgtype.endswith(topics_config["compressed_image_suffix"]):
                camera_name = _camera_dir_name(topic, topics_config)
                image_counters[camera_name] += 1
                frame_idx = image_counters[camera_name]
                image_dir = bag_output / output_config["images_subdir"] / camera_name
                image_dir.mkdir(parents=True, exist_ok=True)
                ext = _image_extension(str(msg.format), image_config)
                image_name = output_config["image_filename"].format(
                    index=frame_idx,
                    timestamp=timestamp,
                    ext=ext,
                )
                image_path = image_dir / image_name
                image_path.write_bytes(bytes(msg.data))
                frames.append(
                    {
                        "camera": camera_name,
                        "frame_idx": frame_idx,
                        "timestamp_ns": timestamp,
                        "topic": topic,
                        "image_path": str(image_path.relative_to(bag_output)),
                    }
                )
            elif msgtype.endswith(topics_config["audio_data_suffix"]):
                audio_chunks.append((timestamp, bytes(msg.data)))
            elif msgtype.endswith(topics_config["audio_info_suffix"]):
                audio_info = {
                    "channels": int(msg.channels),
                    "sample_rate": int(msg.sample_rate),
                    "sample_format": str(msg.sample_format),
                    "bitrate": int(msg.bitrate),
                    "coding_format": str(msg.coding_format),
                }
            elif msgtype.endswith(topics_config["string_suffix"]):
                event_item = {
                    "timestamp_ns": timestamp,
                    "timestamp_sec": timestamp / 1e9,
                    "data": str(msg.data),
                }
                event_labels.append(event_item)
                timeline_events.append(
                    {
                        "timestamp_ns": timestamp,
                        "event_data": str(msg.data),
                    }
                )

        metadata = {
            "bag_file": bag_path.name,
            "duration_ns": reader.duration,
            "duration_sec": reader.duration / 1e9,
            "start_time_ns": reader.start_time,
            "end_time_ns": reader.end_time,
            "message_count": reader.message_count,
            "topics": {
                topic: {"msgtype": stats["msgtype"], "count": stats["count"]}
                for topic, stats in topic_stats.items()
            },
        }

    _json_dump(metadata, bag_output / output_config["metadata_file"], json_config)

    audio_chunk_records: list[dict[str, Any]] = []
    if audio_info is not None and audio_chunks:
        sample_width = _parse_sample_format(audio_info["sample_format"], audio_config)
        audio_chunk_records = _build_audio_chunk_records(
            audio_chunks,
            sample_rate=audio_info["sample_rate"],
            sample_width=sample_width,
            channels=audio_info["channels"],
        )
        sorted_chunks = sorted(audio_chunks, key=lambda item: item[0])
        pcm_data = b"".join(chunk for _, chunk in sorted_chunks)
        audio_dir = bag_output / output_config["audio_subdir"]
        _write_wav(
            audio_dir / output_config["audio_file"],
            pcm_data,
            channels=audio_info["channels"],
            sample_rate=audio_info["sample_rate"],
            sample_width=sample_width,
        )
        _write_audio_chunks_jsonl(
            audio_chunk_records,
            audio_dir / output_config["audio_chunks_file"],
            json_config,
        )
        audio_meta = {
            **audio_info,
            "chunk_count": len(audio_chunk_records),
            "pcm_bytes": len(pcm_data),
            "duration_sec": len(pcm_data)
            / (audio_info["sample_rate"] * sample_width * audio_info["channels"]),
        }
        _json_dump(audio_meta, audio_dir / output_config["audio_info_file"], json_config)

    if event_labels:
        labels_dir = bag_output / output_config["labels_subdir"]
        labels_dir.mkdir(parents=True, exist_ok=True)
        labels_path = labels_dir / output_config["event_labels_file"]
        with labels_path.open("w", encoding="utf-8") as labels_file:
            for item in event_labels:
                labels_file.write(
                    json.dumps(item, ensure_ascii=json_config.get("ensure_ascii", False)) + "\n"
                )

    return {
        "metadata": metadata,
        "timeline_messages": timeline_messages,
        "frames": frames,
        "audio_chunks": audio_chunk_records,
        "events": timeline_events,
    }


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


def _lookup_bag_oss_key(client: Any, table_name: str, clip_id: str) -> str | None:
    safe_clip_id = clip_id.replace("'", "''")
    sql = f"SELECT bag_oss_key FROM {table_name} WHERE clip_id = '{safe_clip_id}' LIMIT 1;"
    with client.execute_sql(sql).open_reader() as reader:
        for record in reader:
            key = record[0]
            return str(key) if key else None
    return None


def _resolve_bag_oss_key(
    *,
    clip_id: str,
    table_prefix: str,
    node_value: str | None,
) -> str:
    if node_value:
        return node_value
    table_name = f"{table_prefix}dim_clip"
    looked_up = _lookup_bag_oss_key(o, table_name, clip_id)  # type: ignore[name-defined]
    if looked_up:
        return looked_up
    raise ValueError(
        f"bag_oss_key not provided and not found in {table_name} for clip_id={clip_id}"
    )


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job1_parse"):
        return

    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]
    clip_dir_name = pipeline_ctx.get("clip_dir_name") or get_arg("clip_dir_name") or ""
    if not clip_dir_name:
        raise ValueError("clip_dir_name required (dim_clip or node param)")

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai")
    role_arn = get_arg("oss_ram_role_arn")
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    oss_mount_prefix = get_arg("oss_mount_prefix", "") or ""
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")
    runs_subdir = get_arg("oss_runs_subdir", "runs/{run_id}/").format(run_id=run_id).strip("/")
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_cpu = get_int_arg("dpe_cpu", 4)
    dpe_memory = get_int_arg("dpe_memory_gb", 16)
    pipeline_config = load_pipeline_config()

    bag_oss_key = _resolve_bag_oss_key(
        clip_id=clip_id,
        table_prefix=table_prefix,
        node_value=get_arg("bag_oss_key") or pipeline_ctx.get("bag_oss_key"),
    )
    oss_mount_url = _oss_internal_url(cloud_region, oss_bucket, oss_mount_prefix)
    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    output_relpath = f"{clip_prefix}/{runs_subdir}/parsed"

    dpe_image = get_arg("dpe_image", "sq_maxframe")
    _apply_dpe_runtime_settings(dpe_image)

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False

    if dpe_image:
        print(f"Job1 DPE image: {dpe_image}")
    else:
        print(
            "WARN: dpe_image empty; falling back to @with_python_requirements(rosbags). "
            "For production, build docker/dpe-deps and set dpe_image to MC registered name."
        )

    session = new_session(o)  # type: ignore[name-defined]
    job_row = {
        "clip_id": clip_id,
        "run_id": run_id,
        "clip_dir_name": clip_dir_name,
        "bag_oss_key": bag_oss_key,
        "output_relpath": output_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    _job1_parse_row = _build_job1_parse_udf(
        use_python_pack=not bool(dpe_image),
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=_storage_options(role_arn, account),
        pipeline_config=pipeline_config,
    )

    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            _job1_parse_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "clip_id": "string",
                "run_id": "string",
                "bag_stem": "string",
                "payload_relpath": "string",
                "frame_count": "int64",
                "audio_chunk_count": "int64",
            },
            skip_infer=True,
        )
        result = result_df.execute().fetch()
        if result.empty:
            raise RuntimeError("Job1 parse returned no rows")
        row = result.iloc[0]
        print(
            f"Job1 parse done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"frames={row['frame_count']} audio_chunks={row['audio_chunk_count']} "
            f"payload={row['payload_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
        print(f"NEXT_NODE_PARAM bag_oss_key={bag_oss_key}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
