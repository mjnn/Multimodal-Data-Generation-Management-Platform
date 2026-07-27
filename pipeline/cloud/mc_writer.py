"""Write Job1 parse results to MaxCompute tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from odps import ODPS


def _table_name(prefix: str, base: str) -> str:
    return f"{prefix}{base}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _partition_spec(ds: str) -> str:
    return f"ds={ds}"


def write_job1_to_mc(
    odps: ODPS,
    *,
    table_prefix: str,
    ds: str,
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    bag_oss_key: str | None = None,
    run_id: str,
    bag_stem: str,
    parse_result: dict[str, Any],
) -> None:
    """Insert Job1 rows into MC tables for one bag parse."""
    metadata = parse_result["metadata"]
    now = _utc_now_iso()
    partition = _partition_spec(ds)

    dim_table_name = _table_name(table_prefix, "dim_clip")
    odps.execute_sql(f"DELETE FROM {dim_table_name} WHERE clip_id = '{clip_id}';")
    dim_table = odps.get_table(dim_table_name)
    with dim_table.open_writer() as writer:
        writer.write(
            [
                [
                    clip_id,
                    clip_dir_name,
                    content_hash,
                    run_id,
                    now,
                    now,
                    bag_oss_key,
                ]
            ]
        )

    run_table = odps.get_table(_table_name(table_prefix, "pipeline_run"))
    with run_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, clip_id, "completed", now, now, now]])

    step_table = odps.get_table(_table_name(table_prefix, "pipeline_step"))
    with step_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, "job1_parse", "completed", now, now, None]])

    timeline_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            item["topic"],
            item["msgtype"],
            item["modality"],
            int(item["timestamp_ns"]),
            int(item["sequence_idx"]),
        ]
        for item in parse_result["timeline_messages"]
    ]
    if timeline_rows:
        table = odps.get_table(_table_name(table_prefix, "fact_message_timeline"))
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(timeline_rows)

    frame_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            item["camera"],
            int(item["frame_idx"]),
            int(item["timestamp_ns"]),
            item["topic"],
            item["image_path"],
        ]
        for item in parse_result["frames"]
    ]
    if frame_rows:
        table = odps.get_table(_table_name(table_prefix, "fact_frame"))
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(frame_rows)

    audio_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            int(item["chunk_idx"]),
            int(item["timestamp_ns"]),
            int(item["byte_offset"]),
            int(item["byte_length"]),
            int(item["sample_count"]),
            int(item["duration_ns"]),
            int(item["pcm_bytes"]),
        ]
        for item in parse_result["audio_chunks"]
    ]
    if audio_rows:
        table = odps.get_table(_table_name(table_prefix, "fact_audio_chunk"))
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(audio_rows)

    event_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            int(item["timestamp_ns"]),
            item["event_data"],
        ]
        for item in parse_result["events"]
    ]
    if event_rows:
        table = odps.get_table(_table_name(table_prefix, "fact_event"))
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(event_rows)

    summary_table = odps.get_table(_table_name(table_prefix, "clip_parse_summary"))
    with summary_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write(
            [
                [
                    clip_id,
                    run_id,
                    bag_stem,
                    str(metadata["bag_file"]),
                    int(metadata["duration_ns"]),
                    float(metadata["duration_sec"]),
                    int(metadata["start_time_ns"]),
                    int(metadata["end_time_ns"]),
                    int(metadata["message_count"]),
                    json.dumps(metadata.get("topics", {}), ensure_ascii=False),
                    now,
                ]
            ]
        )
