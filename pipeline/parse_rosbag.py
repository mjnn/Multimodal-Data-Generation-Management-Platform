#!/usr/bin/env python3
"""Parse ROS bag files from clip directories and export structured parsed data."""

from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (_REPO_ROOT / "shared", _REPO_ROOT / "pipeline"):
    _text = str(_entry)
    if _text not in sys.path:
        sys.path.insert(0, _text)

import yaml
from rosbags.highlevel import AnyReader

from clip_id import compute_clip_id, compute_content_hash, write_rosbag_manifest
from parse_records_db import get_topic_column_specs, init_db, sync_clip_records, upsert_parse_record
from pipeline_status_db import (
    get_pipeline_config,
    init_pipeline_db,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
)
from timeline_db import get_timeline_config, write_job1_timeline

LOCAL_RUN_ID = "local"


@dataclass
class BagParseResult:
    metadata: dict[str, Any]
    timeline_messages: list[dict[str, Any]]
    frames: list[dict[str, Any]]
    audio_chunks: list[dict[str, Any]]
    events: list[dict[str, Any]]


@dataclass
class TopicStats:
    msgtype: str
    count: int = 0


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    if not isinstance(config, dict):
        raise ValueError(f"Invalid config file: {config_path}")

    return config


def resolve_path(base_dir: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def json_dump(data: Any, path: Path, json_config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            data,
            indent=json_config.get("indent", 2),
            ensure_ascii=json_config.get("ensure_ascii", False),
        ),
        encoding="utf-8",
    )


def sanitize_topic_name(topic: str) -> str:
    name = topic.strip("/").replace("/", "_")
    return re.sub(r"[^\w.-]+", "_", name) or "unknown"


def camera_dir_name(topic: str, topics_config: dict[str, Any]) -> str:
    pattern = topics_config["camera_pattern"]
    template = topics_config["camera_name_template"]
    match = re.search(pattern, topic)
    if match:
        return template.format(index=match.group(1))
    return sanitize_topic_name(topic)


def write_wav(path: Path, pcm_data: bytes, channels: int, sample_rate: int, sample_width: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)


def parse_sample_format(sample_format: str, audio_config: dict[str, Any]) -> int:
    mapping = audio_config["sample_formats"]
    if sample_format not in mapping:
        raise ValueError(f"Unsupported audio sample format: {sample_format}")
    return int(mapping[sample_format])


def image_extension(image_format: str, image_config: dict[str, Any]) -> str:
    normalized = image_format.lower()
    if normalized in image_config["jpeg_aliases"]:
        return "jpg"
    return normalized or image_config["default_extension"]


def message_modality(msgtype: str, topics_config: dict[str, Any]) -> str:
    if msgtype.endswith(topics_config["compressed_image_suffix"]):
        return "frame"
    if msgtype.endswith(topics_config["audio_data_suffix"]):
        return "audio"
    if msgtype.endswith(topics_config["audio_info_suffix"]):
        return "metadata"
    if msgtype.endswith(topics_config["string_suffix"]):
        return "event"
    return "other"


