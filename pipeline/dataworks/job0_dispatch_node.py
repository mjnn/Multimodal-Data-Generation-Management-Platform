# =============================================================================

# DataWorks PyODPS 3 节点：Job0-调度（Driver）

#

# 在 job0_discover 之后运行：从 dim_clip 挑选待处理 clip，生成/复用 run_id，

# 写入 OSS ``pipeline/dispatch/latest.json``；下游 Job1~4 通过

# ``resolve_pipeline_context()`` 读该 manifest（不依赖赋值节点 / 节点输出参数）。

#

# 工作流连线：job0_discover → job0_dispatch → job1_parse → ...

# 粘贴：python scripts/bundle_pipeline_dispatch.py dataworks/job0_dispatch_node.py

# =============================================================================



from __future__ import annotations



import json

import os

import re

from typing import Any



from pipeline_dispatch import (
    DEFAULT_DISPATCH_OSS_KEY,
    attach_taxonomy_to_dispatch_payload,
    pick_dispatch_target,
    resolve_oss_http_endpoint,
    write_dispatch_to_oss,
)



_PROJECT_DEFAULTS: dict[str, str] = {

    "oss_bucket": "rosbag-labels-pipeline-bucket2",

    "cloud_region": "cn_shanghai",

    "table_prefix": "aig_rosbag__",

    "dispatch_oss_key": DEFAULT_DISPATCH_OSS_KEY,

    "pipeline_version": "clip_omni_v2",

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

        raise ValueError(f"Missing required parameter: {name}")

    return value





def main() -> None:

    table_prefix = get_arg("table_prefix", "aig_rosbag__") or "aig_rosbag__"

    oss_bucket = require_arg("oss_bucket")

    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"

    dispatch_key = get_arg("dispatch_oss_key", DEFAULT_DISPATCH_OSS_KEY) or DEFAULT_DISPATCH_OSS_KEY

    dry_run = str(get_arg("dry_run", "false")).lower() in {"1", "true", "yes"}



    account = o.account  # type: ignore[name-defined]

    payload = pick_dispatch_target(o, table_prefix, get_arg=get_arg)  # type: ignore[name-defined]

    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    payload = attach_taxonomy_to_dispatch_payload(
        payload,
        bucket_name=oss_bucket,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )

    print(f"Job0 dispatch: action={payload.get('action')} reason={payload.get('reason')}")

    if payload.get("action") == "run":

        print(

            f"DISPATCH clip_id={payload.get('clip_id')} run_id={payload.get('run_id')} "

            f"bag_oss_key={payload.get('bag_oss_key')}"

        )

    else:

        print("PIPELINE_IDLE: no clip needs processing; downstream nodes will no-op")



    print(f"DISPATCH_JSON={json.dumps(payload, ensure_ascii=False)}")



    if dry_run:

        print("Job0 dispatch dry_run: skip OSS write")

        return



    write_dispatch_to_oss(

        bucket_name=oss_bucket,

        object_key=dispatch_key,

        endpoint=resolve_oss_http_endpoint(cloud_region, get_arg=get_arg),

        account=account,

        payload=payload,

        region=cloud_region,

        get_arg=get_arg,

    )

    print(f"Job0 dispatch OSS manifest: oss://{oss_bucket}/{dispatch_key}")





main()

