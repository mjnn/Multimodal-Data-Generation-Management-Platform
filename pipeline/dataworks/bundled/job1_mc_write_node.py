from __future__ import annotations

# job1_mc_write_node.py — paste this single file into DataWorks PyODPS3

# === BEGIN mc_write_idempotent.py (auto-bundled) ===
"""Idempotent MaxCompute partition writes for Job1~4 mc_write nodes.

DataWorks paste: run `python scripts/bundle_mc_write_node.py dataworks/jobN_mc_write_node.py`
"""


from typing import Any


def sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def purge_partition_rows(
    client: Any,
    *,
    table_name: str,
    ds: str,
    columns: str,
    exclude_where: str,
) -> None:
    """INSERT OVERWRITE ds partition, excluding rows matching exclude_where."""
    safe_ds = ds.replace("'", "''")
    sql = f"""
INSERT OVERWRITE TABLE {table_name} PARTITION (ds={sql_string_literal(safe_ds)})
SELECT {columns}
FROM {table_name}
WHERE ds = {sql_string_literal(safe_ds)}
  AND NOT ({exclude_where})
"""
    client.execute_sql(sql).wait_for_success()


def purge_clip_run_rows(
    client: Any,
    *,
    table_name: str,
    ds: str,
    clip_id: str,
    run_id: str,
    columns: str,
) -> None:
    exclude_where = (
        f"clip_id = {sql_string_literal(clip_id)} "
        f"AND run_id = {sql_string_literal(run_id)}"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )


def purge_pipeline_step_run(
    client: Any,
    *,
    table_name: str,
    ds: str,
    run_id: str,
    step_id: str,
) -> None:
    columns = "run_id, step_id, status, started_at, finished_at, error_message"
    exclude_where = (
        f"run_id = {sql_string_literal(run_id)} "
        f"AND step_id = {sql_string_literal(step_id)}"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )


def purge_pipeline_steps_run(
    client: Any,
    *,
    table_name: str,
    ds: str,
    run_id: str,
    step_ids: tuple[str, ...],
) -> None:
    if not step_ids:
        return
    columns = "run_id, step_id, status, started_at, finished_at, error_message"
    step_clause = ", ".join(sql_string_literal(step_id) for step_id in step_ids)
    exclude_where = (
        f"run_id = {sql_string_literal(run_id)} "
        f"AND step_id IN ({step_clause})"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )
# === END mc_write_idempotent.py ===

# === BEGIN pipeline_dispatch.py (auto-bundled) ===
"""Pipeline dispatch: pick clip/run for scheduled DataWorks workflow.

**Primary (all DW editions):** ``job0_dispatch`` writes ``pipeline/dispatch/latest.json``
on OSS; downstream PyODPS nodes call ``resolve_pipeline_context()`` to read it.
No assignment node or node-context output params required.

Optional: hand-set ``clip_id``/``run_id`` in a node's parameter panel for single-clip debug.
Optional (DataWorks Standard+): assignment node + ``dispatch_json`` in args.
"""


import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import oss2
except ImportError:  # pragma: no cover - DataWorks driver often lacks oss2
    oss2 = None  # type: ignore[assignment]

try:
    import alibabacloud_oss_v2 as oss_v2
except ImportError:  # pragma: no cover
    oss_v2 = None  # type: ignore[assignment]

REQUIRED_PIPELINE_STEPS: tuple[str, ...] = (
    "job1_parse",
    "job2_sample",
    "job2_asr",
    "job3_label",
    "job4_embed",
)

DEFAULT_DISPATCH_OSS_KEY = "pipeline/dispatch/latest.json"

DISPATCH_OUTPUT_KEYS: tuple[str, ...] = (
    "action",
    "reason",
    "clip_id",
    "run_id",
    "clip_dir_name",
    "bag_oss_key",
)


_UNRESOLVED_DW_PLACEHOLDER = re.compile(r"^\$\{[^}]+\}$")


def is_unresolved_dw_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    return bool(_UNRESOLVED_DW_PLACEHOLDER.match(str(value).strip()))