def build_audio_chunk_records(
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


def write_audio_chunks_jsonl(
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


def discover_bags(input_dir: Path, bag_config: dict[str, Any]) -> list[Path]:
    bags = sorted(input_dir.glob(bag_config["ros1_glob"]))
    if bags:
        return bags

    metadata_name = bag_config["ros2_metadata_file"]
    return [
        path
        for path in sorted(input_dir.iterdir())
        if path.is_dir() and (path / metadata_name).exists()
    ]


def parse_bag(bag_path: Path, output_dir: Path, config: dict[str, Any]) -> BagParseResult:
    output_config = config["output"]
    topics_config = config["topics"]
    image_config = config["image"]
    audio_config = config["audio"]
    json_config = config["json"]

    bag_output = output_dir / output_config["bag_output_dir"].format(bag_stem=bag_path.stem)
    bag_output.mkdir(parents=True, exist_ok=True)

    topic_stats: dict[str, TopicStats] = {}
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
            topic_stats[topic] = TopicStats(msgtype=info.msgtype)

        for connection, timestamp, rawdata in reader.messages():
            topic = connection.topic
            topic_stats[topic].count += 1
            msg = reader.deserialize(rawdata, connection.msgtype)
            msgtype = connection.msgtype
            modality = message_modality(msgtype, topics_config)
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
                camera_name = camera_dir_name(topic, topics_config)
                image_counters[camera_name] += 1
                frame_idx = image_counters[camera_name]
                image_dir = bag_output / output_config["images_subdir"] / camera_name
                image_dir.mkdir(parents=True, exist_ok=True)

                ext = image_extension(str(msg.format), image_config)
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
                topic: {"msgtype": stats.msgtype, "count": stats.count}
                for topic, stats in topic_stats.items()
            },
        }

    json_dump(metadata, bag_output / output_config["metadata_file"], json_config)

    audio_chunk_records: list[dict[str, Any]] = []
    if audio_info is not None and audio_chunks:
        sample_width = parse_sample_format(audio_info["sample_format"], audio_config)
        audio_chunk_records = build_audio_chunk_records(
            audio_chunks,
            sample_rate=audio_info["sample_rate"],
            sample_width=sample_width,
            channels=audio_info["channels"],
        )
        sorted_chunks = sorted(audio_chunks, key=lambda item: item[0])
        pcm_data = b"".join(chunk for _, chunk in sorted_chunks)
        audio_dir = bag_output / output_config["audio_subdir"]

        write_wav(
            audio_dir / output_config["audio_file"],
            pcm_data,
            channels=audio_info["channels"],
            sample_rate=audio_info["sample_rate"],
            sample_width=sample_width,
        )

        write_audio_chunks_jsonl(
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
        json_dump(audio_meta, audio_dir / output_config["audio_info_file"], json_config)

    if event_labels:
        labels_dir = bag_output / output_config["labels_subdir"]
        labels_dir.mkdir(parents=True, exist_ok=True)
        labels_path = labels_dir / output_config["event_labels_file"]
        with labels_path.open("w", encoding="utf-8") as labels_file:
            for item in event_labels:
                labels_file.write(json.dumps(item, ensure_ascii=json_config.get("ensure_ascii", False)) + "\n")

    return BagParseResult(
        metadata=metadata,
        timeline_messages=timeline_messages,
        frames=frames,
        audio_chunks=audio_chunk_records,
        events=timeline_events,
    )


def iter_clip_dirs(clips_dir: Path, clip_names: list[str] | None = None) -> list[Path]:
    if not clips_dir.exists():
        raise FileNotFoundError(f"Clips directory not found: {clips_dir}")

    if clip_names:
        clip_dirs = [clips_dir / name for name in clip_names]
        missing = [str(path) for path in clip_dirs if not path.is_dir()]
        if missing:
            raise FileNotFoundError(f"Clip directories not found: {', '.join(missing)}")
        return clip_dirs

    return sorted(path for path in clips_dir.iterdir() if path.is_dir())


def save_timeline_records(
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    run_id: str,
    bag_stem: str,
    parse_result: BagParseResult,
    config: dict[str, Any],
    project_root: Path,
) -> None:
    timeline_config = get_timeline_config(config)
    if not timeline_config.get("enabled", False):
        return

    db_path = resolve_path(project_root, timeline_config["path"])
    table_prefix = str(timeline_config["table_prefix"])
    write_job1_timeline(
        db_path,
        table_prefix,
        clip_id=clip_id,
        clip_dir_name=clip_dir_name,
        content_hash=content_hash,
        run_id=run_id,
        bag_stem=bag_stem,
        metadata=parse_result.metadata,
        timeline_messages=parse_result.timeline_messages,
        frames=parse_result.frames,
        audio_chunks=parse_result.audio_chunks,
        events=parse_result.events,
    )
    print(
        f"[{clip_dir_name}] Timeline saved to {db_path} "
        f"(frames={len(parse_result.frames)}, audio_chunks={len(parse_result.audio_chunks)}, "
        f"events={len(parse_result.events)})"
    )


def save_parse_records(
    clip_id: str,
    clip_dir: Path,
    output_dir: Path,
    summary: list[dict[str, Any]],
    config: dict[str, Any],
    project_root: Path,
) -> None:
    db_config = config.get("database")
    if not db_config or not db_config.get("enabled", False):
        return

    db_path = resolve_path(project_root, db_config["path"])
    table_name = db_config["table"]
    topic_specs = get_topic_column_specs(db_config)
    output_config = config["output"]
    summary_path = output_dir / output_config["summary_file"]

    init_db(db_path, table_name, topic_specs)
    for metadata in summary:
        bag_stem = Path(str(metadata["bag_file"])).stem
        bag_output_dir = output_dir / output_config["bag_output_dir"].format(bag_stem=bag_stem)
        metadata_path = bag_output_dir / output_config["metadata_file"]

        upsert_parse_record(
            db_path,
            table_name,
            topic_specs,
            clip_id=clip_id,
            clip_dir=clip_dir,
            parsed_data_dir=output_dir,
            summary_path=summary_path,
            metadata_path=metadata_path,
            bag_output_dir=bag_output_dir,
            metadata=metadata,
        )

    print(f"[{clip_dir.name}] Parse records saved to {db_path} ({table_name}) [clip_id={clip_id}]")


def get_db_path(config: dict[str, Any], project_root: Path) -> Path:
    db_config = config["database"]
    return resolve_path(project_root, db_config["path"])


def update_pipeline_step_status(
    config: dict[str, Any],
    project_root: Path,
    *,
    run_id: str,
    step_id: str,
    phase: str,
    error_message: str | None = None,
) -> None:
    pipeline_config = get_pipeline_config(config)
    db_path = get_db_path(config, project_root)
    table_name = str(pipeline_config["table"])
    init_pipeline_db(db_path, table_name)

    if phase == "running":
        mark_step_running(db_path, table_name, pipeline_config, run_id, step_id)
    elif phase == "completed":
        mark_step_completed(db_path, table_name, pipeline_config, run_id, step_id)
    elif phase == "failed":
        if not error_message:
            raise ValueError("error_message is required when phase=failed")
        mark_step_failed(db_path, table_name, pipeline_config, run_id, step_id, error_message)
    else:
        raise ValueError(f"Unsupported pipeline phase: {phase}")


def process_clip(
    clip_dir: Path,
    config: dict[str, Any],
    project_root: Path,
    *,
    run_id: str | None = None,
    pipeline_step_id: str = "parse_rosbag",
) -> list[dict[str, Any]]:
    paths_config = config["paths"]
    rosbag_dir = clip_dir / paths_config["rosbag_subdir"]
    output_dir = clip_dir / paths_config["parsed_data_subdir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    if not rosbag_dir.exists():
        raise FileNotFoundError(f"Rosbag directory not found: {rosbag_dir}")

    bag_paths = discover_bags(rosbag_dir, config["bag"])
    if not bag_paths:
        raise FileNotFoundError(f"No rosbag files found in: {rosbag_dir}")

    if run_id is not None:
        update_pipeline_step_status(
            config,
            project_root,
            run_id=run_id,
            step_id=pipeline_step_id,
            phase="running",
        )

    manifest_path = write_rosbag_manifest(rosbag_dir, config["bag"])
    content_hash = compute_content_hash(rosbag_dir, config["bag"])
    clip_id = compute_clip_id(rosbag_dir, config)
    print(f"[{clip_dir.name}] Rosbag manifest written to {manifest_path}")
    effective_run_id = run_id or LOCAL_RUN_ID

    summary: list[dict[str, Any]] = []
    try:
        for bag_path in bag_paths:
            print(f"[{clip_dir.name}] Parsing {bag_path.name} ... [clip_id={clip_id}]")
            parse_result = parse_bag(bag_path, output_dir, config)
            summary.append(parse_result.metadata)
            save_timeline_records(
                clip_id,
                clip_dir.name,
                content_hash,
                effective_run_id,
                bag_path.stem,
                parse_result,
                config,
                project_root,
            )
            bag_output_name = config["output"]["bag_output_dir"].format(bag_stem=bag_path.stem)
            print(
                f"  done: {parse_result.metadata['message_count']} messages, "
                f"{parse_result.metadata['duration_sec']:.2f}s -> {output_dir / bag_output_name}"
            )

        summary_path = output_dir / config["output"]["summary_file"]
        json_dump(summary, summary_path, config["json"])
        print(f"[{clip_dir.name}] Summary written to {summary_path}")

        save_parse_records(clip_id, clip_dir, output_dir, summary, config, project_root)

        if run_id is not None:
            update_pipeline_step_status(
                config,
                project_root,
                run_id=run_id,
                step_id=pipeline_step_id,
                phase="completed",
            )
    except Exception as exc:
        if run_id is not None:
            update_pipeline_step_status(
                config,
                project_root,
                run_id=run_id,
                step_id=pipeline_step_id,
                phase="failed",
                error_message=str(exc),
            )
        raise

    return summary


def sync_database(config: dict[str, Any], project_root: Path, clip_dirs: list[Path]) -> None:
    db_config = config.get("database")
    if not db_config or not db_config.get("enabled", False):
        print("Database sync skipped: database.enabled is false")
        return

    db_path = resolve_path(project_root, db_config["path"])
    table_name = db_config["table"]
    topic_specs = get_topic_column_specs(db_config)
    output_config = config["output"]
    paths_config = config["paths"]

    init_db(db_path, table_name, topic_specs)

    total = 0
    for clip_dir in clip_dirs:
        output_dir = clip_dir / paths_config["parsed_data_subdir"]
        summary_path = output_dir / output_config["summary_file"]
        if not summary_path.exists():
            print(f"[{clip_dir.name}] Skip sync: summary not found at {summary_path}")
            continue

        rosbag_dir = clip_dir / paths_config["rosbag_subdir"]
        try:
            clip_id = compute_clip_id(rosbag_dir, config)
        except FileNotFoundError:
            print(f"[{clip_dir.name}] Skip sync: no rosbag files for clip_id computation")
            continue

        synced = sync_clip_records(
            db_path,
            table_name,
            topic_specs,
            clip_id=clip_id,
            clip_dir=clip_dir,
            parsed_data_dir=output_dir,
            summary_path=summary_path,
            output_config=output_config,
        )
        total += synced
        print(f"[{clip_dir.name}] Synced {synced} record(s) to {db_path}")

    print(f"Database sync complete: {total} record(s) in {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse ROS bag files from clip directories.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_REPO_ROOT / "shared" / "config.yaml",
        help="Path to config file (default: shared/config.yaml)",
    )
    parser.add_argument(
        "--clip",
        action="append",
        dest="clips",
        help="Process only the specified clip directory name. Can be repeated.",
    )
    parser.add_argument(
        "--sync-db-only",
        action="store_true",
        help="Only sync SQLite records from existing summary/metadata files, without re-parsing bags.",
    )
    parser.add_argument(
        "--run-id",
        help="Pipeline run id; when set, update clip_pipeline_runs for step parse_rosbag.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    project_root = resolve_path(config_path.parent, config.get("project_root", "."))

    paths_config = config["paths"]
    clips_dir = resolve_path(project_root, paths_config["clips_dir"])
    clip_dirs = iter_clip_dirs(clips_dir, args.clips)

    if not clip_dirs:
        raise FileNotFoundError(f"No clip directories found in: {clips_dir}")

    if args.sync_db_only:
        sync_database(config, project_root, clip_dirs)
        return

    for clip_dir in clip_dirs:
        process_clip(clip_dir, config, project_root, run_id=args.run_id)

    print(f"Processed {len(clip_dirs)} clip(s) from {clips_dir}")


if __name__ == "__main__":
    main()
