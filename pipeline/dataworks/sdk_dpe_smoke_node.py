from __future__ import annotations

# =============================================================================
# DataWorks PyODPS3 · SDK DPE 烟雾探针（慢；仅验 DPE 内 SDK）
# 粘贴本文件整份到节点。冷启动常 5–15min+（DPE 排队/拉镜像），无法压到 2min。
#
# ⚡ 要快：用 sdk_driver_fast_probe_node.py（Driver-only，30s–2min）
# ⚡ 验镜像 SDK：本机 py -3.11 pipeline/scripts/probe_dpe_image_sdk.py --image rosbag_sdk_dpe
#
# 验证：DPE 镜像 + OSS 挂载 + oms_multimodal import
# 参数见：workflow-params-sdk-smoke.example
# =============================================================================
import json
import os
import re
from pathlib import Path
import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options

_DEFAULTS = {
    "oss_bucket": "rosbag-labels-pipeline-bucket2",
    "cloud_region": "cn_shanghai",
    "dpe_image": "rosbag_sdk_dpe",
    "mount_path": "/mnt/oss",
    "bag_oss_key": "rosbags/2026-06-05_13-27-07/output.bag",
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


def get_arg(name: str, default: str | None = None) -> str | None:
    merged = dict(_DEFAULTS)
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            for k, v in node_args.items():
                if v is not None and str(v).strip():
                    merged[str(k)] = str(v).strip()
    except NameError:
        pass
    value = merged.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _storage_options(role_arn: str | None, account, *, oss_bucket: str) -> dict[str, str]:
    opts: dict[str, str] = {"oss_bucket": oss_bucket}
    if role_arn:
        opts["role_arn"] = role_arn
        return opts
    return {
        **opts,
        "access_key_id": account.access_id,
        "access_key_secret": account.secret_access_key,
    }


def _build_smoke_udf(*, oss_mount_url: str, mount_path: str, storage_opts: dict[str, str]):
    def _smoke_row(row: pd.Series) -> dict:
        out = {
            "ok": False,
            "bag_exists": False,
            "bag_size": 0,
            "sdk_version": "",
            "has_content_parts": False,
            "has_rosbags": False,
            "python": "",
            "error": "",
        }
        try:
            import sys as _sys

            out["python"] = _sys.version.split()[0]
            bag_key = str(row["bag_oss_key"]).lstrip("/")
            bag_path = Path(mount_path) / bag_key
            out["bag_exists"] = bag_path.is_file()
            if out["bag_exists"]:
                out["bag_size"] = int(bag_path.stat().st_size)
                # Prove readable I/O without full parse.
                with bag_path.open("rb") as fh:
                    _ = fh.read(1024)

            import rosbags  # noqa: F401

            out["has_rosbags"] = True
            import oms_multimodal
            from oms_multimodal.mc import content_parts

            out["sdk_version"] = str(getattr(oms_multimodal, "__version__", ""))
            out["has_content_parts"] = hasattr(content_parts, "build_omni_label_parts")

            out["ok"] = bool(
                out["bag_exists"] and out["has_rosbags"] and out["has_content_parts"]
            )
            if not out["ok"] and not out["error"]:
                out["error"] = "smoke checks incomplete"
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    fn = with_running_options(engine="dpe", cpu=1, memory=4)(_smoke_row)
    return with_fs_mount(oss_mount_url, mount_path, storage_options=storage_opts)(fn)


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    oss_bucket = get_arg("oss_bucket") or _DEFAULTS["oss_bucket"]
    region = get_arg("cloud_region") or _DEFAULTS["cloud_region"]
    mount_path = get_arg("mount_path") or get_arg("dpe_mount_path") or _DEFAULTS["mount_path"]
    dpe_image = (get_arg("dpe_image") or _DEFAULTS["dpe_image"]).strip()
    bag_oss_key = get_arg("bag_oss_key") or _DEFAULTS["bag_oss_key"]
    role_arn = get_arg("oss_ram_role_arn")

    print(
        "SMOKE_ARGS="
        + json.dumps(
            {
                "oss_bucket": oss_bucket,
                "dpe_image": dpe_image,
                "bag_oss_key": bag_oss_key,
                "has_role_arn": bool(role_arn),
            },
            ensure_ascii=False,
        )
    )

    region_dash = region.replace("_", "-")
    oss_mount_url = f"oss://oss-{region_dash}-internal.aliyuncs.com/{oss_bucket}/"
    storage_opts = _storage_options(role_arn, account, oss_bucket=oss_bucket)
    print(f"SMOKE_MOUNT_URL={oss_mount_url}")

    mf_options.session.max_alive_seconds = 1800
    mf_options.session.max_idle_seconds = 1800
    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    sql_settings["odps.session.image"] = dpe_image
    sql_settings["odps.function.timeout"] = "600"
    sql_settings["odps.sql.executionengine.batch.rowcount"] = "1"
    mf_options.sql.settings = sql_settings
    mf_options.local_execution.enabled = False

    udf = _build_smoke_udf(
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_opts=storage_opts,
    )

    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")
        input_df = md.DataFrame(pd.DataFrame([{"bag_oss_key": bag_oss_key}]))
        result_df = input_df.apply(
            udf,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={
                "ok": "bool",
                "bag_exists": "bool",
                "bag_size": "int64",
                "sdk_version": "string",
                "has_content_parts": "bool",
                "has_rosbags": "bool",
                "python": "string",
                "error": "string",
            },
            skip_infer=True,
        )
        out = result_df.execute().fetch()
        row = out.iloc[0].to_dict()
        print("SMOKE_RESULT=" + json.dumps(row, ensure_ascii=False, default=str))
        if not row.get("ok"):
            raise SystemExit(f"smoke failed: {row.get('error') or row}")
        print(
            f"OK smoke: sdk={row.get('sdk_version')} bag_size={row.get('bag_size')}"
        )
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
