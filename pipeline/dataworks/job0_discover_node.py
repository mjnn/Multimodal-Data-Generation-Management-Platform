# =============================================================================
# DataWorks PyODPS 3 节点：Job0-OSS 发现新 Bag（MaxFrame + DPE）
# 粘贴整文件到 PyODPS3 节点；依赖 maxframe、pyodps、pandas（无需 alibabacloud_oss_v2）。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 流程：DPE 挂载 OSS 列举+算 hash（不用 driver AK 调 OSS API）→ driver 写 dim_clip
#
# 工作流参数：
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   table_prefix=aig_rosbag__
#   scan_prefix=rosbags/
#   oss_ram_role_arn=acs:ram::...:role/maxframe-rosbag-oss   # 推荐必填
#   oss_mount_prefix=              # 空=挂整桶
#   dpe_cpu=2
#   dpe_memory_gb=8
#   dpe_mount_path=/mnt/oss
# =============================================================================

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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
    "scan_prefix": "rosbags/",
    "clip_id_format": "sha256:{hex}",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}


def _apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oss_region(region: str) -> str:
    return region.replace("_", "-")


def _oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    region_id = _oss_region(region)
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


def _format_clip_id(content_hash: str, fmt: str) -> str:
    return fmt.format(hex=content_hash)


def _clip_dir_name_from_key(object_key: str) -> str:
    parent = PurePosixPath(object_key).parent.name
    if parent and parent not in (".", "/"):
        return parent
    return PurePosixPath(object_key).stem