def read_skynet_task_input() -> dict[str, str]:
    """Read DataWorks node-context inputs from SKYNET_TASK_INPUT."""
    raw = (os.environ.get("SKYNET_TASK_INPUT") or "").strip()
    if not raw or raw == "{}":
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in loaded.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        resolved[str(key)] = text
    return resolved


def read_pyodps_args() -> dict[str, str]:
    """Read resolved scheduling / node-context values injected into global ``args``."""
    try:
        node_args = args  # type: ignore[name-defined]
    except NameError:
        return {}
    if not isinstance(node_args, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in node_args.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        resolved[str(key)] = text
    return resolved


def resolve_node_param(
    name: str,
    get_arg: Callable[[str, str | None], str | None],
    default: str | None = None,
) -> str | None:
    """Resolve one param from args, SKYNET_TASK_INPUT, then get_arg (skip unresolved ${...})."""
    for candidate in (
        read_pyodps_args().get(name),
        read_skynet_task_input().get(name),
        get_arg(name, default),
    ):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        return text
    return default if default is not None else None


def _sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_ds(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def resolve_dispatch_ds(
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> str | None:
    ds = ""
    if get_arg is not None:
        ds = (resolve_node_param("ds", get_arg, "") or "").strip()
    if not ds or is_unresolved_dw_placeholder(ds) or ds.lower() == "bizdate":
        ds = (os.environ.get("SKYNET_BIZDATE") or "").strip()
    return ds if ds and _is_valid_ds(ds) else None


def _partition_ds_value(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.startswith("ds="):
        return part_name.split("=", 1)[1].strip().strip("'").strip('"')
    return part_name


def _list_ds_partitions_client(client: Any, table_name: str) -> list[str]:
    if not client.exist_table(table_name):
        return []
    table = client.get_table(table_name)
    if not table.table_schema.partitions:
        return []
    values = {_partition_ds_value(str(part.name)) for part in table.partitions}
    return sorted((v for v in values if _is_valid_ds(v)), reverse=True)


def _pipeline_step_ds_predicate(
    client: Any,
    table_name: str,
    get_arg: Callable[[str, str | None], str | None] | None,
) -> str:
    parts = _list_ds_partitions_client(client, table_name)
    if parts:
        recent = parts[:32]
        if len(recent) == 1:
            return f"ds = {_sql_string_literal(recent[0])}"
        in_list = ", ".join(_sql_string_literal(p) for p in recent)
        return f"ds IN ({in_list})"
    ds = resolve_dispatch_ds(get_arg)
    if not ds:
        raise ValueError(
            "pipeline_step query requires ds partition; set workflow ds=${bizdate} "
            "or rely on SKYNET_BIZDATE"
        )
    return f"ds = {_sql_string_literal(ds)}"


def is_pipeline_run_complete(
    client: Any,
    table_prefix: str,
    run_id: str,
    *,
    required_steps: tuple[str, ...] = REQUIRED_PIPELINE_STEPS,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> bool:
    if not run_id:
        return False
    table_name = f"{table_prefix}pipeline_step"
    ds_pred = _pipeline_step_ds_predicate(client, table_name, get_arg)
    sql = (
        f"SELECT step_id, MAX(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok "
        f"FROM {table_name} WHERE run_id = {_sql_string_literal(run_id)} "
        f"AND {ds_pred} "
        f"GROUP BY step_id"
    )
    completed: set[str] = set()
    with client.execute_sql(sql).open_reader() as reader:
        for row in reader:
            step_id = str(row[0])
            if int(row[1]) == 1:
                completed.add(step_id)
    return all(step in completed for step in required_steps)


def list_dim_clips(client: Any, table_prefix: str) -> list[dict[str, Any]]:
    table_name = f"{table_prefix}dim_clip"
    sql = (
        f"SELECT clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, created_at "
        f"FROM {table_name} ORDER BY created_at ASC"
    )
    rows: list[dict[str, Any]] = []
    with client.execute_sql(sql).open_reader() as reader:
        for record in reader:
            rows.append(
                {
                    "clip_id": str(record[0]),
                    "clip_dir_name": str(record[1] or ""),
                    "content_hash": str(record[2] or ""),
                    "bag_oss_key": str(record[3] or ""),
                    "active_run_id": str(record[4] or "") or None,
                    "created_at": str(record[5] or ""),
                }
            )
    return rows


def pick_dispatch_target(
    client: Any,
    table_prefix: str,
    *,
    required_steps: tuple[str, ...] = REQUIRED_PIPELINE_STEPS,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any]:
    """Return dispatch payload with action=run|idle."""
    for clip in list_dim_clips(client, table_prefix):
        clip_id = clip["clip_id"]
        active_run_id = clip.get("active_run_id")
        if active_run_id and is_pipeline_run_complete(
            client,
            table_prefix,
            active_run_id,
            required_steps=required_steps,
            get_arg=get_arg,
        ):
            continue
        if active_run_id:
            run_id = active_run_id
            reason = "resume_incomplete"
        else:
            run_id = str(uuid.uuid4())
            reason = "new_run"
        return {
            "action": "run",
            "reason": reason,
            "clip_id": clip_id,
            "run_id": run_id,
            "clip_dir_name": clip.get("clip_dir_name") or "",
            "bag_oss_key": clip.get("bag_oss_key") or "",
            "content_hash": clip.get("content_hash") or "",
            "active_run_id_before": active_run_id,
            "dispatched_at": utc_now_iso(),
        }
    return {
        "action": "idle",
        "reason": "no_pending_clip",
        "clip_id": "",
        "run_id": "",
        "clip_dir_name": "",
        "bag_oss_key": "",
        "dispatched_at": utc_now_iso(),
    }


def _normalize_oss_region(region: str) -> str:
    return region.replace("_", "-")


def default_oss_http_endpoint(region: str, *, use_internal: bool = True) -> str:
    """Regional OSS HTTP endpoint; DataWorks/MaxCompute should use internal by default."""
    region_id = _normalize_oss_region(region)
    internal_suffix = "-internal" if use_internal else ""
    return f"https://oss-{region_id}{internal_suffix}.aliyuncs.com"


def resolve_oss_http_endpoint(
    region: str,
    get_arg: Callable[[str, str | None], str | None] | None = None,
    *,
    explicit_endpoint: str | None = None,
) -> str:
    endpoint = (explicit_endpoint or "").strip()
    if not endpoint and get_arg is not None:
        endpoint = (resolve_node_param("oss_endpoint", get_arg, "") or "").strip()
    if endpoint:
        return endpoint
    use_internal = True
    if get_arg is not None:
        raw = resolve_node_param("oss_use_internal", get_arg, "true") or "true"
        use_internal = str(raw).lower() not in {"0", "false", "no"}
    return default_oss_http_endpoint(region, use_internal=use_internal)


def _oss_credentials(account: Any) -> tuple[str, str]:
    access_id = getattr(account, "access_id", None) or getattr(account, "access_key_id", None)
    secret = getattr(account, "secret_access_key", None) or getattr(account, "access_key_secret", None)
    if not access_id or not secret:
        raise RuntimeError("OSS credentials missing on ODPS account")
    return str(access_id), str(secret)


def _account_security_token(account: Any) -> str:
    for attr in ("sts_token", "security_token", "token"):
        value = getattr(account, attr, None)
        if value:
            return str(value)
    return ""


def resolve_dispatch_oss_credentials(
    account: Any,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> tuple[str, str, str]:
    """Return (access_key_id, access_key_secret, security_token). Token may be empty."""
    if get_arg is not None:
        ak = (
            resolve_node_param("oss_vl_access_key_id", get_arg, "")
            or resolve_node_param("oss_access_key_id", get_arg, "")
            or ""
        ).strip()
        sk = (
            resolve_node_param("oss_vl_access_key_secret", get_arg, "")
            or resolve_node_param("oss_access_key_secret", get_arg, "")
            or ""
        ).strip()
        if ak and sk and not ak.startswith("STS."):
            return ak, sk, ""
    access_id, secret = _oss_credentials(account)
    token = _account_security_token(account)
    if access_id.startswith("STS.") and not token:
        raise RuntimeError(
            "OSS STS credentials from o.account require security_token; "
            "set oss_vl_access_key_id + oss_vl_access_key_secret in workflow params"
        )
    return access_id, secret, token


def _make_oss_v2_client(
    access_key_id: str,
    access_key_secret: str,
    *,
    region: str,
    endpoint: str | None = None,
    security_token: str | None = None,
) -> Any:
    if oss_v2 is None:
        raise RuntimeError("alibabacloud_oss_v2 is required for OSS dispatch I/O")
    cfg = oss_v2.config.load_default()
    if security_token:
        cfg.credentials_provider = oss_v2.credentials.StaticCredentialsProvider(
            access_key_id,
            access_key_secret,
            security_token,
        )
    else:
        cfg.credentials_provider = oss_v2.credentials.StaticCredentialsProvider(
            access_key_id,
            access_key_secret,
        )
    cfg.region = _normalize_oss_region(region)
    if endpoint:
        cfg.endpoint = endpoint
    return oss_v2.Client(cfg)


def _is_oss_object_missing(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    code = str(getattr(exc, "code", "") or "")
    if code in {"NoSuchKey", "NotFound"}:
        return True
    text = str(exc)
    return any(token in text for token in ("NoSuchKey", "404", "Not Found", "not found"))


def write_dispatch_to_oss(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    payload: dict[str, Any],
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    access_id, secret, token = resolve_dispatch_oss_credentials(account, get_arg=get_arg)
    if oss2 is not None:
        auth = (
            oss2.StsAuth(access_id, secret, token)
            if token
            else oss2.Auth(access_id, secret)
        )
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.put_object(object_key, body)
        return
    if oss_v2 is None:
        raise RuntimeError("oss2 or alibabacloud_oss_v2 is required to write dispatch payload")
    client = _make_oss_v2_client(
        access_id,
        secret,
        region=region or "cn-shanghai",
        endpoint=endpoint,
        security_token=token or None,
    )
    client.put_object(
        oss_v2.PutObjectRequest(
            bucket=bucket_name,
            key=object_key,
            body=body,
        )
    )


def read_oss_object_bytes(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> bytes | None:
    """Read one OSS object on the DataWorks driver (no MaxFrame 8MB STRING tunnel limit)."""
    access_id, secret, token = resolve_dispatch_oss_credentials(account, get_arg=get_arg)
    if oss2 is not None:
        auth = (
            oss2.StsAuth(access_id, secret, token)
            if token
            else oss2.Auth(access_id, secret)
        )
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        try:
            return bucket.get_object(object_key).read()
        except oss2.exceptions.NoSuchKey:
            return None
        except oss2.exceptions.NotFound:
            return None
    if oss_v2 is not None:
        client = _make_oss_v2_client(
            access_id,
            secret,
            region=region or "cn-shanghai",
            endpoint=endpoint,
            security_token=token or None,
        )
        try:
            result = client.get_object(
                oss_v2.GetObjectRequest(bucket=bucket_name, key=object_key)
            )
            with result.body as stream:
                return stream.read()
        except Exception as exc:
            if _is_oss_object_missing(exc):
                return None
            raise
    raise RuntimeError("oss2 or alibabacloud_oss_v2 is required to read OSS objects")


def read_oss_object_text(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> str | None:
    raw = read_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if raw is None:
        return None
    return raw.decode("utf-8")


def read_oss_json_object(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any] | None:
    text = read_oss_object_text(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if text is None:
        return None
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else None


def read_dispatch_from_oss(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any] | None:
    raw = read_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if raw is None:
        return None
    loaded = json.loads(raw.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else None


def write_dispatch_to_mc(
    client: Any,
    table_prefix: str,
    *,
    ds: str,
    payload: dict[str, Any],
) -> None:
    """Persist dispatch payload for the ODPS SQL assignment node (``job0_dispatch_out``)."""
    table_name = f"{table_prefix}dispatch_staging"
    row = {
        "action": str(payload.get("action") or ""),
        "reason": str(payload.get("reason") or ""),
        "clip_id": str(payload.get("clip_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "clip_dir_name": str(payload.get("clip_dir_name") or ""),
        "bag_oss_key": str(payload.get("bag_oss_key") or ""),
        "dispatched_at": str(payload.get("dispatched_at") or utc_now_iso()),
    }
    sql = (
        f"INSERT OVERWRITE TABLE {table_name} PARTITION (ds={_sql_string_literal(ds)}) "
        f"SELECT "
        f"{_sql_string_literal(row['action'])}, "
        f"{_sql_string_literal(row['reason'])}, "
        f"{_sql_string_literal(row['clip_id'])}, "
        f"{_sql_string_literal(row['run_id'])}, "
        f"{_sql_string_literal(row['clip_dir_name'])}, "
        f"{_sql_string_literal(row['bag_oss_key'])}, "
        f"{_sql_string_literal(row['dispatched_at'])}"
    )
    client.execute_sql(sql).wait_for_success()


def dispatch_payload_from_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text or is_unresolved_dw_placeholder(text):
        return None
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def log_dataworks_args(*, label: str = "resolve_pipeline_context") -> None:
    """Print how DataWorks injected scheduler / node-context params (diagnostic)."""
    try:
        node_args = args  # type: ignore[name-defined]
    except NameError:
        node_args = {}
    keys = sorted(node_args.keys()) if isinstance(node_args, dict) else []
    print(
        f"{label}: args_keys={keys} "
        f"SKYNET_TASK_INPUT={os.environ.get('SKYNET_TASK_INPUT', '')}"
    )


def _idle_context(*, action: str, reason: str, source: str) -> dict[str, Any]:
    return {
        "should_run": False,
        "action": action or "idle",
        "reason": reason,
        "clip_id": "",
        "run_id": "",
        "clip_dir_name": "",
        "bag_oss_key": "",
        "source": source,
    }


def _run_context(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    clip_id = str(payload.get("clip_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if not clip_id or not run_id:
        raise ValueError(f"Invalid dispatch payload (missing clip_id/run_id): {payload!r}")
    return {
        "should_run": True,
        "action": "run",
        "clip_id": clip_id,
        "run_id": run_id,
        "clip_dir_name": str(payload.get("clip_dir_name") or "").strip(),
        "bag_oss_key": str(payload.get("bag_oss_key") or "").strip(),
        "reason": str(payload.get("reason") or ""),
        "source": source,
    }


def _load_dispatch_from_oss(
    get_arg: Callable[[str, str | None], str | None],
    *,
    oss_account: Any,
    oss_bucket: str | None,
    oss_endpoint: str | None,
) -> dict[str, Any] | None:
    dispatch_key = (
        resolve_node_param("dispatch_oss_key", get_arg, DEFAULT_DISPATCH_OSS_KEY)
        or DEFAULT_DISPATCH_OSS_KEY
    ).strip()
    bucket = (oss_bucket or resolve_node_param("oss_bucket", get_arg, "") or "").strip()
    if not bucket:
        return None
    region = resolve_node_param("cloud_region", get_arg, "cn_shanghai") or "cn_shanghai"
    endpoint = (oss_endpoint or resolve_node_param("oss_endpoint", get_arg, "") or "").strip()
    if not endpoint:
        endpoint = resolve_oss_http_endpoint(region, get_arg=get_arg)
    return read_dispatch_from_oss(
        bucket_name=bucket,
        object_key=dispatch_key,
        endpoint=endpoint,
        account=oss_account,
        region=region,
        get_arg=get_arg,
    )


def resolve_pipeline_context(
    get_arg: Callable[[str, str | None], str | None],
    *,
    odps_client: Any | None = None,
    oss_account: Any | None = None,
    oss_endpoint: str | None = None,
    oss_bucket: str | None = None,
) -> dict[str, Any]:
    """Resolve clip_id/run_id from node args (debug) or OSS dispatch manifest (primary)."""
    log_dataworks_args()

    action = (resolve_node_param("action", get_arg, "") or "").strip().lower()
    clip_id = (resolve_node_param("clip_id", get_arg, "") or "").strip()
    run_id = (resolve_node_param("run_id", get_arg, "") or "").strip()
    clip_dir_name = (resolve_node_param("clip_dir_name", get_arg, "") or "").strip()
    bag_oss_key = (resolve_node_param("bag_oss_key", get_arg, "") or "").strip()

    if action == "idle":
        return _idle_context(
            action="idle",
            reason=(resolve_node_param("reason", get_arg, "idle") or "idle").strip(),
            source="node_params",
        )

    if clip_id and not run_id:
        run_id = str(uuid.uuid4())
    if clip_id and run_id:
        return {
            "should_run": True,
            "action": "run",
            "clip_id": clip_id,
            "run_id": run_id,
            "clip_dir_name": clip_dir_name,
            "bag_oss_key": bag_oss_key,
            "source": "node_params",
        }

    dispatch_key = (
        resolve_node_param("dispatch_oss_key", get_arg, DEFAULT_DISPATCH_OSS_KEY)
        or DEFAULT_DISPATCH_OSS_KEY
    ).strip()
    bucket = (oss_bucket or resolve_node_param("oss_bucket", get_arg, "") or "").strip()

    if oss_account and bucket:
        region = resolve_node_param("cloud_region", get_arg, "cn_shanghai") or "cn_shanghai"
        endpoint_for_log = resolve_oss_http_endpoint(
            region,
            get_arg=get_arg,
            explicit_endpoint=oss_endpoint,
        )
        print(
            f"resolve_pipeline_context: no clip_id in args; reading OSS "
            f"oss://{bucket}/{dispatch_key} via {endpoint_for_log}"
        )
        payload = _load_dispatch_from_oss(
            get_arg,
            oss_account=oss_account,
            oss_bucket=bucket,
            oss_endpoint=oss_endpoint,
        )
        if payload:
            print(f"resolve_pipeline_context: loaded dispatch from OSS (action={payload.get('action')})")
            oss_action = str(payload.get("action") or "").strip().lower()
            if oss_action != "run":
                return _idle_context(
                    action=oss_action or "idle",
                    reason=str(payload.get("reason") or "idle"),
                    source="dispatch_oss",
                )
            return _run_context(payload, source="dispatch_oss")

    dispatch_json = (
        resolve_node_param("dispatch_json", get_arg, "")
        or resolve_node_param("outputs", get_arg, "")
        or ""
    ).strip()
    json_payload = dispatch_payload_from_json(dispatch_json)
    if json_payload:
        oss_action = str(json_payload.get("action") or "").strip().lower()
        if oss_action != "run":
            return _idle_context(
                action=oss_action or "idle",
                reason=str(json_payload.get("reason") or "idle"),
                source="dispatch_json",
            )
        return _run_context(json_payload, source="dispatch_json")

    raw_task_input = (os.environ.get("SKYNET_TASK_INPUT") or "").strip()
    pyodps_args = read_pyodps_args()
    if not bucket or not oss_account:
        raise ValueError(
            "clip_id/run_id empty: set node params for manual run, or ensure "
            "oss_bucket is configured and job0_dispatch ran first"
        )
    if raw_task_input and "${" in raw_task_input:
        raise ValueError(
            "Dispatch OSS manifest missing and node context unresolved "
            f"(SKYNET_TASK_INPUT={raw_task_input}, args_keys={sorted(pyodps_args.keys())}). "
            "Run job0_dispatch_node first (writes "
            f"oss://{bucket}/{dispatch_key}), then job1_parse in the same workflow. "
            "Do not rely on PyODPS node output params for clip_id; remove write_dispatch_oss=false."
        )
    raise ValueError(
        f"Dispatch OSS manifest missing: oss://{bucket}/{dispatch_key}. "
        "Run job0_dispatch_node in the same workflow before downstream nodes."
    )


def exit_if_pipeline_idle(ctx: dict[str, Any], *, node_name: str = "") -> bool:
    """Print idle marker and return True if caller should exit main() successfully."""
    if ctx.get("should_run"):
        return False
    label = f" {node_name}" if node_name else ""
    print(
        f"PIPELINE_IDLE{label}: action={ctx.get('action')} reason={ctx.get('reason')} "
        f"(skip downstream work until next schedule)"
    )
    return True
# === END pipeline_dispatch.py ===

# =============================================================================
# DataWorks PyODPS 3 节点：Job1-写MC（节点 2/2，Driver）
# 粘贴整文件到 PyODPS3 节点；依赖 pyodps、alibabacloud_oss_v2（或 oss2）。
#
# 流程：Driver 经 OSS SDK 读 job1_mc_payload.json → 写 aig_rosbag__*
# 禁止经 MaxFrame 回传整份 payload（ODPS STRING 上限 8MB，大 clip 会 Tunnel 失败）
# 幂等：同 ds 分区下先 INSERT OVERWRITE 去掉本 (clip_id, run_id) 旧行再 append
# DataWorks 粘贴：python scripts/bundle_mc_write_node.py dataworks/job1_mc_write_node.py
#
# 工作流参数：
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   table_prefix=aig_rosbag__
#   oss_prefix_template=clips/{clip_id}/
#   oss_ram_role_arn=              # 推荐；留空则用 o.account AK/SK
#   oss_mount_prefix=
#   dpe_cpu=1
#   dpe_memory_gb=4
#   dpe_mount_path=/mnt/oss
#   ds=${bizdate}
#
# 节点参数：
#   clip_id=sha256:...
#   run_id=<uuid>
# =============================================================================


import json
import os
import re
from datetime import datetime, timezone
from typing import Any



_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
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


def _resolve_ds() -> str:
    ds = get_arg("ds") or get_arg("bizdate") or ""
    if not ds or "${" in ds:
        ds = os.environ.get("SKYNET_BIZDATE", "").strip()
    if not ds:
        raise ValueError(
            "Missing partition parameter: ds or bizdate "
            "(DataWorks 手动跑时 ${bizdate} 可能未展开，需 SKYNET_BIZDATE 或写死 ds=20260608)"
        )
    return ds


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_name(prefix: str, base: str) -> str:
    return f"{prefix}{base}"


def _clip_prefix(template: str, clip_id: str) -> str:
    return template.format(clip_id=clip_id).strip("/")


def _sql_string_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _fetch_dim_clip_created_at(client: Any, table_name: str, clip_id: str) -> str | None:
    safe_clip_id = clip_id.replace("'", "''")
    sql = f"SELECT created_at FROM {table_name} WHERE clip_id = '{safe_clip_id}' LIMIT 1"
    with client.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows:
        return None
    value = rows[0][0]
    return None if value is None else str(value)


def _upsert_dim_clip(client: Any, table_name: str, row: list[Any]) -> None:
    """Non-transactional dim_clip: DELETE 不可用，用 INSERT OVERWRITE 合并行。"""
    clip_id = str(row[0]).replace("'", "''")
    columns = (
        "clip_id, clip_dir_name, content_hash, active_run_id, "
        "created_at, updated_at, bag_oss_key"
    )
    new_values = ", ".join(_sql_string_literal(value) for value in row)
    sql = f"""
INSERT OVERWRITE TABLE {table_name}
SELECT {columns} FROM {table_name} WHERE clip_id != '{clip_id}'
UNION ALL
SELECT {new_values}
"""
    client.execute_sql(sql).wait_for_success()


def write_job1_to_mc(
    client: Any,
    *,
    table_prefix: str,
    ds: str,
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    bag_oss_key: str | None,
    run_id: str,
    bag_stem: str,
    parse_result: dict[str, Any],
) -> None:
    metadata = parse_result["metadata"]
    now = _utc_now_iso()
    partition = f"ds={ds}"

    dim_table_name = _table_name(table_prefix, "dim_clip")
    created_at = _fetch_dim_clip_created_at(client, dim_table_name, clip_id) or now
    _upsert_dim_clip(
        client,
        dim_table_name,
        [
            clip_id,
            clip_dir_name,
            content_hash,
            run_id,
            created_at,
            now,
            bag_oss_key or None,
        ],
    )

    run_table_name = _table_name(table_prefix, "pipeline_run")
    purge_clip_run_rows(
        client,
        table_name=run_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns="run_id, clip_id, status, started_at, updated_at, completed_at",
    )
    run_table = client.get_table(run_table_name)
    with run_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, clip_id, "completed", now, now, now]])

    step_table_name = _table_name(table_prefix, "pipeline_step")
    purge_pipeline_step_run(
        client,
        table_name=step_table_name,
        ds=ds,
        run_id=run_id,
        step_id="job1_parse",
    )
    step_table = client.get_table(step_table_name)
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
    timeline_table_name = _table_name(table_prefix, "fact_message_timeline")
    purge_clip_run_rows(
        client,
        table_name=timeline_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, topic, msgtype, modality, "
            "timestamp_ns, sequence_idx"
        ),
    )
    if timeline_rows:
        table = client.get_table(timeline_table_name)
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
    frame_table_name = _table_name(table_prefix, "fact_frame")
    purge_clip_run_rows(
        client,
        table_name=frame_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, camera, frame_idx, "
            "timestamp_ns, topic, image_path"
        ),
    )
    if frame_rows:
        table = client.get_table(frame_table_name)
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
    audio_table_name = _table_name(table_prefix, "fact_audio_chunk")
    purge_clip_run_rows(
        client,
        table_name=audio_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, chunk_idx, timestamp_ns, byte_offset, "
            "byte_length, sample_count, duration_ns, pcm_bytes"
        ),
    )
    if audio_rows:
        table = client.get_table(audio_table_name)
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
    event_table_name = _table_name(table_prefix, "fact_event")
    purge_clip_run_rows(
        client,
        table_name=event_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns="clip_id, run_id, bag_stem, timestamp_ns, event_data",
    )
    if event_rows:
        table = client.get_table(event_table_name)
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(event_rows)

    summary_table_name = _table_name(table_prefix, "clip_parse_summary")
    purge_clip_run_rows(
        client,
        table_name=summary_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, bag_file, duration_ns, duration_sec, "
            "start_time_ns, end_time_ns, message_count, topics_json, parsed_at"
        ),
    )
    summary_table = client.get_table(summary_table_name)
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


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job1_mc_write"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]
    ds = _resolve_ds()

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")

    clip_prefix = _clip_prefix(prefix_template, clip_id)
    payload_key = f"{clip_prefix}/runs/{run_id}/parsed/job1_mc_payload.json"
    oss_endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    print(f"Job1 MC write: reading oss://{oss_bucket}/{payload_key} via {oss_endpoint}")
    payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=payload_key,
        endpoint=oss_endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if payload is None:
        raise FileNotFoundError(
            f"Job1 payload not found: oss://{oss_bucket}/{payload_key} (run job1_parse first)"
        )

    parse_result = payload["parse_result"]
    write_job1_to_mc(
        o,  # type: ignore[name-defined]
        table_prefix=table_prefix,
        ds=ds,
        clip_id=str(payload.get("clip_id", clip_id)),
        clip_dir_name=str(payload["clip_dir_name"]),
        content_hash=str(payload["content_hash"]),
        bag_oss_key=str(payload.get("bag_oss_key") or "") or None,
        run_id=str(payload.get("run_id", run_id)),
        bag_stem=str(payload["bag_stem"]),
        parse_result=parse_result,
    )
    print(
        f"MC write done: clip_id={clip_id} run_id={run_id} ds={ds} "
        f"frames={len(parse_result['frames'])} "
        f"audio_chunks={len(parse_result['audio_chunks'])}"
    )


main()
