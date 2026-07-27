#!/usr/bin/env python3
"""Run and schedule the clip data processing pipeline with SQLite status tracking."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from clip_id import compute_clip_id
from parse_rosbag import iter_clip_dirs, load_config, process_clip, resolve_path
from pipeline_status_db import (
    create_pipeline_run,
    get_latest_run,
    get_latest_run_for_clip_dir,
    get_next_step_id,
    get_pipeline_config,
    get_run,
    init_pipeline_db,
    list_runs,
    mark_run_running,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
    rollback_run,
)
from parse_records_db import get_topic_column_specs, init_db
from timeline_db import (
    get_dim_clip,
    get_timeline_config,
    list_clip_run_versions,
    set_active_run_id,
)


def get_db_path(config: dict[str, Any], project_root: Path) -> Path:
    db_config = config["database"]
    return resolve_path(project_root, db_config["path"])


def get_pipeline_table(config: dict[str, Any]) -> str:
    pipeline_config = get_pipeline_config(config)
    return str(pipeline_config["table"])


def resolve_clip_id(clip_dir: Path, config: dict[str, Any]) -> str:
    paths_config = config["paths"]
    rosbag_dir = clip_dir / paths_config["rosbag_subdir"]
    return compute_clip_id(rosbag_dir, config)


def lookup_latest_run(
    db_path: Path,
    table_name: str,
    clip_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        clip_id = resolve_clip_id(clip_dir, config)
        run = get_latest_run(db_path, table_name, clip_id)
        if run is not None:
            return run
    except FileNotFoundError:
        pass
    return get_latest_run_for_clip_dir(db_path, table_name, clip_dir)


def ensure_databases(config: dict[str, Any], project_root: Path) -> tuple[Path, str]:
    db_path = get_db_path(config, project_root)
    db_config = config["database"]
    init_db(db_path, db_config["table"], get_topic_column_specs(db_config))
    table_name = get_pipeline_table(config)
    init_pipeline_db(db_path, table_name)
    return db_path, table_name


def get_timeline_db_path(config: dict[str, Any], project_root: Path) -> Path:
    timeline_config = get_timeline_config(config)
    return resolve_path(project_root, timeline_config["path"])


def get_timeline_table_prefix(config: dict[str, Any]) -> str:
    timeline_config = get_timeline_config(config)
    return str(timeline_config["table_prefix"])


def resolve_clip_target(
    *,
    clip_name: str | None,
    clip_id: str | None,
    clips_dir: Path,
    config: dict[str, Any],
) -> tuple[str, Path | None]:
    if clip_id:
        if clip_name:
            raise SystemExit("Use either --clip or --clip-id, not both")
        return clip_id, None

    if not clip_name:
        raise SystemExit("Provide --clip or --clip-id")

    clip_dir = clips_dir / clip_name
    if not clip_dir.is_dir():
        raise SystemExit(f"Clip directory not found: {clip_dir}")
    return resolve_clip_id(clip_dir, config), clip_dir


def print_active_run(
    clip_id: str,
    timeline_db_path: Path,
    table_prefix: str,
) -> None:
    dim_clip = get_dim_clip(timeline_db_path, table_prefix, clip_id)
    if dim_clip is None:
        raise SystemExit(f"No dim_clip record found for clip_id={clip_id}")

    print(f"clip_id: {dim_clip['clip_id']}")
    print(f"clip_dir_name: {dim_clip['clip_dir_name']}")
    print(f"active_run_id: {dim_clip['active_run_id']}")
    print(f"updated_at: {dim_clip['updated_at']}")


def print_clip_run_versions(
    clip_id: str,
    timeline_db_path: Path,
    table_prefix: str,
    pipeline_db_path: Path,
    pipeline_table: str,
) -> None:
    versions = list_clip_run_versions(timeline_db_path, table_prefix, clip_id)
    if not versions:
        raise SystemExit(f"No timeline run versions found for clip_id={clip_id}")

    pipeline_runs = {
        run["run_id"]: run
        for run in list_runs(
            pipeline_db_path,
            pipeline_table,
            clip_id=clip_id,
            limit=1000,
        )
    }

    print(f"clip_id: {clip_id}")
    print("timeline_versions:")
    for version in versions:
        marker = " *" if version["is_active"] else ""
        pipeline_run = pipeline_runs.get(version["run_id"])
        pipeline_status = pipeline_run["status"] if pipeline_run else "-"
        print(
            f"  - run_id={version['run_id']}{marker} | bags={version['bag_count']} | "
            f"parsed_at={version['last_parsed_at']} | pipeline_status={pipeline_status}"
        )
    print(f"Listed {len(versions)} timeline version(s)")


def build_step_command(step: dict[str, Any], clip_id: str, run_id: str) -> list[str]:
    command_template = str(step["command"])
    command = command_template.format(clip_id=clip_id, run_id=run_id)
    return shlex.split(command, posix=(sys.platform != "win32"))


def execute_step(step: dict[str, Any], clip_id: str, run_id: str, project_root: Path) -> None:
    command = build_step_command(step, clip_id, run_id)
    result = subprocess.run(command, cwd=project_root, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Step '{step['id']}' failed with exit code {result.returncode}: {' '.join(command)}"
        )


def run_step_inline(
    step_id: str,
    clip_dir: Path,
    config: dict[str, Any],
    project_root: Path,
    *,
    run_id: str | None = None,
) -> None:
    if step_id == "parse_rosbag":
        process_clip(clip_dir, config, project_root, run_id=run_id)
        return
    raise NotImplementedError(f"No inline handler for pipeline step: {step_id}")


def execute_pipeline_run(
    run_id: str,
    clip_dir: Path,
    config: dict[str, Any],
    project_root: Path,
    db_path: Path,
    table_name: str,
) -> None:
    pipeline_config = get_pipeline_config(config)
    run = get_run(db_path, table_name, run_id)
    steps = json.loads(run["steps_json"])

    mark_run_running(db_path, table_name, pipeline_config, run_id)

    while True:
        step_id = get_next_step_id(pipeline_config, steps)
        if step_id is None:
            break

        step = next(item for item in pipeline_config["steps"] if str(item["id"]) == step_id)
        if not step.get("enabled", True):
            continue

        print(f"[{clip_dir.name}] Running step '{step_id}' (run_id={run_id}) ...")
        mark_step_running(db_path, table_name, pipeline_config, run_id, step_id)

        try:
            if step.get("inline", False):
                run_step_inline(step_id, clip_dir, config, project_root, run_id=run_id)
            else:
                execute_step(step, clip_dir.name, run_id, project_root)
            mark_step_completed(db_path, table_name, pipeline_config, run_id, step_id)
            run = get_run(db_path, table_name, run_id)
            steps = json.loads(run["steps_json"])
            print(f"[{clip_dir.name}] Step '{step_id}' completed")
        except Exception as exc:
            mark_step_failed(db_path, table_name, pipeline_config, run_id, step_id, str(exc))
            raise

    final_run = get_run(db_path, table_name, run_id)
    print(
        f"[{clip_dir.name}] Pipeline finished with status={final_run['status']} "
        f"(run_id={run_id})"
    )


def print_run_status(run: dict[str, Any]) -> None:
    steps = json.loads(run["steps_json"])
    print(f"run_id: {run['run_id']}")
    print(f"clip_id: {run['clip_id']}")
    print(f"pipeline: {run['pipeline_name']}")
    print(f"status: {run['status']}")
    print(f"current_step_id: {run['current_step_id']}")
    print(f"rollback_to_step: {run['rollback_to_step']}")
    print(f"started_at: {run['started_at']}")
    print(f"updated_at: {run['updated_at']}")
    print(f"completed_at: {run['completed_at']}")
    if run["error_message"]:
        print(f"error_message: {run['error_message']}")
    print("steps:")
    for step_id, step_state in steps.items():
        print(
            f"  - {step_id}: status={step_state['status']}, "
            f"started_at={step_state['started_at']}, finished_at={step_state['finished_at']}"
        )
        if step_state["error_message"]:
            print(f"    error: {step_state['error_message']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run clip processing pipeline with status tracking.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--clip", action="append", dest="clips")
    parser.add_argument("--run-id", help="Resume, inspect, or rollback an existing pipeline run.")
    parser.add_argument("--status", action="store_true", help="Show pipeline run status.")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List pipeline runs filtered by --run-status and/or --current-step.",
    )
    parser.add_argument("--run-status", help="Filter runs by overall status.")
    parser.add_argument("--current-step", help="Filter runs by current step id.")
    parser.add_argument("--rollback", action="store_true", help="Rollback a run to --to-step.")
    parser.add_argument("--to-step", help="Rollback target step id.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing run from the next pending step.",
    )
    parser.add_argument(
        "--clip-id",
        help="Content-addressed clip id (sha256:...). Alternative to --clip.",
    )
    parser.add_argument(
        "--show-active-run",
        action="store_true",
        help="Show dim_clip.active_run_id for a clip.",
    )
    parser.add_argument(
        "--list-clip-runs",
        action="store_true",
        help="List timeline run versions for a clip (active run marked with *).",
    )
    parser.add_argument(
        "--set-active-run",
        metavar="RUN_ID",
        help="Switch dim_clip.active_run_id to an existing timeline run version.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = load_config(config_path)
    project_root = resolve_path(config_path.parent, config.get("project_root", "."))
    db_path, table_name = ensure_databases(config, project_root)
    pipeline_config = get_pipeline_config(config)
    paths_config = config["paths"]
    clips_dir = resolve_path(project_root, paths_config["clips_dir"])
    timeline_db_path = get_timeline_db_path(config, project_root)
    timeline_table_prefix = get_timeline_table_prefix(config)

    if args.show_active_run:
        clip_names = args.clips or []
        if args.clip_id:
            print_active_run(args.clip_id, timeline_db_path, timeline_table_prefix)
            return
        if len(clip_names) != 1:
            raise SystemExit("--show-active-run requires exactly one --clip or --clip-id")
        resolved_clip_id, _ = resolve_clip_target(
            clip_name=clip_names[0],
            clip_id=None,
            clips_dir=clips_dir,
            config=config,
        )
        print_active_run(resolved_clip_id, timeline_db_path, timeline_table_prefix)
        return

    if args.list_clip_runs:
        clip_names = args.clips or []
        if args.clip_id:
            print_clip_run_versions(
                args.clip_id,
                timeline_db_path,
                timeline_table_prefix,
                db_path,
                table_name,
            )
            return
        if len(clip_names) != 1:
            raise SystemExit("--list-clip-runs requires exactly one --clip or --clip-id")
        resolved_clip_id, _ = resolve_clip_target(
            clip_name=clip_names[0],
            clip_id=None,
            clips_dir=clips_dir,
            config=config,
        )
        print_clip_run_versions(
            resolved_clip_id,
            timeline_db_path,
            timeline_table_prefix,
            db_path,
            table_name,
        )
        return

    if args.set_active_run:
        clip_names = args.clips or []
        if args.clip_id:
            resolved_clip_id = args.clip_id
        elif len(clip_names) == 1:
            resolved_clip_id, _ = resolve_clip_target(
                clip_name=clip_names[0],
                clip_id=None,
                clips_dir=clips_dir,
                config=config,
            )
        else:
            raise SystemExit("--set-active-run requires --clip or --clip-id")

        updated = set_active_run_id(
            timeline_db_path,
            timeline_table_prefix,
            clip_id=resolved_clip_id,
            run_id=args.set_active_run,
        )
        print(
            f"Active run switched for clip_id={updated['clip_id']}: "
            f"active_run_id={updated['active_run_id']}"
        )
        return

    if args.list:
        runs = list_runs(
            db_path,
            table_name,
            status=args.run_status,
            current_step_id=args.current_step,
        )
        for run in runs:
            print(
                f"{run['run_id']} | clip={run['clip_id']} | status={run['status']} | "
                f"current_step={run['current_step_id']} | updated_at={run['updated_at']}"
            )
        print(f"Listed {len(runs)} run(s)")
        return

    if args.status:
        if not args.run_id and not args.clips:
            raise SystemExit("Provide --run-id or --clip with --status")
        if args.run_id:
            print_run_status(get_run(db_path, table_name, args.run_id))
        else:
            for clip_name in args.clips:
                clip_dir = clips_dir / clip_name
                run = lookup_latest_run(db_path, table_name, clip_dir, config)
                if run is None:
                    print(f"No pipeline run found for clip: {clip_name}")
                    continue
                print_run_status(run)
                print()
        return

    if args.rollback:
        if not args.run_id or not args.to_step:
            raise SystemExit("--rollback requires --run-id and --to-step")
        rollback_run(db_path, table_name, pipeline_config, args.run_id, args.to_step)
        print(f"Rolled back run {args.run_id} to step '{args.to_step}'")
        print_run_status(get_run(db_path, table_name, args.run_id))
        return

    if args.resume:
        if not args.run_id:
            raise SystemExit("--resume requires --run-id")
        run = get_run(db_path, table_name, args.run_id)
        clip_dir = Path(run["clip_dir"])
        execute_pipeline_run(args.run_id, clip_dir, config, project_root, db_path, table_name)
        return

    clip_dirs = iter_clip_dirs(clips_dir, args.clips)
    if not clip_dirs:
        raise FileNotFoundError(f"No clip directories found in: {clips_dir}")

    for clip_dir in clip_dirs:
        clip_id = resolve_clip_id(clip_dir, config)
        run_id = create_pipeline_run(
            db_path,
            table_name,
            pipeline_config,
            clip_id=clip_id,
            clip_dir=clip_dir,
        )
        print(f"[{clip_dir.name}] Created pipeline run {run_id} [clip_id={clip_id}]")
        execute_pipeline_run(run_id, clip_dir, config, project_root, db_path, table_name)


if __name__ == "__main__":
    main()
