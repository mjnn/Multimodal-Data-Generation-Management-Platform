from __future__ import annotations

# job2_sample_node.py — paste this single file into DataWorks PyODPS3

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


def write_oss_object_bytes(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    body: bytes,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    """Write one OSS object from the DataWorks driver (no MaxFrame STRING tunnel limit)."""
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
        raise RuntimeError("oss2 or alibabacloud_oss_v2 is required to write OSS objects")
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


def write_oss_object_text(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    text: str,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    write_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        body=text.encode("utf-8"),
        region=region,
        get_arg=get_arg,
    )


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
    write_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        body=body,
        region=region,
        get_arg=get_arg,
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

# === BEGIN sample_sync.py (auto-bundled) ===
"""Four-camera time-aligned sampling and sync-group helpers (Job2/Job3)."""


from typing import Any

DEFAULT_ALIGN_WINDOW_MS = 200


def align_window_ns_from_ms(window_ms: float | int) -> int:
    return int(float(window_ms) * 1_000_000)


def resolve_required_cameras(
    frames: list[dict[str, Any]],
    cameras: Any,
) -> list[str]:
    if cameras not in (None, "all", "*"):
        if isinstance(cameras, str):
            return sorted(item.strip() for item in cameras.split(",") if item.strip())
        return sorted(str(item) for item in cameras)
    return sorted({str(frame["camera"]) for frame in frames})


def _nearest_frame_in_window(
    camera_frames: list[dict[str, Any]],
    anchor_ns: int,
    window_ns: int,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_dist: int | None = None
    for frame in camera_frames:
        ts = int(frame["timestamp_ns"])
        dist = abs(ts - anchor_ns)
        if dist > window_ns:
            continue
        if best_dist is None or dist < best_dist:
            best = frame
            best_dist = dist
    return best


def sample_uniform_sync(
    frames: list[dict[str, Any]],
    *,
    interval_sec: float,
    align_window_ms: float | int = DEFAULT_ALIGN_WINDOW_MS,
    cameras: Any = "all",
    start_time_ns: int | None = None,
    end_time_ns: int | None = None,
    min_cameras: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (flat sampled_frames with sync_group_id, sample_groups metadata).

    Each sync group only emitted when all required cameras have a frame within
    ±align_window_ms of the anchor timestamp.
    """
    if not frames:
        return [], []

    interval_ns = int(float(interval_sec) * 1_000_000_000)
    window_ns = align_window_ns_from_ms(align_window_ms)
    required = resolve_required_cameras(frames, cameras)
    if not required:
        return [], []

    need = min_cameras if min_cameras is not None else len(required)
    need = max(1, min(need, len(required)))

    by_camera: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        if str(frame["camera"]) not in required:
            continue
        by_camera.setdefault(str(frame["camera"]), []).append(frame)
    for camera_frames in by_camera.values():
        camera_frames.sort(key=lambda item: int(item["timestamp_ns"]))

    all_ts = [int(frame["timestamp_ns"]) for frame in frames]
    range_start = int(start_time_ns if start_time_ns is not None else min(all_ts))
    range_end = int(end_time_ns if end_time_ns is not None else max(all_ts))
    if interval_ns <= 0:
        raise ValueError("interval_sec must be positive")

    flat: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    group_idx = 0
    anchor = range_start
    while anchor <= range_end:
        picked: list[dict[str, Any]] = []
        for camera in required:
            match = _nearest_frame_in_window(by_camera.get(camera, []), anchor, window_ns)
            if match is not None:
                picked.append(match)
        if len(picked) >= need and len(picked) == len(required):
            group_idx += 1
            sync_group_id = f"sg{group_idx:06d}"
            group_frames: list[dict[str, Any]] = []
            for frame in sorted(picked, key=lambda item: str(item["camera"])):
                row = dict(frame)
                row["sync_group_id"] = sync_group_id
                row["anchor_timestamp_ns"] = anchor
                group_frames.append(row)
                flat.append(row)
            groups.append(
                {
                    "sync_group_id": sync_group_id,
                    "anchor_timestamp_ns": anchor,
                    "cameras": [str(item["camera"]) for item in group_frames],
                    "frames": group_frames,
                }
            )
        anchor += interval_ns
    return flat, groups


def is_sync_sample_policy(policy: dict[str, Any] | None) -> bool:
    if not policy:
        return False
    return str(policy.get("type") or "") == "uniform_sync"


def group_manifest_by_sync(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(str(row.get("sync_group_id") or "").strip() for row in manifest_rows):
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        sync_group_id = str(row.get("sync_group_id") or "").strip()
        if not sync_group_id:
            continue
        bucket = grouped.setdefault(
            sync_group_id,
            {
                "sync_group_id": sync_group_id,
                "anchor_timestamp_ns": int(row.get("anchor_timestamp_ns") or row["timestamp_ns"]),
                "frames": [],
            },
        )
        bucket["frames"].append(row)
    return sorted(grouped.values(), key=lambda item: int(item["anchor_timestamp_ns"]))
# === END sample_sync.py ===

# =============================================================================
# DataWorks PyODPS 3 节点：Job2-抽样（MaxFrame + DPE）
# 粘贴整文件到 PyODPS3 节点；Driver 需 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 依赖：Job1 完成（parsed/job1_mc_payload.json）
# 写 OSS：
#   clips/{clip_id}/runs/{run_id}/job2/sample_manifest.jsonl
#   clips/{clip_id}/runs/{run_id}/job2/job2_sample_payload.json
#
# 编排：Job1 → Job2_sample ──→ Job3（与 Job2_asr 并行）
#       Job1 → Job2_asr  ──┘
# =============================================================================


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
        {
            "name": "uniform_sync",
            "type": "uniform_sync",
            "params": {
                "interval_sec": 1.0,
                "cameras": "all",
                "align_window_ms": DEFAULT_ALIGN_WINDOW_MS,
            },
        },
    ],
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


def _resolve_parsed_image_relpath(image_path: str, *, parsed_relpath: str, bag_stem: str) -> str:
    """Normalize Job1 frame image_path to path relative to parsed/ root."""
    raw = str(image_path or "").strip().lstrip("/")
    parsed_prefix = parsed_relpath.strip("/")
    if raw.startswith(parsed_prefix + "/"):
        return raw[len(parsed_prefix) + 1 :]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        return raw.rsplit(parsed_marker, 1)[-1].lstrip("/")
    if raw.startswith(f"{bag_stem}/"):
        return raw
    return f"{bag_stem}/{raw}"


def _build_job2_sample_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job2_config: dict[str, Any],
    sample_policy_name: str,
):
    def _job2_sample_row(row):
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        job1_payload_path = parsed_root / "job1_mc_payload.json"
        if not job1_payload_path.is_file():
            raise FileNotFoundError(f"Job1 payload not found: {job1_payload_path}")

        job1_payload = _read_json(job1_payload_path)
        parse_result = job1_payload["parse_result"]
        frames = parse_result.get("frames") or []
        events = parse_result.get("events") or []
        bag_stem = str(job1_payload.get("bag_stem") or row["bag_stem"])

        all_policies = job2_config.get("sample_policies") or DEFAULT_JOB2_CONFIG["sample_policies"]
        policy = _find_policy({"sample_policies": all_policies}, sample_policy_name)
        parse_metadata = parse_result.get("metadata") or {}
        policy_params = policy.get("params") or {}
        sample_groups: list[dict[str, Any]] = []

        if is_sync_sample_policy(policy):
            align_window_ms = float(
                policy_params.get("align_window_ms", DEFAULT_ALIGN_WINDOW_MS)
            )
            sampled_frames, _raw_groups = sample_uniform_sync(
                frames,
                interval_sec=float(policy_params.get("interval_sec", 1.0)),
                align_window_ms=align_window_ms,
                cameras=policy_params.get("cameras", "all"),
                start_time_ns=parse_metadata.get("start_time_ns"),
                end_time_ns=parse_metadata.get("end_time_ns"),
            )
        else:
            sampled_frames = apply_sample_policy(
                policy,
                frames=frames,
                events=events,
                all_policies=all_policies,
            )

        job2_root = Path(mount_path) / row["job2_relpath"]
        job2_root.mkdir(parents=True, exist_ok=True)

        manifest_rows = []
        parsed_relpath = str(row["parsed_relpath"])
        for frame in sampled_frames:
            image_relpath = _resolve_parsed_image_relpath(
                frame["image_path"],
                parsed_relpath=parsed_relpath,
                bag_stem=bag_stem,
            )
            row_out: dict[str, Any] = {
                "camera": frame["camera"],
                "frame_idx": int(frame["frame_idx"]),
                "timestamp_ns": int(frame["timestamp_ns"]),
                "topic": frame.get("topic"),
                "image_relpath": image_relpath,
                "sample_policy": sample_policy_name,
            }
            sync_group_id = str(frame.get("sync_group_id") or "").strip()
            if sync_group_id:
                row_out["sync_group_id"] = sync_group_id
                row_out["anchor_timestamp_ns"] = int(
                    frame.get("anchor_timestamp_ns") or frame["timestamp_ns"]
                )
            manifest_rows.append(row_out)

        if is_sync_sample_policy(policy):
            sample_groups = group_manifest_by_sync(manifest_rows)

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
            "sample_sync_mode": is_sync_sample_policy(policy),
            "sampled_frames": manifest_rows,
            "sample_groups": sample_groups,
            "processed_at": _utc_now_iso(),
        }
        payload_path = job2_root / "job2_sample_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": payload["clip_id"],
            "run_id": payload["run_id"],
            "sample_policy_name": sample_policy_name,
            "sampled_frame_count": len(manifest_rows),
            "sync_group_count": len(sample_groups),
            "manifest_relpath": f"{row['job2_relpath']}/sample_manifest.jsonl",
            "sample_payload_relpath": f"{row['job2_relpath']}/job2_sample_payload.json",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job2_sample_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job2_sample"):
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
    sample_policy_name = get_arg("sample_policy") or str(
        job2_config.get("active_sample_policy") or "uniform"
    )

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

    _job2_sample_row = _build_job2_sample_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options=_storage_options(role_arn, account),
        job2_config=job2_config,
        sample_policy_name=sample_policy_name,
    )

    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            _job2_sample_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "clip_id": "string",
                "run_id": "string",
                "sample_policy_name": "string",
                "sampled_frame_count": "int64",
                "sync_group_count": "int64",
                "manifest_relpath": "string",
                "sample_payload_relpath": "string",
            },
            skip_infer=True,
        )
        result = result_df.execute().fetch()
        if result.empty:
            raise RuntimeError("Job2 sample returned no rows")
        row = result.iloc[0]
        print(
            f"Job2 sample done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"policy={row['sample_policy_name']} "
            f"sampled_frames={row['sampled_frame_count']} "
            f"sync_groups={row.get('sync_group_count', 0)} "
            f"manifest={row['manifest_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
