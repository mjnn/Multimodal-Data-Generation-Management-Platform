from __future__ import annotations

# =============================================================================
# DataWorks PyODPS3 · 极速探针（Driver-only，不启 MaxFrame / DPE）
#
# 粘贴整文件到节点。预期 30s–2min（无 DPE 排队/拉镜像）。
# 验证：工作流参数下发 + Driver AK 能读 OSS bag（HeadObject）。
#
# 不验证：DPE 镜像内 SDK（那一步请本机跑 probe_dpe_image_sdk.py，或夜间跑 dpe smoke）。
#
# 节点「自定义脚本」可只留：pip install alibabacloud_oss_v2 -q
# （不必装 maxframe，比 smoke 节点更快启动）
#
# 参数：workflow-params-sdk-fast.example
# =============================================================================

import json
import os
import re
import sys

_DEFAULTS = {
    "oss_bucket": "rosbag-labels-pipeline-bucket2",
    "cloud_region": "cn_shanghai",
    "bag_oss_key": "rosbags/2026-06-05_13-27-07/output.bag",
    "dpe_image": "rosbag_sdk_dpe",
}


def _parse_skynet_args(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        loaded = json.loads(text)
        return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
    out: dict[str, str] = {}
    for token in re.split(r"[;\s]+", text):
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _all_args() -> dict[str, str]:
    merged = dict(_DEFAULTS)
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    flow_raw = os.environ.get("SKYNET_FLOW_PARAVALUE", "")
    if flow_raw.strip().startswith("{"):
        try:
            flow = json.loads(flow_raw)
            inner = flow.get("__dw.workflow.parameters__")
            if isinstance(inner, str) and inner.strip().startswith("{"):
                merged.update({str(k): str(v) for k, v in json.loads(inner).items()})
        except json.JSONDecodeError:
            pass
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            for k, v in node_args.items():
                if v is not None and str(v).strip():
                    merged[str(k)] = str(v).strip()
    except NameError:
        pass
    return merged


def get_arg(name: str, default: str | None = None) -> str | None:
    value = _all_args().get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _head_bag(*, bucket: str, key: str, region: str, account) -> dict:
    import alibabacloud_oss_v2 as oss

    cfg = oss.config.load_default()
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
        account.access_id,
        account.secret_access_key,
    )
    cfg.region = region.replace("_", "-")
    client = oss.Client(cfg)
    resp = client.head_object(oss.HeadObjectRequest(bucket=bucket, key=key))
    headers = getattr(resp, "headers", None) or {}
    size = headers.get("Content-Length") or headers.get("content-length") or "0"
    return {"bag_exists": True, "bag_size": int(size)}


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    cfg = _all_args()
    required = ("oss_bucket", "oss_ram_role_arn", "dpe_image", "bag_oss_key")
    missing = [k for k in required if not get_arg(k)]
    print(
        "FAST_PROBE_ARGS="
        + json.dumps(
            {
                "keys": sorted(cfg.keys()),
                "missing_required": missing,
                "python": sys.version.split()[0],
                "skynet_args_len": len(os.environ.get("SKYNET_ARGS", "")),
            },
            ensure_ascii=False,
        )
    )
    if missing:
        raise SystemExit(f"missing params: {missing}")

    bucket = get_arg("oss_bucket") or ""
    bag_key = (get_arg("bag_oss_key") or "").lstrip("/")
    region = get_arg("cloud_region") or "cn_shanghai"
    result = {
        "ok": False,
        "mode": "driver_only",
        "oss_bucket": bucket,
        "bag_oss_key": bag_key,
        "dpe_image": get_arg("dpe_image"),
        "bag_exists": False,
        "bag_size": 0,
        "error": "",
    }
    try:
        meta = _head_bag(bucket=bucket, key=bag_key, region=region, account=account)
        result.update(meta)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"

    print("FAST_PROBE_RESULT=" + json.dumps(result, ensure_ascii=False))
    if not result["ok"]:
        raise SystemExit(result["error"] or "fast probe failed")
    print(f"OK fast probe: bag_size={result['bag_size']} dpe_image={result['dpe_image']}")


if __name__ == "__main__":
    main()
