"""Trigger DataWorks manual workflow (sdk hybrid driver) via OpenAPI."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

_DEFAULTS_PATH = Path(__file__).resolve().parent / "dataworks_sdk_pipeline_defaults.yaml"
_DAG_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DAG_STATUS_TTL_SEC = 300.0  # 5 min — GetDag counts against DW OpenAPI quota
_THROTTLE_UNTIL_MONO = 0.0
_THROTTLE_LAST_MSG = ""
_start_throttle_applied = False


class DataWorksThrottleError(RuntimeError):
    """DataWorks OpenAPI quota exhausted; circuit open."""


def _throttle_cooldown_sec() -> float:
    raw = _env("DATAWORKS_THROTTLE_COOLDOWN_SEC", "900") or "900"
    try:
        return max(60.0, float(raw))
    except ValueError:
        return 900.0


def throttle_seconds_remaining() -> float:
    return max(0.0, _THROTTLE_UNTIL_MONO - time.monotonic())


def is_throttle_circuit_open() -> bool:
    return throttle_seconds_remaining() > 0


def _trip_throttle_circuit(exc: BaseException | None = None) -> None:
    global _THROTTLE_UNTIL_MONO, _THROTTLE_LAST_MSG
    cool = _throttle_cooldown_sec()
    _THROTTLE_UNTIL_MONO = time.monotonic() + cool
    _THROTTLE_LAST_MSG = str(exc) if exc else _THROTTLE_LAST_MSG
    logger.warning(
        "DataWorks OpenAPI throttle circuit OPEN for %.0fs (no further API calls)",
        cool,
    )


def _ensure_circuit_allows(api: str) -> None:
    rem = throttle_seconds_remaining()
    if rem <= 0:
        return
    mins = int(rem // 60) + (1 if rem % 60 else 0)
    raise DataWorksThrottleError(
        f"DataWorks OpenAPI 配额熔断中（约剩余 {mins} 分钟），暂不可调用 {api}。"
        "请稍后再触发；期间 HMI 不会再请求 GetDag/CreateDagTest，以免继续耗尽配额。"
        + (f" 上次错误: {_THROTTLE_LAST_MSG[:200]}" if _THROTTLE_LAST_MSG else "")
    )


class DataWorksConfigError(RuntimeError):
    """Missing or invalid DataWorks trigger configuration."""


def _env(name: str, default: str = "") -> str:
    # Strip inline comments: VALUE  # comment
    raw = (os.getenv(name) or default).strip()
    if " #" in raw:
        raw = raw.split(" #", 1)[0].rstrip()
    elif raw.endswith("#") is False and "\t#" in raw:
        raw = raw.split("\t#", 1)[0].rstrip()
    return raw.strip().strip('"').strip("'")


def require_dataworks_config() -> dict[str, str]:
    global _start_throttle_applied
    project_name = _env("DATAWORKS_PROJECT_NAME")
    flow_name = _env("DATAWORKS_FLOW_NAME")
    node_id = _env("DATAWORKS_NODE_ID")
    # smoke = CreateDagTest (周期节点冒烟)；manual = RunManualDagNodes（已发布手动业务流程）
    # auto = 有 FLOW_NAME 先 manual，业务流程不存在则回退 smoke
    mode = (_env("DATAWORKS_TRIGGER_MODE", "auto") or "auto").lower()
    if mode not in ("auto", "smoke", "manual"):
        raise DataWorksConfigError(
            f"DATAWORKS_TRIGGER_MODE must be auto|smoke|manual (got {mode!r})"
        )
    access_id = _env("ODPS_ACCESS_ID") or _env("ALIBABA_CLOUD_ACCESS_KEY_ID")
    access_key = _env("ODPS_ACCESS_KEY") or _env("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    required: list[tuple[str, str]] = [
        ("DATAWORKS_PROJECT_NAME", project_name),
        ("DATAWORKS_NODE_ID", node_id),
        ("ODPS_ACCESS_ID (or ALIBABA_CLOUD_ACCESS_KEY_ID)", access_id),
        ("ODPS_ACCESS_KEY (or ALIBABA_CLOUD_ACCESS_KEY_SECRET)", access_key),
    ]
    if mode == "manual":
        required.insert(1, ("DATAWORKS_FLOW_NAME", flow_name))
    missing = [k for k, v in required if not v]
    if missing:
        raise DataWorksConfigError(
            "DataWorks trigger not configured; set: " + ", ".join(missing)
        )
    if not node_id.isdigit():
        raise DataWorksConfigError(
            f"DATAWORKS_NODE_ID must be numeric DataWorks node id (got {node_id!r}); "
            "open the node in DataWorks → properties → copy 节点 ID"
        )
    if not _start_throttle_applied:
        _start_throttle_applied = True
        flag = (_env("DATAWORKS_START_IN_THROTTLE", "") or "").lower()
        if flag in {"1", "true", "yes", "on"}:
            _trip_throttle_circuit(
                RuntimeError("DATAWORKS_START_IN_THROTTLE=1 (rest DataWorks OpenAPI quota)")
            )
    return {
        "project_name": project_name,
        "flow_name": flow_name,
        "node_id": node_id,
        "trigger_mode": mode,
        "project_env": _env("DATAWORKS_PROJECT_ENV", "PROD") or "PROD",
        "region_id": _env("DATAWORKS_REGION_ID", "cn-shanghai") or "cn-shanghai",
        "access_id": access_id,
        "access_key": access_key,
    }


def _load_yaml_defaults() -> dict[str, str]:
    custom = _env("DATAWORKS_DEFAULT_PARAMS")
    path = Path(custom) if custom else _DEFAULTS_PATH
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("dataworks defaults load failed: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        out[str(k)] = str(v).strip()
    return out


def _parse_extra_params(raw: str) -> dict[str, str]:
    """Parse space- or newline-separated key=value pairs."""
    out: dict[str, str] = {}
    for part in raw.replace("\n", " ").split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def build_node_param_string(bag_oss_keys: list[str], *, ds: str | None = None) -> str:
    """Build scheduling param string: key=value pairs separated by spaces."""
    keys = [k.strip().lstrip("/") for k in bag_oss_keys if k and k.strip()]
    if not keys:
        raise ValueError("bag_oss_keys required")

    params = _load_yaml_defaults()
    params.update(_parse_extra_params(_env("DATAWORKS_EXTRA_PARAMS")))

    # From cloud settings when not overridden
    from hmi.config import get_settings

    settings = get_settings()
    params.setdefault("oss_bucket", settings.get("oss_bucket") or "")
    params.setdefault("cloud_region", _env("CLOUD_REGION", "cn_shanghai") or "cn_shanghai")
    if _env("DPE_IMAGE"):
        params.setdefault("dpe_image", _env("DPE_IMAGE"))
    if _env("OSS_RAM_ROLE_ARN"):
        params.setdefault("oss_ram_role_arn", _env("OSS_RAM_ROLE_ARN"))

    ds_val = (ds or datetime.now(timezone.utc).strftime("%Y%m%d")).strip()
    params["ds"] = ds_val
    params["bag_oss_keys"] = ",".join(keys)
    params["max_bags"] = str(len(keys))

    # Prefer bag_oss_keys list; clear single-bag triplet if present in template
    params.pop("bag_oss_key", None)
    params.pop("clip_id", None)
    params.pop("run_id", None)

    parts: list[str] = []
    for k in sorted(params.keys()):
        v = params[k]
        if not v:
            continue
        # Node param values must not contain spaces that break key=value parsing;
        # commas in bag_oss_keys are fine.
        if " " in v or "\n" in v:
            raise ValueError(f"DataWorks param {k} must not contain whitespace")
        parts.append(f"{k}={v}")
    return " ".join(parts)


def _biz_date() -> str:
    """DataWorks BizDate must be <= yesterday 00:00:00."""
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    return f"{day.isoformat()} 00:00:00"


def _client(cfg: dict[str, str]):
    try:
        from alibabacloud_dataworks_public20200518.client import Client
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError as exc:
        raise DataWorksConfigError(
            "Missing package alibabacloud_dataworks_public20200518; "
            "pip install -r hmi/backend/requirements.txt"
        ) from exc

    config = open_api_models.Config(
        access_key_id=cfg["access_id"],
        access_key_secret=cfg["access_key"],
        region_id=cfg["region_id"],
    )
    # dataworks endpoint by region
    config.endpoint = f"dataworks.{cfg['region_id']}.aliyuncs.com"
    return Client(config)


def _is_throttle_error(exc: BaseException) -> bool:
    text = str(exc)
    return (
        "Throttling" in text
        or "throttl" in text.lower()
        or "reached the upper limit" in text
        or "调用次数" in text
    )


def _call_with_throttle_retry(
    fn: Callable[[], Any],
    *,
    api: str,
    attempts: int = 1,
    base_sleep_sec: float = 30.0,
) -> Any:
    """Call DataWorks OpenAPI; on throttle open circuit (do NOT spam retries)."""
    _ensure_circuit_allows(api)
    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if _is_throttle_error(exc):
                _trip_throttle_circuit(exc)
                raise
            if i >= attempts - 1:
                raise
            sleep_s = base_sleep_sec * (2**i)
            logger.warning(
                "DataWorks %s failed; retry %s/%s after %.0fs: %s",
                api,
                i + 1,
                attempts,
                sleep_s,
                exc,
            )
            time.sleep(sleep_s)
    assert last is not None
    raise last


def _friendly_run_error(exc: BaseException, cfg: dict[str, str], *, api: str) -> str:
    """Map common DataWorks OpenAPI errors to actionable Chinese hints."""
    text = str(exc)
    code = ""
    if isinstance(exc, DataWorksThrottleError) or _is_throttle_error(exc):
        rem = throttle_seconds_remaining()
        mins = max(1, int(rem // 60) + (1 if rem % 60 else 0)) if rem else int(_throttle_cooldown_sec() // 60)
        return (
            f"DataWorks OpenAPI 调用次数已达上限（Throttling.Resource），熔断约 {mins} 分钟。"
            "请不要连续重试上传触发；可在 DataWorks 控制台手动跑 p0，或升级版本提高配额。"
            f" 原始错误: {text}"
        )
    if "10600111020399005" in text or "项目不存在" in text:
        return (
            f"DataWorks 项目不存在: {cfg['project_name']!r}。"
            "请把 DATAWORKS_PROJECT_NAME 设为工作空间「英文标识」"
            "（控制台 → 工作空间列表；可用 scripts/list_dataworks_projects.py 列出）。"
            f" 原始错误: {text}"
        )
    if "业务流程不存在" in text or (
        "10600111020399006" in text and "flow" in text.lower()
    ):
        return (
            f"DataWorks 手动业务流程不存在: flow={cfg.get('flow_name')!r} "
            f"env={cfg['project_env']!r}。"
            "周期调度节点请设 DATAWORKS_TRIGGER_MODE=smoke（CreateDagTest）；"
            "或新建并发布「手动业务流程」后填 DATAWORKS_FLOW_NAME。"
            f" 原始错误: {text}"
        )
    if "'Code': '" in text:
        code = text.split("'Code': '", 1)[1].split("'", 1)[0]
    prefix = f"DataWorks {api} failed"
    if code:
        prefix += f" [{code}]"
    return f"{prefix}: {text}"


def _is_flow_missing_error(exc: BaseException) -> bool:
    text = str(exc)
    return "业务流程不存在" in text or "10600111020399006" in text


def _trigger_manual(
    client: Any,
    cfg: dict[str, str],
    *,
    node_params_body: str,
    biz_date: str,
) -> str:
    from alibabacloud_dataworks_public20200518 import models as dw_models

    if not cfg.get("flow_name"):
        raise DataWorksConfigError(
            "DATAWORKS_FLOW_NAME required for trigger_mode=manual"
        )
    node_parameters = json.dumps({cfg["node_id"]: node_params_body}, ensure_ascii=False)
    request = dw_models.RunManualDagNodesRequest(
        project_env=cfg["project_env"],
        project_name=cfg["project_name"],
        flow_name=cfg["flow_name"],
        biz_date=biz_date,
        node_parameters=node_parameters,
        include_node_ids=cfg["node_id"],
    )
    logger.info(
        "dataworks RunManualDagNodes flow=%s node=%s",
        cfg["flow_name"],
        cfg["node_id"],
    )
    try:
        response = _call_with_throttle_retry(
            lambda: client.run_manual_dag_nodes(request),
            api="RunManualDagNodes",
            attempts=1,
        )
    except Exception as exc:
        raise RuntimeError(_friendly_run_error(exc, cfg, api="RunManualDagNodes")) from exc

    body = getattr(response, "body", None)
    dag_id = getattr(body, "dag_id", None) if body is not None else None
    if dag_id is None:
        raise RuntimeError(f"DataWorks returned no DagId: {response}")
    return str(dag_id)


def _trigger_smoke(
    client: Any,
    cfg: dict[str, str],
    *,
    node_params_body: str,
    biz_date: str,
) -> str:
    """CreateDagTest — works for published cycle (NORMAL) nodes like p0."""
    from alibabacloud_dataworks_public20200518 import models as dw_models

    request = dw_models.CreateDagTestRequest(
        project_env=cfg["project_env"],
        node_id=int(cfg["node_id"]),
        name=f"hmi_{cfg['node_id']}",
        bizdate=biz_date,
        node_params=node_params_body,
    )
    logger.info("dataworks CreateDagTest node=%s", cfg["node_id"])
    try:
        response = _call_with_throttle_retry(
            lambda: client.create_dag_test(request),
            api="CreateDagTest",
            attempts=1,
        )
    except Exception as exc:
        raise RuntimeError(_friendly_run_error(exc, cfg, api="CreateDagTest")) from exc

    body = getattr(response, "body", None)
    # SDK field is often `data` holding the DagId long
    dag_id = getattr(body, "data", None) if body is not None else None
    if dag_id is None and body is not None:
        dag_id = getattr(body, "dag_id", None)
    if dag_id is None:
        raise RuntimeError(f"DataWorks CreateDagTest returned no DagId: {response}")
    return str(dag_id)


def trigger_sdk_pipeline(bag_oss_keys: list[str], *, ds: str | None = None) -> dict[str, Any]:
    """Trigger Driver node; return dag_id and echo of params.

    Modes (DATAWORKS_TRIGGER_MODE):
    - smoke: CreateDagTest on DATAWORKS_NODE_ID (周期节点)
    - manual: RunManualDagNodes on DATAWORKS_FLOW_NAME
    - auto: manual if FLOW_NAME set, else smoke; 业务流程不存在时回退 smoke
    """
    cfg = require_dataworks_config()
    node_params_body = build_node_param_string(bag_oss_keys, ds=ds)
    biz_date = _biz_date()
    client = _client(cfg)
    mode = cfg["trigger_mode"]
    used = mode

    if mode == "smoke" or (mode == "auto" and not cfg.get("flow_name")):
        used = "smoke"
        dag_id = _trigger_smoke(
            client, cfg, node_params_body=node_params_body, biz_date=biz_date
        )
    elif mode == "manual":
        used = "manual"
        dag_id = _trigger_manual(
            client, cfg, node_params_body=node_params_body, biz_date=biz_date
        )
    else:
        # auto + flow_name: try manual, fall back to smoke
        try:
            used = "manual"
            dag_id = _trigger_manual(
                client, cfg, node_params_body=node_params_body, biz_date=biz_date
            )
        except RuntimeError as exc:
            if not _is_flow_missing_error(exc):
                raise
            logger.warning(
                "manual flow %r missing; falling back to CreateDagTest: %s",
                cfg.get("flow_name"),
                exc,
            )
            used = "smoke"
            dag_id = _trigger_smoke(
                client, cfg, node_params_body=node_params_body, biz_date=biz_date
            )

    return {
        "dag_id": dag_id,
        "trigger_mode": used,
        "flow_name": cfg.get("flow_name") or None,
        "project_name": cfg["project_name"],
        "project_env": cfg["project_env"],
        "biz_date": biz_date,
        "node_id": cfg["node_id"],
        "node_parameters": node_params_body,
    }


def get_dag_status(dag_id: str) -> dict[str, Any]:
    """Query GetDag; map status to pending|running|completed|failed."""
    cache_key = str(dag_id)
    now = time.monotonic()
    cached = _DAG_STATUS_CACHE.get(cache_key)
    if cached and now - cached[0] < _DAG_STATUS_TTL_SEC:
        return dict(cached[1])

    if is_throttle_circuit_open():
        # Prefer last cache even if stale; otherwise skip API
        if cached:
            return dict(cached[1])
        return {
            "dag_id": dag_id,
            "raw_status": None,
            "pipeline_status": None,
            "error": "throttle_circuit_open",
        }

    cfg = require_dataworks_config()
    from alibabacloud_dataworks_public20200518 import models as dw_models

    client = _client(cfg)
    request = dw_models.GetDagRequest(
        dag_id=int(dag_id),
        project_env=cfg["project_env"],
    )
    try:
        response = _call_with_throttle_retry(
            lambda: client.get_dag(request),
            api="GetDag",
            attempts=1,
        )
    except DataWorksThrottleError as exc:
        logger.warning("GetDag skipped (circuit): %s", exc)
        if cached:
            return dict(cached[1])
        return {
            "dag_id": dag_id,
            "raw_status": None,
            "pipeline_status": None,
            "error": str(exc),
        }
    except Exception as exc:
        if _is_throttle_error(exc):
            _trip_throttle_circuit(exc)
        logger.warning("GetDag failed dag_id=%s: %s", dag_id, exc)
        out = {
            "dag_id": dag_id,
            "raw_status": None,
            "pipeline_status": None,
            "error": str(exc),
        }
        if _is_throttle_error(exc):
            _DAG_STATUS_CACHE[cache_key] = (now, out)
        return out

    data = getattr(getattr(response, "body", None), "data", None)
    raw = str(getattr(data, "status", "") or "").upper() if data is not None else ""
    mapping = {
        "CREATED": "pending",
        "RUNNING": "running",
        "SUCCESS": "completed",
        "FAILURE": "failed",
    }
    out = {
        "dag_id": dag_id,
        "raw_status": raw or None,
        "pipeline_status": mapping.get(raw),
        "name": getattr(data, "name", None) if data is not None else None,
    }
    _DAG_STATUS_CACHE[cache_key] = (now, out)
    return dict(out)