def _hash_bag_file(bag_path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(bag_path.name.encode("utf-8"))
    with bag_path.open("rb") as bag_file:
        while True:
            block = bag_file.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


_UPLOAD_MARKER_FILES = (".upload_complete", "upload_complete.json", "upload_manifest.json")


def _upload_run_id_from_key(object_key: str, uploads_prefix: str) -> str | None:
    prefix = uploads_prefix.strip("/") + "/"
    key = object_key.strip("/")
    if not key.startswith(prefix.strip("/")):
        return None
    rest = key[len(prefix.strip("/")) :].lstrip("/")
    if not rest or "/" not in rest:
        return None
    return rest.split("/", 1)[0] or None


def _group_upload_runs_on_mount(
    pending: list[dict[str, str]],
    *,
    mount_root: Path,
    uploads_prefix: str,
    allow_legacy_flat: bool,
) -> list[dict[str, Any]]:
    prefix = uploads_prefix if uploads_prefix.endswith("/") else uploads_prefix + "/"
    grouped: dict[str, dict[str, Any]] = {}
    for bag in pending:
        object_key = str(bag.get("object_key") or "")
        clip_id = str(bag.get("clip_id") or "")
        upload_run_id = _upload_run_id_from_key(object_key, prefix)
        if upload_run_id is None:
            if not allow_legacy_flat:
                continue
            upload_run_id = f"solo-{clip_id[-16:]}"
        grouped.setdefault(
            upload_run_id,
            {"upload_run_id": upload_run_id, "bags": [], "complete": False},
        )
        grouped[upload_run_id]["bags"].append(dict(bag))
    runs: list[dict[str, Any]] = []
    for upload_run_id, run in grouped.items():
        if upload_run_id.startswith("solo-"):
            run["complete"] = True
        else:
            upload_dir = mount_root / prefix.strip("/") / upload_run_id
            run["complete"] = any((upload_dir / name).is_file() for name in _UPLOAD_MARKER_FILES)
        runs.append(run)
    runs.sort(key=lambda item: str(item.get("upload_run_id") or ""))
    return runs


def _discover_bags_on_mount(
    *,
    mount_root: Path,
    scan_prefix: str,
    bag_suffix: str,
    clip_id_format: str,
    max_scan: int,
) -> list[dict[str, str]]:
    scan_dir = mount_root / scan_prefix.strip("/") if scan_prefix else mount_root
    if not scan_dir.is_dir():
        return []

    pending: list[dict[str, str]] = []
    for bag_path in sorted(scan_dir.rglob("*")):
        if not bag_path.is_file() or not bag_path.name.endswith(bag_suffix):
            continue
        object_key = bag_path.relative_to(mount_root).as_posix()
        content_hash = _hash_bag_file(bag_path)
        pending.append(
            {
                "clip_id": _format_clip_id(content_hash, clip_id_format),
                "content_hash": content_hash,
                "object_key": object_key,
                "clip_dir_name": _clip_dir_name_from_key(object_key),
            }
        )
        if len(pending) >= max_scan:
            break
    return pending


def _existing_clip_ids(client: Any, table_name: str, clip_ids: list[str]) -> set[str]:
    if not clip_ids:
        return set()
    found: set[str] = set()
    batch_size = 50
    for start in range(0, len(clip_ids), batch_size):
        batch = clip_ids[start : start + batch_size]
        in_list = ",".join(f"'{cid.replace(chr(39), chr(39)+chr(39))}'" for cid in batch)
        sql = f"SELECT clip_id FROM {table_name} WHERE clip_id IN ({in_list});"
        with client.execute_sql(sql).open_reader() as reader:
            for record in reader:
                found.add(str(record[0]))
    return found


def _insert_discovered_clips(client: Any, table_name: str, rows: list[list[Any]]) -> None:
    table = client.get_table(table_name)
    with table.open_writer() as writer:
        writer.write(rows)


def main() -> None:
    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    scan_prefix = get_arg("scan_prefix", "") or ""
    uploads_prefix = get_arg("uploads_prefix", "rosbags/uploads/") or "rosbags/uploads/"
    allow_legacy_flat = str(get_arg("allow_legacy_flat", "false") or "false").lower() in {
        "1",
        "true",
        "yes",
    }
    clip_id_format = get_arg("clip_id_format", "sha256:{hex}")
    bag_suffix = get_arg("bag_suffix", ".bag")
    max_scan = get_int_arg("max_scan", 200)
    dry_run = str(get_arg("dry_run", "false")).lower() in {"1", "true", "yes"}
    role_arn = get_arg("oss_ram_role_arn")
    oss_mount_prefix = get_arg("oss_mount_prefix", "") or ""
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_cpu = get_int_arg("dpe_cpu", 2)
    dpe_memory = get_int_arg("dpe_memory_gb", 8)

    dim_table = f"{table_prefix}dim_clip"
    account = o.account  # type: ignore[name-defined]
    if not role_arn:
        print(
            "WARN: oss_ram_role_arn empty; DPE mount falls back to o.account AK/SK "
            "(DataWorks 节点 AK 通常不能直连 OSS API，建议配置 RAM 角色)"
        )

    dpe_image = get_arg("dpe_image")
    _apply_dpe_runtime_settings(dpe_image)

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False

    print(f"Job0 DPE image: {dpe_image}")
    session = new_session(o)  # type: ignore[name-defined]
    input_df = md.DataFrame(
        pd.DataFrame(
            [
                {
                    "scan_prefix": scan_prefix,
                    "bag_suffix": bag_suffix,
                    "max_scan": max_scan,
                    "clip_id_format": clip_id_format,
                }
            ]
        )
    )
    oss_mount_url = _oss_internal_url(cloud_region, oss_bucket, oss_mount_prefix)
    storage_options = _storage_options(role_arn, account)

    @with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)
    @with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)
    def _job0_discover_on_mount(row):
        pending = _discover_bags_on_mount(
            mount_root=Path(mount_path),
            scan_prefix=str(row["scan_prefix"]),
            bag_suffix=str(row["bag_suffix"]),
            clip_id_format=str(row["clip_id_format"]),
            max_scan=int(row["max_scan"]),
        )
        upload_runs = _group_upload_runs_on_mount(
            pending,
            mount_root=Path(mount_path),
            uploads_prefix=uploads_prefix,
            allow_legacy_flat=allow_legacy_flat,
        )
        payload = {"pending": pending, "upload_runs": upload_runs}
        return {"discovered_json": json.dumps(payload, ensure_ascii=False)}

    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            _job0_discover_on_mount,
            axis=1,
            output_type="dataframe",
            result_type="expand",
        )
        row = result_df.execute().fetch().iloc[0]
        discover_payload = json.loads(str(row["discovered_json"]))
        if isinstance(discover_payload, list):
            pending = discover_payload
            upload_runs_raw: list[dict[str, Any]] = []
        else:
            pending = discover_payload.get("pending") or []
            upload_runs_raw = discover_payload.get("upload_runs") or []
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()

    if not pending:
        print(f"Job0: no bag objects under prefix={scan_prefix!r}")
        return

    existing = _existing_clip_ids(
        o,  # type: ignore[name-defined]
        dim_table,
        [str(item["clip_id"]) for item in pending],
    )

    now = _utc_now_iso()
    new_rows: list[list[Any]] = []
    discovered: list[dict[str, str]] = []
    new_clip_ids: set[str] = set()
    for item in pending:
        clip_id = str(item["clip_id"])
        if clip_id in existing:
            continue
        new_clip_ids.add(clip_id)
        discovered.append(
            {
                "clip_id": clip_id,
                "content_hash": str(item["content_hash"]),
                "object_key": str(item["object_key"]),
                "clip_dir_name": str(item["clip_dir_name"]),
            }
        )
        new_rows.append(
            [
                clip_id,
                str(item["clip_dir_name"]),
                str(item["content_hash"]),
                None,
                now,
                now,
                str(item["object_key"]),
            ]
        )

    upload_runs_out: list[dict[str, Any]] = []
    for upload_run in upload_runs_raw:
        if not upload_run.get("complete"):
            continue
        new_bags = [
            dict(bag)
            for bag in (upload_run.get("bags") or [])
            if str(bag.get("clip_id") or "") in new_clip_ids
        ]
        if not new_bags:
            continue
        upload_runs_out.append(
            {
                "upload_run_id": str(upload_run.get("upload_run_id") or ""),
                "complete": True,
                "new_count": len(new_bags),
                "bags": new_bags,
            }
        )

    if dry_run:
        print(f"Job0 dry_run: would insert {len(new_rows)} clip(s)")
        for item in discovered:
            print(f"DISCOVERED clip_id={item['clip_id']} oss_key={item['object_key']}")
        return

    if new_rows:
        _insert_discovered_clips(o, dim_table, new_rows)  # type: ignore[name-defined]

    print(
        f"Job0 done: scanned={len(pending)} new={len(discovered)} "
        f"upload_runs={len(upload_runs_out)} prefix={scan_prefix!r} table={dim_table}"
    )
    for upload_run in upload_runs_out:
        print(
            f"UPLOAD_RUN id={upload_run['upload_run_id']} new_clips={upload_run['new_count']}"
        )
    for item in discovered:
        print(f"DISCOVERED clip_id={item['clip_id']} oss_key={item['object_key']}")
    print(f"DISCOVERED_JSON={json.dumps(discovered, ensure_ascii=False)}")

    write_discover = str(get_arg("write_discover_oss", "true") or "true").lower() not in {
        "0",
        "false",
        "no",
    }
    if write_discover and not dry_run:
        try:
            from pipeline_dispatch import (
                DEFAULT_DISCOVER_OSS_KEY,
                resolve_oss_http_endpoint,
                write_discover_manifest_to_oss,
            )

            discover_key = get_arg("discover_oss_key", DEFAULT_DISCOVER_OSS_KEY) or DEFAULT_DISCOVER_OSS_KEY
            endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
            manifest = {
                "discovered_at": now,
                "scan_prefix": scan_prefix,
                "uploads_prefix": uploads_prefix,
                "scanned": len(pending),
                "new_count": len(discovered),
                "items": discovered,
                "pending": pending,
                "upload_runs": upload_runs_out,
            }
            write_discover_manifest_to_oss(
                bucket_name=oss_bucket,
                object_key=discover_key,
                endpoint=endpoint,
                account=account,
                payload=manifest,
                region=cloud_region,
                get_arg=get_arg,
            )
            print(f"Job0 discover manifest: oss://{oss_bucket}/{discover_key}")
        except ImportError:
            print(
                "WARN: pipeline_dispatch not bundled; skip discover OSS manifest. "
                "Bundle job0_discover or set write_discover_oss=false."
            )


main()
