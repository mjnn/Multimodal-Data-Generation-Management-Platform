# =============================================================================
# DataWorks PyODPS 3 节点：Job3-抽样帧打标（MaxFrame + DPE）
#
# ★★★ DataWorks 必须粘贴 bundled 整文件，勿粘贴本文件 ★★★
#   python scripts/bundle_dataworks_node.py dataworks/job3_label_node.py
#   → 粘贴 dataworks/bundled/job3_label_node.py（约 1700+ 行，含 mf_ai_function 内联）
#
# 粘贴整文件到 PyODPS3 节点；Driver 需 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
# DPE worker：推荐 dpe_image=<MC 镜像名>（docker/dpe-deps 含 pyyaml）。
#
# 读 Job2 产物：clips/{clip_id}/runs/{run_id}/job2/sample_manifest.jsonl
# 读 Job1 帧图：clips/{clip_id}/runs/{run_id}/parsed/{image_relpath}
# 写 Job3 产物：clips/{clip_id}/runs/{run_id}/job3/frame_labels.jsonl
#              clips/{clip_id}/runs/{run_id}/job3/job3_mc_payload.json
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
#   job3_config_json=
#   label_taxonomy_json=             # 可选，整份 taxonomy JSON
#   label_taxonomy_oss_key=config/oms_label_taxonomy.yaml
#
# 节点参数
#   clip_id=sha256:...
#   run_id=<Job1 相同>
#   label_model=                     # 留空=stub（labels_json 中 values 为空）
#   label_model_version=
#   label_batch_size=32
#   label_timezone=Asia/Shanghai     # L1.1 时间标签由 record_time_ns 后处理写入
#   exclude_labels=L1.1.timestamp,L1.1.day_period,L1.1.commute_flag,L1.1.is_holiday
#   label_image_mode=auto          # auto|oss_url|base64；有 role_arn 或 oss_vl AK/SK 时 auto→oss_url
#   oss_vl_access_key_id=           # 长期 OSS AK（VL IMAGE_URL；非 STS.*；别名 oss_access_key_id）
#   oss_vl_access_key_secret=     # 长期 OSS SK（与上成对；别名 oss_access_key_secret）
#   ※ oss_ram_role_arn 仅 DPE 挂载用；cp.image(IMAGE_URL) 必须 AK/SK，不能靠 role_arn
#   label_prompt_compact=true      # 压缩 taxonomy prompt，减少 VL token
#   ai_parallel_partitions=16      # MCSQL 行级并发（默认自动放大到 min(帧数,32)）
#   total_rpm_limit=12000          # VL generate running_options；0=不传
#   request_timeout=300            # VL generate 单次请求超时（秒）；0=不传
#   ai_memory=8G                   # VL generate Worker 内存；留空=不传
# =============================================================================

from __future__ import annotations

import base64
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

from pipeline_dispatch import exit_if_pipeline_idle, resolve_pipeline_context
from oms_time_labels import (
    DEFAULT_LABEL_TIMEZONE,
    apply_l1_time_label_overrides,
)
from sample_sync import group_manifest_by_sync

_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}

DEFAULT_JOB3_CONFIG: dict[str, Any] = {
    "provider": "maxframe_ai_function",
    "model": "",
    "model_version": "",
    "label_taxonomy_oss_key": "config/oms_label_taxonomy.yaml",
    "exclude_labels": [],
    "batch_size": 32,
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
        "ai_label_frames_with_model",
        "ai_label_sync_groups_with_model",
        "build_vl_oss_storage_options",
        "resolve_label_image_mode",
        "resolve_ai_parallel_partitions",
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


def _resolve_oss_vl_ak_sk() -> tuple[str, str]:
    ak = (
        get_arg("oss_vl_access_key_id")
        or get_arg("oss_access_key_id")
        or ""
    )
    sk = (
        get_arg("oss_vl_access_key_secret")
        or get_arg("oss_access_key_secret")
        or ""
    )
    return ak, sk


def load_job3_config() -> dict[str, Any]:
    raw = get_arg("job3_config_json")
    if not raw:
        return DEFAULT_JOB3_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("job3_config_json must be a JSON object")
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(json.loads(text))
    return rows


def _load_taxonomy_from_mount(
    mount_path: str,
    *,
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
) -> dict[str, Any]:
    if label_taxonomy_json:
        loaded = json.loads(label_taxonomy_json)
        if not isinstance(loaded, dict):
            raise ValueError("label_taxonomy_json must be a JSON object")
        return loaded

    if label_taxonomy_oss_key:
        taxonomy_path = Path(mount_path) / label_taxonomy_oss_key
        if taxonomy_path.is_file():
            text = taxonomy_path.read_text(encoding="utf-8")
            if taxonomy_path.suffix.lower() in {".yaml", ".yml"}:
                import yaml

                loaded = yaml.safe_load(text)
            else:
                loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded

    return {
        "version": "stub",
        "label_count": 0,
        "labels": [],
        "source": "embedded-stub",
    }


def _filter_taxonomy(taxonomy: dict[str, Any], exclude_labels: list[str]) -> dict[str, Any]:
    if not exclude_labels:
        return taxonomy
    excluded = set(exclude_labels)
    labels = taxonomy.get("labels") or []
    filtered = [item for item in labels if str(item.get("id")) not in excluded]
    return {
        **taxonomy,
        "labels": filtered,
        "label_count": len(filtered),
        "excluded_labels": list(excluded),
    }


def _frame_id(camera: str, frame_idx: int) -> str:
    return f"{camera}:{frame_idx}"


def _build_label_prompt(taxonomy: dict[str, Any]) -> str:
    lines = [
        "You are an OMS in-cabin vision labeler.",
        "Return JSON object mapping label id to value, following each label value_schema.",
        f"Taxonomy version: {taxonomy.get('version', 'unknown')}",
        "Labels:",
    ]
    for item in taxonomy.get("labels") or []:
        label_id = item.get("id")
        name = item.get("name")
        definition = item.get("definition")
        schema = item.get("value_schema") or {}
        lines.append(f"- {label_id} ({name}): {definition}; schema={json.dumps(schema, ensure_ascii=False)}")
    return "\n".join(lines)


def _stub_labels_payload(
    *,
    taxonomy: dict[str, Any],
    model_version: str,
) -> dict[str, Any]:
    return {
        "taxonomy_version": str(taxonomy.get("version") or "unknown"),
        "provider": "maxcompute_ai",
        "model_version": model_version,
        "status": "stub",
        "values": {},
    }


def _label_single_frame_stub(
    *,
    frame: dict[str, Any],
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    image_bytes: bytes | None,
) -> dict[str, Any]:
    resolved_version = model_version or ("none" if not model else model)
    labels_payload = _stub_labels_payload(taxonomy=taxonomy, model_version=resolved_version)
    if model:
        # MC AI 接入点：当前版本保留 OMS 结构，values 留空供后续 vision 模型填充。
        labels_payload["status"] = "pending_model_integration"
    labels_payload["image_size_bytes"] = len(image_bytes) if image_bytes else 0
    return labels_payload


def _resolve_frame_image_path(parsed_root: Path, frame: dict[str, Any]) -> Path:
    """Resolve sampled frame image under parsed/ (handles legacy duplicated paths)."""
    raw = str(frame.get("image_relpath") or frame.get("image_path") or "").strip().lstrip("/")
    candidates = [parsed_root / raw]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        candidates.append(parsed_root / raw.rsplit(parsed_marker, 1)[-1].lstrip("/"))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _manifest_is_sync(manifest_rows: list[dict[str, Any]]) -> bool:
    return any(str(row.get("sync_group_id") or "").strip() for row in manifest_rows)


def _build_sync_groups(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = group_manifest_by_sync(manifest_rows)
    if not groups:
        return []
    for group in groups:
        group["frames"] = sorted(
            group.get("frames") or [],
            key=lambda item: str(item.get("camera") or ""),
        )
    return groups


def _run_label_sync_batches(
    sync_groups: list[dict[str, Any]],
    *,
    parsed_root: Path,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    prompt = _build_label_prompt(taxonomy) if model else ""

    for group in sync_groups:
        anchor_ns = int(group.get("anchor_timestamp_ns") or 0)
        sync_group_id = str(group.get("sync_group_id") or "")
        group_frames = group.get("frames") or []
        if not group_frames:
            continue

        labels_payload = _label_single_frame_stub(
            frame=group_frames[0],
            taxonomy=taxonomy,
            model=model,
            model_version=model_version,
            image_bytes=None,
        )
        if model and prompt:
            labels_payload["_prompt_chars"] = len(prompt)
        labels_payload["values"] = apply_l1_time_label_overrides(
            labels_payload.get("values") or {},
            anchor_ns,
            timezone=label_timezone,
        )
        labels_payload["label_scope"] = "sync_group"
        labels_payload["sync_group_id"] = sync_group_id

        for frame in group_frames:
            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            results.append(
                {
                    "frame_id": _frame_id(camera, frame_idx),
                    "camera": camera,
                    "frame_idx": frame_idx,
                    "timestamp_ns": int(frame["timestamp_ns"]),
                    "anchor_timestamp_ns": anchor_ns,
                    "sync_group_id": sync_group_id,
                    "label_scope": "sync_group",
                    "image_relpath": str(frame.get("image_relpath") or ""),
                    "sample_policy": frame.get("sample_policy"),
                    "labels_json": dict(labels_payload),
                }
            )
    return results


def _run_label_batches(
    manifest_rows: list[dict[str, Any]],
    *,
    parsed_root: Path,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    batch_size: int,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    prompt = _build_label_prompt(taxonomy) if model else ""

    for start in range(0, len(manifest_rows), batch_size):
        batch = manifest_rows[start : start + batch_size]
        for frame in batch:
            image_path = _resolve_frame_image_path(parsed_root, frame)
            image_bytes = image_path.read_bytes() if image_path.is_file() else None
            if image_bytes is None:
                raise FileNotFoundError(f"Sampled frame image not found: {image_path}")

            labels_payload = _label_single_frame_stub(
                frame=frame,
                taxonomy=taxonomy,
                model=model,
                model_version=model_version,
                image_bytes=image_bytes,
            )
            if model and prompt:
                labels_payload["_prompt_chars"] = len(prompt)
            labels_payload["values"] = apply_l1_time_label_overrides(
                labels_payload.get("values") or {},
                int(frame["timestamp_ns"]),
                timezone=label_timezone,
            )

            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            results.append(
                {
                    "frame_id": _frame_id(camera, frame_idx),
                    "camera": camera,
                    "frame_idx": frame_idx,
                    "timestamp_ns": int(frame["timestamp_ns"]),
                    "image_relpath": str(frame["image_relpath"]),
                    "sample_policy": frame.get("sample_policy"),
                    "labels_json": labels_payload,
                }
            )
    return results


def _build_job3_label_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job3_config: dict[str, Any],
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
    exclude_labels: list[str],
    label_model: str,
    label_model_version: str,
    label_batch_size: int,
    label_timezone: str,
):
    def _job3_label_row(row):
        manifest_path = Path(mount_path) / row["manifest_relpath"]
        if not manifest_path.is_file():
            job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
            if not job2_payload_path.is_file():
                raise FileNotFoundError(
                    f"Job2 manifest not found: {manifest_path}; payload: {job2_payload_path}"
                )
            job2_payload = json.loads(job2_payload_path.read_text(encoding="utf-8"))
            manifest_rows = job2_payload.get("sampled_frames") or []
        else:
            manifest_rows = _read_jsonl(manifest_path)

        if not manifest_rows:
            raise ValueError("Job2 sample manifest is empty; run Job2 sampling first")

        taxonomy = _load_taxonomy_from_mount(
            mount_path,
            label_taxonomy_json=label_taxonomy_json,
            label_taxonomy_oss_key=label_taxonomy_oss_key,
        )
        taxonomy = _filter_taxonomy(taxonomy, exclude_labels)

        parsed_root = Path(mount_path) / row["parsed_relpath"]
        if _manifest_is_sync(manifest_rows):
            sync_groups = _build_sync_groups(manifest_rows)
            labeled_frames = _run_label_sync_batches(
                sync_groups,
                parsed_root=parsed_root,
                taxonomy=taxonomy,
                model=label_model,
                model_version=label_model_version,
                label_timezone=label_timezone,
            )
        else:
            labeled_frames = _run_label_batches(
                manifest_rows,
                parsed_root=parsed_root,
                taxonomy=taxonomy,
                model=label_model,
                model_version=label_model_version,
                batch_size=label_batch_size,
                label_timezone=label_timezone,
            )

        job3_root = Path(mount_path) / row["job3_relpath"]
        job3_root.mkdir(parents=True, exist_ok=True)

        frame_labels_path = job3_root / "frame_labels.jsonl"
        with frame_labels_path.open("w", encoding="utf-8") as labels_file:
            for item in labeled_frames:
                row_out = {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                if item.get("sync_group_id"):
                    row_out["sync_group_id"] = item["sync_group_id"]
                    row_out["anchor_timestamp_ns"] = item.get("anchor_timestamp_ns")
                    row_out["label_scope"] = item.get("label_scope") or "sync_group"
                labels_file.write(json.dumps(row_out, ensure_ascii=False) + "\n")

        resolved_model_version = label_model_version or (
            "none" if not label_model else label_model
        )
        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "taxonomy_label_count": int(taxonomy.get("label_count") or len(taxonomy.get("labels") or [])),
            "label_model_version": resolved_model_version,
            "sample_sync_mode": _manifest_is_sync(manifest_rows),
            "labeled_frames": [
                {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                for item in labeled_frames
            ],
            "processed_at": _utc_now_iso(),
        }
        payload_path = job3_root / "job3_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "labeled_frame_count": len(labeled_frames),
            "taxonomy_version": payload["taxonomy_version"],
            "label_model_version": resolved_model_version,
            "payload_relpath": f"{row['job3_relpath']}/job3_mc_payload.json",
            "frame_labels_relpath": f"{row['job3_relpath']}/frame_labels.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_label_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job3_prepare_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
    exclude_labels: list[str],
):
    def _job3_prepare_row(row):
        manifest_path = Path(mount_path) / row["manifest_relpath"]
        if not manifest_path.is_file():
            job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
            if not job2_payload_path.is_file():
                raise FileNotFoundError(
                    f"Job2 manifest not found: {manifest_path}; payload: {job2_payload_path}"
                )
            job2_payload = json.loads(job2_payload_path.read_text(encoding="utf-8"))
            manifest_rows = job2_payload.get("sampled_frames") or []
        else:
            manifest_rows = _read_jsonl(manifest_path)

        if not manifest_rows:
            raise ValueError("Job2 sample manifest is empty; run Job2 sampling first")

        taxonomy = _load_taxonomy_from_mount(
            mount_path,
            label_taxonomy_json=label_taxonomy_json,
            label_taxonomy_oss_key=label_taxonomy_oss_key,
        )
        taxonomy = _filter_taxonomy(taxonomy, exclude_labels)

        enriched: list[dict[str, Any]] = []
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        for frame in manifest_rows:
            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            image_path = _resolve_frame_image_path(parsed_root, frame)
            enriched.append(
                {
                    **frame,
                    "frame_id": _frame_id(camera, frame_idx),
                    "image_relpath": str(frame.get("image_relpath") or frame.get("image_path") or ""),
                    "image_exists": image_path.is_file(),
                }
            )

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "job3_relpath": row["job3_relpath"],
            "manifest_json": json.dumps(enriched, ensure_ascii=False),
            "taxonomy_json": json.dumps(taxonomy, ensure_ascii=False),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_prepare_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job3_encode_frame_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job3_encode_frame_row(row):
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        frame = {
            "camera": row["camera"],
            "frame_idx": int(row["frame_idx"]),
            "image_relpath": row["image_relpath"],
            "image_path": row.get("image_path") or row["image_relpath"],
        }
        image_path = _resolve_frame_image_path(parsed_root, frame)
        if not image_path.is_file():
            raise FileNotFoundError(f"Sampled frame image not found: {image_path}")
        return {
            "frame_id": row["frame_id"],
            "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_encode_frame_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _parallel_encode_frame_images(
    manifest_rows: list[dict[str, Any]],
    *,
    parsed_relpath: str,
    encode_partitions: int,
    encode_udf,
) -> list[dict[str, Any]]:
    if not manifest_rows:
        return manifest_rows
    rows = [
        {
            "frame_id": frame["frame_id"],
            "camera": frame["camera"],
            "frame_idx": int(frame["frame_idx"]),
            "image_relpath": frame["image_relpath"],
            "image_path": frame.get("image_path") or frame["image_relpath"],
            "parsed_relpath": parsed_relpath,
        }
        for frame in manifest_rows
    ]
    frame_df = md.DataFrame(pd.DataFrame(rows))
    if encode_partitions > 1 and len(rows) > 1:
        frame_df = frame_df.mf.rebalance(num_partitions=min(encode_partitions, len(rows)))
    encoded = frame_df.apply(
        encode_udf,
        axis=1,
        output_type="dataframe",
        result_type="expand",
        dtypes={"frame_id": "string", "image_base64": "string"},
        skip_infer=True,
    ).execute().fetch()
    b64_by_id = {
        str(row["frame_id"]): str(row["image_base64"])
        for _, row in encoded.iterrows()
    }
    merged: list[dict[str, Any]] = []
    for frame in manifest_rows:
        frame_id = str(frame["frame_id"])
        image_b64 = b64_by_id.get(frame_id, "")
        if not image_b64:
            raise ValueError(f"Missing base64 for frame_id={frame_id}")
        merged.append({**frame, "image_base64": image_b64})
    return merged


def _build_job3_write_payload_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job3_write_payload_row(row):
        labeled_frames = json.loads(str(row["labeled_frames_json"]))
        job3_root = Path(mount_path) / row["job3_relpath"]
        job3_root.mkdir(parents=True, exist_ok=True)

        frame_labels_path = job3_root / "frame_labels.jsonl"
        with frame_labels_path.open("w", encoding="utf-8") as labels_file:
            for item in labeled_frames:
                row_out = {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                if item.get("sync_group_id"):
                    row_out["sync_group_id"] = item["sync_group_id"]
                    row_out["anchor_timestamp_ns"] = item.get("anchor_timestamp_ns")
                    row_out["label_scope"] = item.get("label_scope") or "sync_group"
                labels_file.write(json.dumps(row_out, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "taxonomy_version": row["taxonomy_version"],
            "taxonomy_label_count": int(row["taxonomy_label_count"]),
            "label_model_version": row["label_model_version"],
            "sample_sync_mode": str(row.get("sample_sync_mode") or "").strip().lower() in ("1", "true", "yes"),
            "labeled_frames": labeled_frames,
            "processed_at": _utc_now_iso(),
        }
        payload_path = job3_root / "job3_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "labeled_frame_count": len(labeled_frames),
            "taxonomy_version": row["taxonomy_version"],
            "label_model_version": row["label_model_version"],
            "payload_relpath": f"{row['job3_relpath']}/job3_mc_payload.json",
            "frame_labels_relpath": f"{row['job3_relpath']}/frame_labels.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_write_payload_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _labeled_frames_from_sync_ai(
    sync_groups: list[dict[str, Any]],
    ai_results: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    resolved_version = model_version or ("none" if not model else model)
    labeled: list[dict[str, Any]] = []
    for group, ai_result in zip(sync_groups, ai_results):
        values = ai_result.get("values") if isinstance(ai_result, dict) else {}
        if not isinstance(values, dict):
            values = {}
        anchor_ns = int(group.get("anchor_timestamp_ns") or 0)
        values = apply_l1_time_label_overrides(
            values,
            anchor_ns,
            timezone=label_timezone,
        )
        sync_group_id = str(group.get("sync_group_id") or "")
        labels_payload = {
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "provider": "maxframe_ai_function",
            "model_version": resolved_version,
            "status": str(ai_result.get("status") or "ok"),
            "label_scope": "sync_group",
            "sync_group_id": sync_group_id,
            "values": values,
        }
        for frame in group.get("frames") or []:
            labeled.append(
                {
                    "frame_id": frame["frame_id"],
                    "camera": frame["camera"],
                    "frame_idx": frame["frame_idx"],
                    "timestamp_ns": frame["timestamp_ns"],
                    "anchor_timestamp_ns": anchor_ns,
                    "sync_group_id": sync_group_id,
                    "label_scope": "sync_group",
                    "image_relpath": frame["image_relpath"],
                    "labels_json": dict(labels_payload),
                }
            )
    return labeled


def _labeled_frames_from_ai(
    manifest_rows: list[dict[str, Any]],
    ai_results: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    resolved_version = model_version or ("none" if not model else model)
    labeled: list[dict[str, Any]] = []
    for frame, ai_result in zip(manifest_rows, ai_results):
        values = ai_result.get("values") if isinstance(ai_result, dict) else {}
        if not isinstance(values, dict):
            values = {}
        values = apply_l1_time_label_overrides(
            values,
            int(frame["timestamp_ns"]),
            timezone=label_timezone,
        )
        labels_payload = {
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "provider": "maxframe_ai_function",
            "model_version": resolved_version,
            "status": str(ai_result.get("status") or "ok"),
            "values": values,
        }
        labeled.append(
            {
                "frame_id": frame["frame_id"],
                "camera": frame["camera"],
                "frame_idx": frame["frame_idx"],
                "timestamp_ns": frame["timestamp_ns"],
                "image_relpath": frame["image_relpath"],
                "labels_json": labels_payload,
            }
        )
    return labeled


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job3_label"):
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

    job3_config = load_job3_config()
    label_model = get_arg("label_model") or str(job3_config.get("model") or "")
    label_model_version = get_arg("label_model_version") or str(job3_config.get("model_version") or "")
    label_batch_size = get_int_arg("label_batch_size", int(job3_config.get("batch_size", 32)))
    label_timezone = (
        get_arg("label_timezone")
        or str(job3_config.get("label_timezone") or DEFAULT_LABEL_TIMEZONE)
    ).strip()
    label_taxonomy_json = get_arg("label_taxonomy_json") or ""
    label_taxonomy_oss_key = (
        get_arg("label_taxonomy_oss_key")
        or str(job3_config.get("label_taxonomy_oss_key") or DEFAULT_JOB3_CONFIG["label_taxonomy_oss_key"])
    )
    exclude_raw = get_arg("exclude_labels")
    if exclude_raw:
        exclude_labels = [item.strip() for item in exclude_raw.split(",") if item.strip()]
    else:
        exclude_labels = list(job3_config.get("exclude_labels") or [])

    ai_modelset_project = get_arg("ai_modelset_project") or "bigdata_public_modelset"
    ai_parallel_partitions = get_int_arg("ai_parallel_partitions", 8)
    total_rpm_limit = get_int_arg("total_rpm_limit", 12000)
    request_timeout = get_int_arg("request_timeout", 300)
    ai_memory = get_arg("ai_memory", "8G") or ""
    ai_cu_quota_name = get_arg("ai_cu_quota_name")
    ai_gu_quota_name = get_arg("ai_gu_quota_name")
    label_image_mode = get_arg("label_image_mode", "auto") or "auto"
    oss_vl_access_key_id, oss_vl_access_key_secret = _resolve_oss_vl_ak_sk()
    label_prompt_compact_raw = get_arg("label_prompt_compact", "true") or "true"
    label_prompt_compact = label_prompt_compact_raw.strip().lower() not in ("0", "false", "no")
    vl_storage_options = (
        build_vl_oss_storage_options(
            role_arn=role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "build_vl_oss_storage_options" in globals()
        else None
    )
    resolved_image_mode = (
        resolve_label_image_mode(
            label_image_mode,
            role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "resolve_label_image_mode" in globals()
        else (
            "oss_url"
            if (oss_vl_access_key_id and oss_vl_access_key_secret)
            else "base64"
        )
    )

    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    parsed_relpath = f"{clip_prefix}/runs/{run_id}/parsed"
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"
    job3_relpath = f"{clip_prefix}/runs/{run_id}/job3"

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.local_execution.enabled = False

    if label_model and "prepare_mf_ai_runtime" in globals():
        prepare_mf_ai_runtime(
            model_name=label_model,
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
        "manifest_relpath": f"{job2_relpath}/sample_manifest.jsonl",
        "job2_payload_relpath": f"{job2_relpath}/job2_sample_payload.json",
        "job3_relpath": job3_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    try:
        print(f"Logview: {session.get_logview_address()}")
        if not label_taxonomy_json and label_taxonomy_oss_key:
            print(f"Job3 taxonomy OSS key: {label_taxonomy_oss_key} (upload yaml to bucket or pass label_taxonomy_json)")

        if label_model:
            if "ai_label_frames_with_model" not in globals():
                raise RuntimeError(
                    "mf_ai_function not loaded. DataWorks 请粘贴 "
                    "dataworks/bundled/job3_label_node.py（非 job3_label_node.py）。"
                    "本地生成: python scripts/bundle_dataworks_node.py dataworks/job3_label_node.py"
                )
            print(f"Job3 MaxFrame AI Function model={label_model}")

            _job3_prepare_row = _build_job3_prepare_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                label_taxonomy_json=label_taxonomy_json,
                label_taxonomy_oss_key=label_taxonomy_oss_key,
                exclude_labels=exclude_labels,
            )
            prep = input_df.apply(
                _job3_prepare_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "job3_relpath": "string",
                    "manifest_json": "string",
                    "taxonomy_json": "string",
                },
                skip_infer=True,
            ).execute().fetch().iloc[0]

            manifest_rows = json.loads(str(prep["manifest_json"]))
            taxonomy = json.loads(str(prep["taxonomy_json"]))
            missing = [f for f in manifest_rows if not f.get("image_exists")]
            if missing:
                raise FileNotFoundError(
                    f"{len(missing)} sampled frame image(s) missing under parsed/ (first frame_id={missing[0].get('frame_id')})"
                )

            sync_mode = _manifest_is_sync(manifest_rows)
            sync_groups = _build_sync_groups(manifest_rows) if sync_mode else []

            if resolved_image_mode == "base64":
                encode_partitions = (
                    resolve_ai_parallel_partitions(len(manifest_rows), ai_parallel_partitions)
                    if "resolve_ai_parallel_partitions" in globals()
                    else min(len(manifest_rows), max(ai_parallel_partitions, 8))
                )
                print(
                    f"Job3 parallel base64 encode: frames={len(manifest_rows)} "
                    f"partitions={encode_partitions}"
                )
                _job3_encode_frame_row = _build_job3_encode_frame_udf(
                    dpe_cpu=dpe_cpu,
                    dpe_memory=dpe_memory,
                    oss_mount_url=oss_mount_url,
                    mount_path=mount_path,
                    storage_options=_storage_options(role_arn, account),
                )
                manifest_rows = _parallel_encode_frame_images(
                    manifest_rows,
                    parsed_relpath=parsed_relpath,
                    encode_partitions=encode_partitions,
                    encode_udf=_job3_encode_frame_row,
                )
                if sync_mode:
                    sync_groups = _build_sync_groups(manifest_rows)

            label_count = len(sync_groups) if sync_mode else len(manifest_rows)
            effective_partitions = (
                resolve_ai_parallel_partitions(label_count, ai_parallel_partitions)
                if "resolve_ai_parallel_partitions" in globals()
                else min(label_count, max(ai_parallel_partitions, 8))
            )
            vl_auth = "oss_ak_sk" if (oss_vl_access_key_id and oss_vl_access_key_secret) else "none"
            ak_hint = (
                f"{oss_vl_access_key_id[:4]}...{oss_vl_access_key_id[-4:]}"
                if len(oss_vl_access_key_id) >= 8
                else "(empty)"
            )
            print(
                f"Job3 AI label: sync_mode={sync_mode} image_mode={resolved_image_mode} vl_auth={vl_auth} "
                f"ak_hint={ak_hint} frames={len(manifest_rows)} groups={len(sync_groups)} "
                f"parallel_partitions={effective_partitions} compact_prompt={label_prompt_compact} "
                f"running_options={{total_rpm_limit={total_rpm_limit if total_rpm_limit > 0 else 'off'}, "
                f"request_timeout={request_timeout if request_timeout > 0 else 'off'}, "
                f"memory={ai_memory or 'off'}}}"
            )
            if resolved_image_mode == "oss_url" and not vl_storage_options:
                raise ValueError(
                    "label_image_mode=oss_url but OSS VL AK/SK missing. "
                    "Set oss_vl_access_key_id + oss_vl_access_key_secret "
                    f"(aliases oss_access_key_id/secret). "
                    f"Resolved arg keys: {sorted(_all_arg_sources().keys())}"
                )

            if sync_mode:
                if "ai_label_sync_groups_with_model" not in globals():
                    raise RuntimeError(
                        "sync sample policy requires ai_label_sync_groups_with_model in mf_ai_function"
                    )
                ai_results = ai_label_sync_groups_with_model(
                    sync_groups,
                    label_model,
                    o,  # type: ignore[name-defined]
                    taxonomy=taxonomy,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                    storage_options=vl_storage_options,
                    role_arn=role_arn,
                    modelset_project=ai_modelset_project,
                    parallel_partitions=effective_partitions,
                    parsed_relpath=parsed_relpath,
                    compact_prompt=label_prompt_compact,
                    total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                    request_timeout=request_timeout if request_timeout > 0 else None,
                    ai_memory=ai_memory.strip() if ai_memory.strip() else None,
                )
                labeled_frames = _labeled_frames_from_sync_ai(
                    sync_groups,
                    ai_results,
                    taxonomy=taxonomy,
                    model=label_model,
                    model_version=label_model_version,
                    label_timezone=label_timezone,
                )
            else:
                ai_results = ai_label_frames_with_model(
                    manifest_rows,
                    label_model,
                    o,  # type: ignore[name-defined]
                    taxonomy=taxonomy,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                    storage_options=vl_storage_options,
                    role_arn=role_arn,
                    modelset_project=ai_modelset_project,
                    parallel_partitions=effective_partitions,
                    parsed_relpath=parsed_relpath,
                    compact_prompt=label_prompt_compact,
                    total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                    request_timeout=request_timeout if request_timeout > 0 else None,
                    ai_memory=ai_memory.strip() if ai_memory.strip() else None,
                )
                labeled_frames = _labeled_frames_from_ai(
                    manifest_rows,
                    ai_results,
                    taxonomy=taxonomy,
                    model=label_model,
                    model_version=label_model_version,
                    label_timezone=label_timezone,
                )
            resolved_model_version = label_model_version or label_model

            _job3_write_payload_row = _build_job3_write_payload_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
            )
            write_df = md.DataFrame(
                pd.DataFrame(
                    [
                        {
                            "clip_id": clip_id,
                            "run_id": run_id,
                            "job3_relpath": job3_relpath,
                            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
                            "taxonomy_label_count": int(
                                taxonomy.get("label_count") or len(taxonomy.get("labels") or [])
                            ),
                            "label_model_version": resolved_model_version,
                            "sample_sync_mode": sync_mode,
                            "labeled_frames_json": json.dumps(labeled_frames, ensure_ascii=False),
                        }
                    ]
                )
            )
            row = write_df.apply(
                _job3_write_payload_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "labeled_frame_count": "int64",
                    "taxonomy_version": "string",
                    "label_model_version": "string",
                    "payload_relpath": "string",
                    "frame_labels_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch().iloc[0]
        else:
            print("WARN: label_model empty; writing OMS-shaped labels_json with empty values (stub mode)")
            _job3_label_row = _build_job3_label_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                job3_config=job3_config,
                label_taxonomy_json=label_taxonomy_json,
                label_taxonomy_oss_key=label_taxonomy_oss_key,
                exclude_labels=exclude_labels,
                label_model=label_model,
                label_model_version=label_model_version,
                label_batch_size=label_batch_size,
                label_timezone=label_timezone,
            )
            result = input_df.apply(
                _job3_label_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "labeled_frame_count": "int64",
                    "taxonomy_version": "string",
                    "label_model_version": "string",
                    "payload_relpath": "string",
                    "frame_labels_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch()
            if result.empty:
                raise RuntimeError("Job3 label returned no rows")
            row = result.iloc[0]

        print(
            f"Job3 label done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"labeled_frames={row['labeled_frame_count']} "
            f"taxonomy={row['taxonomy_version']} model={row['label_model_version']} "
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
